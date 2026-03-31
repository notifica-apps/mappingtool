"""
Mapping Quality Analysis Module

Detecteert inconsistenties, duplicaten en afwijkingen in mapping bestanden.
Kerncapabiliteit: herkennen wanneer vergelijkbare rubrieken verschillende
classificaties hebben (bijv. 3340-3349 bijna allemaal "Omzet" maar 3341
plotseling "Directe kosten").
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from .normalization import normalize_rubriek, normalize_taken


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class InconsistentGroup:
    """Een groep rubrieken waar de meerderheid één mapping heeft, maar outliers afwijken."""
    group_key: str                  # bijv. "334x" of "inkoop overig service"
    group_description: str          # Leesbare omschrijving
    majority_mapping: Tuple         # (Niveau1, Niveau2) van de meerderheid
    majority_count: int             # Aantal rubrieken met de meerderheids-mapping
    outliers: List[Dict[str, Any]]  # Afwijkende rubrieken met hun mapping
    total_in_group: int

    @property
    def consistency_pct(self) -> float:
        return (self.majority_count / self.total_in_group * 100) if self.total_in_group else 0


@dataclass
class DuplicateEntry:
    """Genormaliseerde key die naar meerdere (N1, N2) combinaties wijst."""
    normalized_key: str
    original_rubrieken: List[str]
    mappings: Dict[Tuple, int]  # (N1, N2) → aantal keer


@dataclass
class QualityReport:
    """Volledig kwaliteitsrapport voor een mapping bestand."""
    mapping_type: str  # 'WV', 'Balans', of 'Taken'
    total_rows: int = 0
    unique_rubrieken: int = 0
    unique_combos: int = 0

    # Problemen
    inconsistent_code_ranges: List[InconsistentGroup] = field(default_factory=list)
    inconsistent_name_groups: List[InconsistentGroup] = field(default_factory=list)
    duplicates: List[DuplicateEntry] = field(default_factory=list)

    # Semantische checks
    semantic_issues: List[Dict[str, Any]] = field(default_factory=list)

    # Statistieken
    combo_distribution: Dict[str, int] = field(default_factory=dict)
    niveau1_distribution: Dict[str, int] = field(default_factory=dict)

    @property
    def total_issues(self) -> int:
        return (len(self.inconsistent_code_ranges) +
                len(self.inconsistent_name_groups) +
                len(self.duplicates) +
                len(self.semantic_issues))

    @property
    def has_issues(self) -> bool:
        return self.total_issues > 0


# =============================================================================
# SEMANTISCHE REGELS
# =============================================================================

# Woorden in rubrieknamen die een sterke hint geven over de juiste Niveau1
# Als een rubriek dit woord bevat maar een ANDERE Niveau1 heeft → waarschuwing
SEMANTIC_HINTS_WV = {
    'inkoop': {
        'expected_niveau1': {'Directe kosten'},
        'description': 'Inkoop-rubrieken horen bij "Directe kosten"',
    },
    'omzet': {
        'expected_niveau1': {'Omzet'},
        'description': 'Omzet-rubrieken horen bij "Omzet"',
    },
    'salaris': {
        'expected_niveau1': {'Personeelkosten', 'Personeelskosten'},
        'description': 'Salaris-rubrieken horen bij "Personeelkosten"',
    },
    'pensioen': {
        'expected_niveau1': {'Personeelkosten', 'Personeelskosten'},
        'description': 'Pensioen-rubrieken horen bij "Personeelkosten"',
    },
    'afschrijving': {
        'expected_niveau1': {'Afschrijving', 'Afschrijvingen'},
        'description': 'Afschrijving-rubrieken horen bij "Afschrijving"',
    },
    'verzekering': {
        'expected_niveau1': {'Overige bedrijfskosten', 'Personeelkosten', 'Personeelskosten'},
        'description': 'Verzekering-rubrieken horen bij "Overige bedrijfskosten" of "Personeelkosten"',
    },
    'huur': {
        'expected_niveau1': {'Overige bedrijfskosten'},
        'description': 'Huur-rubrieken horen bij "Overige bedrijfskosten"',
    },
    'rente': {
        'expected_niveau1': {'Financiele Baten en Lasten'},
        'description': 'Rente-rubrieken horen bij "Financiele Baten en Lasten"',
    },
    'interest': {
        'expected_niveau1': {'Financiele Baten en Lasten'},
        'description': 'Interest-rubrieken horen bij "Financiele Baten en Lasten"',
    },
}

SEMANTIC_HINTS_BALANS = {
    'bank': {
        'expected_niveau1': {'Vlottende Activa'},
        'description': 'Bank-rubrieken horen bij "Vlottende Activa"',
    },
    'btw': {
        'expected_niveau1': {'Kortlopende schulden'},
        'description': 'BTW-rubrieken horen bij "Kortlopende schulden"',
    },
    'voorziening': {
        'expected_niveau1': {'Voorzieningen'},
        'description': 'Voorziening-rubrieken horen bij "Voorzieningen"',
    },
    'kapitaal': {
        'expected_niveau1': {'Eigen vermogen'},
        'description': 'Kapitaal-rubrieken horen bij "Eigen vermogen"',
    },
}


# =============================================================================
# ANALYSE FUNCTIES
# =============================================================================

def _extract_code_prefix(rubriek: str, prefix_len: int = 3) -> Optional[str]:
    """Extract numeriek prefix uit rubrieknaam (bijv. '3340 - Inkoop...' → '334')."""
    match = re.match(r'^(\d+)', str(rubriek).strip())
    if match:
        code = match.group(1)
        if len(code) >= prefix_len:
            return code[:prefix_len]
    return None


def _extract_name_prefix(rubriek: str, n_tokens: int = 2) -> Optional[str]:
    """Extract eerste N tokens van rubrieknaam na het nummer."""
    text = re.sub(r'^\d+[\s\-]*', '', str(rubriek).strip()).strip()
    tokens = text.lower().split()
    if len(tokens) >= n_tokens:
        return ' '.join(tokens[:n_tokens])
    return None


def analyze_code_range_consistency(
    df: pd.DataFrame,
    rubriek_col: str,
    niveau1_col: str,
    niveau2_col: str,
    min_group_size: int = 3,
) -> List[InconsistentGroup]:
    """
    Analyseer consistentie binnen code-reeksen (bijv. 334x, 335x).

    Groepeert rubrieken per numeriek prefix en detecteert uitschieters
    waar de mapping afwijkt van de meerderheid.
    """
    # Groepeer per code prefix
    groups: Dict[str, List[Dict]] = defaultdict(list)

    for _, row in df.iterrows():
        prefix = _extract_code_prefix(str(row[rubriek_col]))
        if prefix:
            groups[prefix].append({
                'rubriek': str(row[rubriek_col]),
                'niveau1': str(row[niveau1_col]) if pd.notna(row[niveau1_col]) else '',
                'niveau2': str(row[niveau2_col]) if pd.notna(row[niveau2_col]) else '',
            })

    inconsistencies = []

    for prefix, items in sorted(groups.items()):
        if len(items) < min_group_size:
            continue

        # Tel (N1, N2) combinaties
        combo_counts = Counter()
        for item in items:
            combo_counts[(item['niveau1'], item['niveau2'])] += 1

        # Vind meerderheid
        most_common = combo_counts.most_common(1)[0]
        majority_combo, majority_count = most_common

        # Als niet 100% consistent → er zijn outliers
        if majority_count < len(items):
            outliers = []
            for item in items:
                item_combo = (item['niveau1'], item['niveau2'])
                if item_combo != majority_combo:
                    outliers.append({
                        'rubriek': item['rubriek'],
                        'huidige_niveau1': item['niveau1'],
                        'huidige_niveau2': item['niveau2'],
                        'verwacht_niveau1': majority_combo[0],
                        'verwacht_niveau2': majority_combo[1],
                    })

            inconsistencies.append(InconsistentGroup(
                group_key=f"{prefix}x",
                group_description=f"Code-reeks {prefix}0-{prefix}9",
                majority_mapping=majority_combo,
                majority_count=majority_count,
                outliers=outliers,
                total_in_group=len(items),
            ))

    return inconsistencies


def analyze_name_group_consistency(
    df: pd.DataFrame,
    rubriek_col: str,
    niveau1_col: str,
    niveau2_col: str,
    min_group_size: int = 3,
) -> List[InconsistentGroup]:
    """
    Analyseer consistentie op basis van naam-overeenkomst.

    Groepeert rubrieken met dezelfde eerste 2 woorden en detecteert
    afwijkende mappings.
    """
    groups: Dict[str, List[Dict]] = defaultdict(list)

    for _, row in df.iterrows():
        prefix = _extract_name_prefix(str(row[rubriek_col]))
        if prefix:
            groups[prefix].append({
                'rubriek': str(row[rubriek_col]),
                'niveau1': str(row[niveau1_col]) if pd.notna(row[niveau1_col]) else '',
                'niveau2': str(row[niveau2_col]) if pd.notna(row[niveau2_col]) else '',
            })

    inconsistencies = []

    for prefix, items in sorted(groups.items()):
        if len(items) < min_group_size:
            continue

        combo_counts = Counter()
        for item in items:
            combo_counts[(item['niveau1'], item['niveau2'])] += 1

        most_common = combo_counts.most_common(1)[0]
        majority_combo, majority_count = most_common

        if majority_count < len(items):
            outliers = []
            for item in items:
                item_combo = (item['niveau1'], item['niveau2'])
                if item_combo != majority_combo:
                    outliers.append({
                        'rubriek': item['rubriek'],
                        'huidige_niveau1': item['niveau1'],
                        'huidige_niveau2': item['niveau2'],
                        'verwacht_niveau1': majority_combo[0],
                        'verwacht_niveau2': majority_combo[1],
                    })

            inconsistencies.append(InconsistentGroup(
                group_key=prefix,
                group_description=f'Rubrieken met prefix "{prefix}"',
                majority_mapping=majority_combo,
                majority_count=majority_count,
                outliers=outliers,
                total_in_group=len(items),
            ))

    return inconsistencies


def analyze_duplicates(
    df: pd.DataFrame,
    rubriek_col: str,
    niveau1_col: str,
    niveau2_col: str,
    mapping_type: str,
) -> List[DuplicateEntry]:
    """
    Vind rubrieken die na normalisatie dezelfde key opleveren
    maar naar verschillende (N1, N2) combinaties wijzen.
    """
    normalize_fn = normalize_rubriek if mapping_type != 'Taken' else normalize_taken

    # Groepeer per genormaliseerde key
    key_groups: Dict[str, Dict] = defaultdict(lambda: {
        'originals': [],
        'mappings': Counter(),
    })

    for _, row in df.iterrows():
        rubriek = str(row[rubriek_col]).strip()
        if not rubriek:
            continue

        norm_key = normalize_fn(rubriek)
        if not norm_key:
            continue

        n1 = str(row[niveau1_col]) if pd.notna(row[niveau1_col]) else ''
        n2 = str(row[niveau2_col]) if pd.notna(row[niveau2_col]) else ''

        key_groups[norm_key]['originals'].append(rubriek)
        key_groups[norm_key]['mappings'][(n1, n2)] += 1

    duplicates = []
    for norm_key, data in key_groups.items():
        if len(data['mappings']) > 1:
            duplicates.append(DuplicateEntry(
                normalized_key=norm_key,
                original_rubrieken=list(set(data['originals'])),
                mappings=dict(data['mappings']),
            ))

    # Sorteer op aantal conflicterende mappings (meeste eerst)
    duplicates.sort(key=lambda d: -len(d.mappings))
    return duplicates


def analyze_semantic_consistency(
    df: pd.DataFrame,
    rubriek_col: str,
    niveau1_col: str,
    mapping_type: str,
) -> List[Dict[str, Any]]:
    """
    Controleer of rubrieken semantisch bij hun Niveau1 passen.

    Bijv. "Inkoop overig service Brand" zou bij "Directe kosten" moeten horen,
    niet bij "Omzet".
    """
    hints = SEMANTIC_HINTS_WV if mapping_type == 'WV' else SEMANTIC_HINTS_BALANS
    issues = []

    for _, row in df.iterrows():
        rubriek = str(row[rubriek_col]).strip()
        niveau1 = str(row[niveau1_col]).strip() if pd.notna(row[niveau1_col]) else ''

        if not rubriek or not niveau1:
            continue

        rubriek_lower = rubriek.lower()

        for keyword, rule in hints.items():
            # Check of het keyword in de rubrieknaam voorkomt
            if re.search(r'\b' + re.escape(keyword) + r'\b', rubriek_lower):
                # Check of de huidige Niveau1 in de verwachte set zit
                expected = rule['expected_niveau1']
                # Case-insensitive vergelijking
                niveau1_matches = any(
                    niveau1.lower().strip() == exp.lower().strip()
                    for exp in expected
                )
                if not niveau1_matches:
                    issues.append({
                        'rubriek': rubriek,
                        'huidige_niveau1': niveau1,
                        'verwacht_niveau1': ', '.join(sorted(expected)),
                        'reden': rule['description'],
                        'keyword': keyword,
                    })
                break  # Eerste match is voldoende per rubriek

    return issues


# =============================================================================
# HOOFDFUNCTIE
# =============================================================================

def analyze_mapping_quality(
    df: pd.DataFrame,
    mapping_type: str,
    rubriek_col: str = 'Rubriek',
    niveau1_col: str = 'Niveau1',
    niveau2_col: str = 'Niveau2',
    min_group_size: int = 3,
) -> QualityReport:
    """
    Voer volledige kwaliteitsanalyse uit op een mapping DataFrame.

    Args:
        df: DataFrame met mapping data
        mapping_type: 'WV', 'Balans', of 'Taken'
        rubriek_col: Kolom met rubrieknamen
        niveau1_col: Kolom met Niveau1 classificatie
        niveau2_col: Kolom met Niveau2 classificatie
        min_group_size: Minimale groepsgrootte voor consistentie-analyse

    Returns:
        QualityReport met alle bevindingen
    """
    report = QualityReport(mapping_type=mapping_type)

    # Filter lege rijen
    mask = df[rubriek_col].notna() & (df[rubriek_col].astype(str).str.strip() != '')
    if niveau1_col in df.columns:
        mask = mask & df[niveau1_col].notna() & (df[niveau1_col].astype(str).str.strip() != '')
    working_df = df[mask].copy()

    report.total_rows = len(working_df)
    report.unique_rubrieken = working_df[rubriek_col].nunique()

    if niveau1_col in working_df.columns and niveau2_col in working_df.columns:
        # Unieke combinaties
        combos = working_df[[niveau1_col, niveau2_col]].drop_duplicates()
        report.unique_combos = len(combos)

        # Distributies
        report.niveau1_distribution = dict(
            working_df[niveau1_col].value_counts().head(20)
        )
        report.combo_distribution = dict(
            working_df.apply(
                lambda r: f"{r[niveau1_col]} / {r[niveau2_col]}", axis=1
            ).value_counts().head(30)
        )

        # 1. Code-reeks consistentie
        report.inconsistent_code_ranges = analyze_code_range_consistency(
            working_df, rubriek_col, niveau1_col, niveau2_col, min_group_size
        )

        # 2. Naam-groep consistentie
        report.inconsistent_name_groups = analyze_name_group_consistency(
            working_df, rubriek_col, niveau1_col, niveau2_col, min_group_size
        )

        # 3. Duplicaten
        report.duplicates = analyze_duplicates(
            working_df, rubriek_col, niveau1_col, niveau2_col, mapping_type
        )

        # 4. Semantische checks
        report.semantic_issues = analyze_semantic_consistency(
            working_df, rubriek_col, niveau1_col, mapping_type
        )

    return report


def format_quality_report(report: QualityReport) -> str:
    """Genereer leesbaar tekstrapport."""
    lines = [
        "=" * 70,
        f"KWALITEITSRAPPORT - {report.mapping_type} MAPPING",
        "=" * 70,
        "",
        f"Totaal rijen: {report.total_rows}",
        f"Unieke rubrieken: {report.unique_rubrieken}",
        f"Unieke (Niveau1, Niveau2) combinaties: {report.unique_combos}",
        f"Totaal gevonden issues: {report.total_issues}",
        "",
    ]

    # Semantische issues
    if report.semantic_issues:
        lines.append("-" * 70)
        lines.append(f"SEMANTISCHE AFWIJKINGEN ({len(report.semantic_issues)} gevonden)")
        lines.append("-" * 70)
        for issue in report.semantic_issues:
            lines.append(f"  [{issue['keyword'].upper()}] {issue['rubriek']}")
            lines.append(f"    Huidige Niveau1:  {issue['huidige_niveau1']}")
            lines.append(f"    Verwacht:         {issue['verwacht_niveau1']}")
            lines.append(f"    Reden:            {issue['reden']}")
            lines.append("")

    # Code-reeks inconsistenties
    if report.inconsistent_code_ranges:
        lines.append("-" * 70)
        lines.append(f"INCONSISTENTE CODE-REEKSEN ({len(report.inconsistent_code_ranges)} groepen)")
        lines.append("-" * 70)
        for group in report.inconsistent_code_ranges:
            lines.append(f"  Reeks {group.group_key} ({group.total_in_group} rubrieken, "
                         f"{group.consistency_pct:.0f}% consistent)")
            lines.append(f"    Meerderheid: {group.majority_mapping[0]} / {group.majority_mapping[1]} "
                         f"({group.majority_count}x)")
            for outlier in group.outliers:
                lines.append(f"    AFWIJKEND: {outlier['rubriek']}")
                lines.append(f"      Nu:      {outlier['huidige_niveau1']} / {outlier['huidige_niveau2']}")
                lines.append(f"      Verwacht: {outlier['verwacht_niveau1']} / {outlier['verwacht_niveau2']}")
            lines.append("")

    # Naam-groep inconsistenties
    if report.inconsistent_name_groups:
        lines.append("-" * 70)
        lines.append(f"INCONSISTENTE NAAM-GROEPEN ({len(report.inconsistent_name_groups)} groepen)")
        lines.append("-" * 70)
        for group in report.inconsistent_name_groups:
            lines.append(f"  {group.group_description} ({group.total_in_group} rubrieken, "
                         f"{group.consistency_pct:.0f}% consistent)")
            lines.append(f"    Meerderheid: {group.majority_mapping[0]} / {group.majority_mapping[1]} "
                         f"({group.majority_count}x)")
            for outlier in group.outliers:
                lines.append(f"    AFWIJKEND: {outlier['rubriek']}")
                lines.append(f"      Nu:      {outlier['huidige_niveau1']} / {outlier['huidige_niveau2']}")
            lines.append("")

    # Duplicaten
    if report.duplicates:
        lines.append("-" * 70)
        lines.append(f"DUPLICATEN ({len(report.duplicates)} genormaliseerde keys met conflicten)")
        lines.append("-" * 70)
        for dup in report.duplicates[:20]:  # Max 20
            lines.append(f"  Key: '{dup.normalized_key}'")
            lines.append(f"    Originelen: {', '.join(dup.original_rubrieken[:5])}")
            for combo, count in sorted(dup.mappings.items(), key=lambda x: -x[1]):
                lines.append(f"    → {combo[0]} / {combo[1]}: {count}x")
            lines.append("")

    # Distributies
    if report.niveau1_distribution:
        lines.append("-" * 70)
        lines.append("NIVEAU1 DISTRIBUTIE")
        lines.append("-" * 70)
        for n1, count in sorted(report.niveau1_distribution.items(), key=lambda x: -x[1]):
            lines.append(f"  {n1}: {count}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)
