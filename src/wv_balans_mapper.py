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

    def __init__(self, min_fill_rate: float = 0.90):
        self.min_fill_rate = min_fill_rate
        self.index: Optional[MappingIndex] = None
        self.matcher: Optional[WVBalansMatcher] = None
        self.valid_combos: Set[Tuple[str, str, str]] = set()
        self.mapping_stats = {}
        self.run_stats = {}

    def load_mapping(self, mapping_path_or_content, is_content: bool = False, filename: str = "") -> Dict[str, Any]:
        """Load and index the mapping file. Bouwt ook de set van geldige combinaties."""
        df, delimiter = read_csv_robust(mapping_path_or_content, is_content)
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

        self.mapping_stats = {
            'total_rows': len(df),
            'valid_rows': valid_rows,
            'skipped_rows': skipped_rows,
            'unique_keys': len(self.index._resolved),
            'valid_combos': len(self.valid_combos),
        }

        return self.mapping_stats

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
        }

        return df, unmatched_df, self.run_stats

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
