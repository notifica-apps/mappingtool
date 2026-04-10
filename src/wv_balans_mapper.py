"""
WV (Winst & Verlies) and Balans Mapping Module

Principe: het mappingbestand (1000_) is ALTIJD leidend.
Elke verrijking (CoA_code, Niveau1, Niveau2) moet exact overeenkomen
met een combinatie die in het mappingbestand voorkomt.
"""
import os
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import pytz

from .normalization import normalize_rubriek, clean_coa_code
from .matching import MappingIndex, WVBalansMatcher
from .quality import analyze_mapping_quality, QualityReport
from .utils import (
    read_csv_robust,
    validate_columns,
    write_csv_output,
    get_output_filename,
    extract_base_name,
)


class WVBalansMapper:
    """
    Mapper for WV (Winst & Verlies) and Balans that enriches target files
    with CoA_code, Niveau1, and Niveau2.

    Het mappingbestand is leidend: alle output-combinaties moeten
    exact voorkomen in het mappingbestand. Geen afgeleide of nieuwe
    combinaties worden toegestaan.
    """

    REQUIRED_MAPPING_COLS = ['Rubriek', 'CoA_code', 'Niveau1', 'Niveau2']
    REQUIRED_TARGET_COLS = ['Rubriek']

    # Harde regels: eerste cijfer grootboeknummer -> toegestane Niveau1 waarden
    GB_RULES: Dict[str, List[str]] = {
        '8': ['Omzet'],
        '7': ['Directe kosten'],
        '4': ['Overige bedrijfskosten', 'Personeelkosten'],
    }

    def __init__(self, min_fill_rate: float = 0.90):
        self.min_fill_rate = min_fill_rate
        self.index: Optional[MappingIndex] = None
        self.matcher: Optional[WVBalansMatcher] = None
        self.valid_combos: Set[Tuple[str, str, str]] = set()
        self.quality_report: Optional[QualityReport] = None
        self.mapping_stats = {}
        self.run_stats = {}
        # DWH grootboeknummer lookup: RubriekKey -> gb_code (eerste cijfer)
        self._gb_lookup: Dict[str, str] = {}

    def load_mapping(self, mapping_path_or_content, is_content: bool = False, filename: str = "") -> Dict[str, Any]:
        """Load and index the mapping file. Bouwt ook de set van geldige combinaties."""
        df, delimiter = read_csv_robust(mapping_path_or_content, is_content)
        self._mapping_df = df  # Bewaar voor quality analysis
        col_map = validate_columns(df, self.REQUIRED_MAPPING_COLS, "Mapping file")

        self.index = MappingIndex()
        self.valid_combos = set()

        valid_rows = 0
        skipped_rows = 0

        for idx, row in df.iterrows():
            rubriek = str(row[col_map['Rubriek']]).strip() if pd.notna(row[col_map['Rubriek']]) else ""
            code = row[col_map['CoA_code']]
            niveau1 = str(row[col_map['Niveau1']]).strip() if pd.notna(row[col_map['Niveau1']]) else ""
            niveau2 = str(row[col_map['Niveau2']]).strip() if pd.notna(row[col_map['Niveau2']]) else ""

            if not rubriek:
                skipped_rows += 1
                continue

            code = clean_coa_code(code)
            if not code or not niveau1 or not niveau2:
                skipped_rows += 1
                continue

            norm_rubriek = normalize_rubriek(rubriek)
            if not norm_rubriek:
                skipped_rows += 1
                continue

            combination = (code, niveau1, niveau2)
            self.valid_combos.add(combination)
            self.index.add(norm_rubriek, combination)
            valid_rows += 1

        self.index.resolve()
        self.matcher = WVBalansMatcher(self.index)

        # Kwaliteitsanalyse op het mapping bestand
        mapping_type = 'Balans' if self.matcher._is_balans else 'WV'
        self.quality_report = analyze_mapping_quality(
            df, mapping_type,
            rubriek_col=col_map['Rubriek'],
            niveau1_col=col_map['Niveau1'],
            niveau2_col=col_map['Niveau2'],
        )

        self.mapping_stats = {
            'total_rows': len(df),
            'valid_rows': valid_rows,
            'skipped_rows': skipped_rows,
            'unique_keys': len(self.index._resolved),
            'valid_combos': len(self.valid_combos),
            'quality_issues': self.quality_report.total_issues if self.quality_report else 0,
        }

        return self.mapping_stats

    def load_gb_lookup(self, data_key: str, klantnummer: int):
        """
        Laad grootboeknummer-lookup uit het DWH via de Notifica Data API.

        Bouwt dicts:
        - _gb_lookup: RubriekKey -> eerste cijfer van grootboeknummer
        - _gb_full_code: RubriekKey -> volledige GB code
        - _gb_namen: RubriekKey -> grootboeknaam
        - _name_to_full_code: genormaliseerde naam -> volledige GB code
        """
        import re
        try:
            import sys
            sdk_paths = [
                os.path.join(os.path.dirname(os.path.dirname(__file__)), '_sdk'),
                'c:/projects/tools_en_analyses/demo-dashboard/_sdk',
            ]
            for p in sdk_paths:
                if p not in sys.path and os.path.isdir(p):
                    sys.path.insert(0, p)

            from notifica_sdk import NotificaClient
            client = NotificaClient(data_key=data_key)
            df = client.query(klantnummer, '''
                SELECT DISTINCT "RubriekKey", "Grootboekrekening code" as gb_code,
                       "Grootboekrekening" as gb_naam
                FROM financieel."Grootboekrekeningen"
                WHERE "RubriekKey" IS NOT NULL
            ''')
            self._gb_namen: Dict[str, str] = {}
            self._gb_full_code: Dict[str, str] = {}
            self._name_to_full_code: Dict[str, str] = {}
            for _, row in df.iterrows():
                rkey = str(int(row['RubriekKey'])) if pd.notna(row['RubriekKey']) else None
                gb_code = str(row['gb_code']).strip()
                gb_naam = str(row.get('gb_naam', '')).strip()
                if rkey and gb_code and gb_code[0].isdigit():
                    self._gb_lookup[rkey] = gb_code[0]
                    self._gb_full_code[rkey] = gb_code
                    self._gb_namen[rkey] = gb_naam
                    # Bouw naam-lookup: strip prefix "4733 - " en Direct/Indirect
                    clean = re.sub(r'^\d+\s*-\s*', '', gb_naam).strip()
                    base = re.sub(r'^\((?:Direct|Indirect)\)\s*', '', clean).strip().lower()
                    if base:
                        self._name_to_full_code[base] = gb_code
        except Exception as e:
            print(f"Waarschuwing: DWH grootboeknummer-lookup mislukt: {e}")
            self._gb_lookup = {}

    def fill_gb_gaps(self, target_df: pd.DataFrame):
        """
        Vul ontbrekende GB-lookups aan op basis van naam-matching.

        Items zonder DWH-koppeling erven de VOLLEDIGE GB-code
        van hun tegenhanger die WEL in het DWH staat.
        """
        import re
        if not self._gb_lookup:
            return

        filled = 0
        for _, row in target_df.iterrows():
            rkey = str(int(row['RubriekKey'])) if pd.notna(row.get('RubriekKey')) else None
            if rkey and rkey not in self._gb_lookup:
                rubriek = str(row.get('Rubriek', '')).strip()
                base = re.sub(r'^\((?:Direct|Indirect)\)\s*', '', rubriek).strip().lower()
                full_code = self._name_to_full_code.get(base)
                if full_code:
                    self._gb_lookup[rkey] = full_code[0]
                    self._gb_full_code[rkey] = full_code
                    filled += 1
        if filled:
            print(f"GB gaps gevuld: {filled} items via naam-matching")

    def _validate_gb_rule(self, rubriek_key: str, niveau1: str) -> bool:
        """
        Valideer Niveau1 tegen harde grootboeknummer-regels.

        Returns True als er geen schending is (of geen lookup beschikbaar).
        """
        if not self._gb_lookup or not rubriek_key:
            return True
        first_digit = self._gb_lookup.get(str(rubriek_key))
        if first_digit and first_digit in self.GB_RULES:
            return niveau1 in self.GB_RULES[first_digit]
        return True

    def _find_gb_alternative(
        self, norm_rubriek: str, allowed_niveau1: List[str],
        rubriek_key: str = None
    ) -> Optional[Tuple]:
        """
        Zoek een alternatieve valid combo waarvan Niveau1 in de toegestane lijst staat.

        Strategie (in volgorde):
        1. Zoek rubrieken in dezelfde GB-nummerreeks (bijv. 47xx) die al correct
           gematcht zijn in de index, en neem hun Niveau2 over
        2. Zoek een directe fuzzy match met het juiste Niveau1
        3. Fallback: meest voorkomende Niveau2 voor dat Niveau1
        """
        if not allowed_niveau1:
            return None

        candidates = [c for c in self.valid_combos if c[1] in allowed_niveau1]
        if not candidates:
            return None

        # Strategie 1: Buurt-context via GB-nummerreeks
        # Items in dezelfde 2-digit range (bijv. alle 47xx) hebben meestal dezelfde Niveau2
        if rubriek_key and hasattr(self, '_gb_full_code'):
            full_code = self._gb_full_code.get(rubriek_key, '')
            if len(full_code) >= 2:
                prefix = full_code[:2]
                # Zoek andere RubriekKeys in dezelfde reeks die WEL correct gematcht zijn
                neighbor_combos = Counter()
                for rk, fc in self._gb_full_code.items():
                    if fc[:2] == prefix and rk != rubriek_key:
                        # Zoek dit item in de index
                        gb_naam = self._gb_namen.get(rk, '')
                        if gb_naam:
                            import re
                            clean = re.sub(r'^\d+\s*-\s*', '', gb_naam).strip()
                            norm_neighbor = normalize_rubriek(clean)
                            if norm_neighbor and self.index and hasattr(self.index, '_resolved'):
                                combo = self.index._resolved.get(norm_neighbor)
                                if combo and combo[1] in allowed_niveau1:
                                    neighbor_combos[combo] += 1
                if neighbor_combos:
                    # Neem de meest voorkomende combo in de buurt
                    return neighbor_combos.most_common(1)[0][0]

        # Strategie 2: Directe fuzzy match met juiste Niveau1
        if self.index and hasattr(self.index, '_resolved'):
            best_score = 0
            best_combo = None
            try:
                from rapidfuzz import fuzz
                for key, combo in self.index._resolved.items():
                    if combo[1] in allowed_niveau1:
                        score = fuzz.token_set_ratio(norm_rubriek, key)
                        if score > best_score and score >= 80:
                            best_score = score
                            best_combo = combo
            except ImportError:
                for key, combo in self.index._resolved.items():
                    if combo[1] in allowed_niveau1:
                        if norm_rubriek in key or key in norm_rubriek:
                            best_combo = combo
                            break
            if best_combo:
                return best_combo

        # Strategie 3: Meest voorkomende combo per Niveau1
        combo_counts = Counter()
        if self.index and hasattr(self.index, '_resolved'):
            for combo in self.index._resolved.values():
                if combo[1] in allowed_niveau1:
                    combo_counts[combo] += 1
        if combo_counts:
            return combo_counts.most_common(1)[0][0]

        return candidates[0] if candidates else None

    def _validate_combo(self, combo: Optional[Tuple]) -> Optional[Tuple]:
        """Valideer dat een combinatie exact in het mappingbestand staat."""
        if combo is None:
            return None
        if combo in self.valid_combos:
            return combo
        return None

    def process_target(
        self,
        target_path_or_content,
        is_content: bool = False,
        filename: str = ""
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
        """
        Process a target file and enrich it with mappings.

        Alle originele kolommen blijven; CoA_code, Niveau1, Niveau2
        worden achteraan toegevoegd (of overschreven als ze al bestaan).
        Elke output-combinatie wordt gevalideerd tegen het mappingbestand.
        """
        if self.matcher is None:
            raise RuntimeError("Must load mapping file first")

        df, delimiter = read_csv_robust(target_path_or_content, is_content)
        col_map = validate_columns(df, self.REQUIRED_TARGET_COLS, "Target file")

        # Verwijder bestaande lege CoA kolommen als ze er al zijn (worden opnieuw toegevoegd)
        for col in ['CoA_code', 'Niveau1', 'Niveau2']:
            if col in df.columns:
                df = df.drop(columns=[col])

        # Nieuwe kolommen achteraan
        coa_codes = []
        niveau1s = []
        niveau2s = []

        unmatched_rows = []
        match_methods = Counter()
        rejected_combos = Counter()
        total_rows = len(df)

        self.matcher.match_stats = Counter()

        for idx, row in df.iterrows():
            rubriek = str(row[col_map['Rubriek']]).strip() if pd.notna(row[col_map['Rubriek']]) else ""

            if not rubriek:
                coa_codes.append("")
                niveau1s.append("")
                niveau2s.append("")
                unmatched_rows.append({
                    'UniekeID': idx + 1,
                    'Rubriek': rubriek,
                    'normalisatie': '',
                })
                continue

            norm_rubriek = normalize_rubriek(rubriek)
            result, method = self.matcher.match(norm_rubriek)

            # HARDE VALIDATIE: combinatie moet in mappingbestand staan
            validated = self._validate_combo(result)

            # GROOTBOEKNUMMER VALIDATIE: check tegen DWH-regels (8=Omzet, 7=Directe kosten, etc.)
            if validated and self._gb_lookup:
                rubriek_key = str(int(row['RubriekKey'])) if 'RubriekKey' in row.index and pd.notna(row.get('RubriekKey')) else None
                if not self._validate_gb_rule(rubriek_key, validated[1]):
                    rejected_combos[validated] += 1
                    # Probeer alternatief: zoek een valid combo met het juiste Niveau1
                    first_digit = self._gb_lookup.get(str(rubriek_key))
                    allowed_n1 = self.GB_RULES.get(first_digit, []) if first_digit else []
                    alt = self._find_gb_alternative(norm_rubriek, allowed_n1, rubriek_key)
                    if alt:
                        validated = alt
                        method = method + '_gb_corrected'
                    else:
                        validated = None

            if validated:
                coa_codes.append(validated[0])
                niveau1s.append(validated[1])
                niveau2s.append(validated[2])
                match_methods[method] += 1
            else:
                coa_codes.append("")
                niveau1s.append("")
                niveau2s.append("")
                if result:
                    rejected_combos[result] += 1
                unmatched_rows.append({
                    'UniekeID': idx + 1,
                    'Rubriek': rubriek,
                    'normalisatie': norm_rubriek,
                })

        # Kolommen achteraan toevoegen
        df['CoA_code'] = coa_codes
        df['Niveau1'] = niveau1s
        df['Niveau2'] = niveau2s

        # POST-PROCESSING: Direct/Indirect consistentie
        # (Direct) varianten erven Niveau1+Niveau2 van hun (Indirect) tegenhanger
        import re as _re
        indirect_ref = {}
        for _idx, _row in df.iterrows():
            _rub = str(_row.get(col_map['Rubriek'], '')).strip()
            _n1 = str(_row.get('Niveau1', '')).strip()
            _n2 = str(_row.get('Niveau2', '')).strip()
            if '(Indirect)' in _rub and _n1 and _n1 != 'nan':
                _base = _re.sub(r'^\(Indirect\)\s*', '', _rub).strip()
                indirect_ref[_base] = (_n1, _n2)

        di_synced = 0
        for _idx, _row in df.iterrows():
            _rub = str(_row.get(col_map['Rubriek'], '')).strip()
            _n1 = str(_row.get('Niveau1', '')).strip()
            _n2 = str(_row.get('Niveau2', '')).strip()
            if '(Direct)' in _rub and _n1 and _n1 != 'nan':
                _base = _re.sub(r'^\(Direct\)\s*', '', _rub).strip()
                if _base in indirect_ref:
                    ref_n1, ref_n2 = indirect_ref[_base]
                    if _n2 != ref_n2:
                        df.at[_idx, 'Niveau1'] = ref_n1
                        df.at[_idx, 'Niveau2'] = ref_n2
                        di_synced += 1

        unmatched_df = pd.DataFrame(unmatched_rows, columns=['UniekeID', 'Rubriek', 'normalisatie'])

        filled_count = total_rows - len(unmatched_rows)
        fill_rate = filled_count / total_rows if total_rows > 0 else 0

        self.run_stats = {
            'total_rows': total_rows,
            'filled_rows': filled_count,
            'unmatched_rows': len(unmatched_rows),
            'fill_rate': fill_rate,
            'fill_rate_pct': f"{fill_rate * 100:.1f}%",
            'match_methods': dict(match_methods),
            'meets_threshold': fill_rate >= self.min_fill_rate,
            'rejected_combos': dict(rejected_combos),
            'top_unmatched_first_words': self._get_top_unmatched_first_words(unmatched_df),
            'direct_indirect_synced': di_synced,
        }

        return df, unmatched_df, self.run_stats

    def get_gb_exceptions(self, enriched_df: pd.DataFrame) -> List[Dict[str, str]]:
        """
        Geeft items terug waarvan het grootboeknummer NIET onder de harde regels valt
        (niet 4/7/8). Deze moeten handmatig gereviewed worden door de gebruiker.

        Returns:
            Lijst van dicts met gb_code, rubriek, niveau1, niveau2 per uitzondering.
        """
        if not hasattr(self, '_gb_full_code') or not self._gb_full_code:
            return []

        exceptions = []
        seen = set()
        for _, row in enriched_df.iterrows():
            rkey = str(int(row['RubriekKey'])) if pd.notna(row.get('RubriekKey')) else None
            if not rkey:
                continue
            gb = self._gb_full_code.get(rkey, '')
            if not gb:
                continue
            first = gb[0]
            if first not in self.GB_RULES:
                rubriek = str(row.get('Rubriek', '')).strip()
                n1 = str(row.get('Niveau1', '')).strip()
                n2 = str(row.get('Niveau2', '')).strip()
                # Deduplicate op rubrieknaam
                if rubriek not in seen:
                    seen.add(rubriek)
                    exceptions.append({
                        'gb_code': gb,
                        'rubriek': rubriek,
                        'niveau1': n1,
                        'niveau2': n2,
                    })
        return exceptions

    def _get_top_unmatched_first_words(self, unmatched_df: pd.DataFrame, top_n: int = 10) -> List[Tuple[str, int]]:
        """Get top N most frequent first words in unmatched terms."""
        if unmatched_df.empty:
            return []
        first_words = []
        for norm in unmatched_df['normalisatie']:
            if norm:
                tokens = str(norm).split()
                if tokens:
                    first_words.append(tokens[0])
        return Counter(first_words).most_common(top_n)

    def save_results(
        self,
        enriched_df: pd.DataFrame,
        unmatched_df: pd.DataFrame,
        output_dir: str,
        base_filename: str
    ) -> Tuple[str, Optional[str]]:
        """Save enriched and unmatched files (;-delimited, UTF-8 BOM, CRLF)."""
        os.makedirs(output_dir, exist_ok=True)

        base = extract_base_name(base_filename)
        enriched_filename = get_output_filename(base)
        enriched_path = os.path.join(output_dir, enriched_filename)

        # Geen hulpkolommen in output
        write_csv_output(enriched_df, enriched_path)

        unmatched_path = None
        if not unmatched_df.empty:
            unmatched_filename = get_output_filename(base, '_unmatched')
            unmatched_path = os.path.join(output_dir, unmatched_filename)
            write_csv_output(unmatched_df, unmatched_path)

        return enriched_path, unmatched_path

    def generate_report(self) -> str:
        """Generate a text report of the mapping run."""
        lines = [
            "=" * 60,
            "WV/BALANS MAPPING REPORT",
            "=" * 60,
            "",
            "MAPPING FILE STATISTICS:",
            f"  Total rows: {self.mapping_stats.get('total_rows', 'N/A')}",
            f"  Valid rows used: {self.mapping_stats.get('valid_rows', 'N/A')}",
            f"  Skipped rows: {self.mapping_stats.get('skipped_rows', 'N/A')}",
            f"  Unique keys: {self.mapping_stats.get('unique_keys', 'N/A')}",
            f"  Valid combinations: {self.mapping_stats.get('valid_combos', 'N/A')}",
            "",
            "TARGET FILE RESULTS:",
            f"  Total rows: {self.run_stats.get('total_rows', 'N/A')}",
            f"  Filled rows: {self.run_stats.get('filled_rows', 'N/A')}",
            f"  Unmatched rows: {self.run_stats.get('unmatched_rows', 'N/A')}",
            f"  Fill rate: {self.run_stats.get('fill_rate_pct', 'N/A')}",
            f"  Meets threshold (90%): {'YES' if self.run_stats.get('meets_threshold') else 'NO'}",
            "",
            "MATCH METHODS BREAKDOWN:",
        ]

        for method, count in sorted(self.run_stats.get('match_methods', {}).items()):
            lines.append(f"  {method}: {count}")

        if self.run_stats.get('rejected_combos'):
            lines.extend([
                "",
                "REJECTED COMBINATIONS (niet in mappingbestand):",
            ])
            for combo, count in sorted(self.run_stats['rejected_combos'].items()):
                lines.append(f"  {combo}: {count}x")

        if self.run_stats.get('top_unmatched_first_words'):
            lines.extend([
                "",
                "TOP 10 UNMATCHED FIRST WORDS:",
            ])
            for word, count in self.run_stats['top_unmatched_first_words']:
                lines.append(f"  {word}: {count}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)
