"""
WV (Winst & Verlies) and Balans Mapping Module - Part 2 Implementation
"""
import os
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
    """

    REQUIRED_MAPPING_COLS = ['Rubriek', 'CoA_code', 'Niveau1', 'Niveau2']
    REQUIRED_TARGET_COLS = ['Rubriek']

    def __init__(self, min_fill_rate: float = 0.90):
        self.min_fill_rate = min_fill_rate
        self.index: Optional[MappingIndex] = None
        self.matcher: Optional[WVBalansMatcher] = None
        self.mapping_stats = {}
        self.run_stats = {}

    def load_mapping(self, mapping_path_or_content, is_content: bool = False, filename: str = "") -> Dict[str, Any]:
        """
        Load and index the mapping file.

        Args:
            mapping_path_or_content: File path or content bytes
            is_content: If True, first arg is content bytes
            filename: Filename (used when is_content=True)

        Returns:
            Dictionary with loading statistics
        """
        # Read CSV
        df, delimiter = read_csv_robust(mapping_path_or_content, is_content)

        # Validate required columns (case-insensitive)
        col_map = validate_columns(df, self.REQUIRED_MAPPING_COLS, "Mapping file")

        # Build index
        self.index = MappingIndex()

        valid_rows = 0
        skipped_rows = 0

        for idx, row in df.iterrows():
            rubriek = str(row[col_map['Rubriek']]).strip() if pd.notna(row[col_map['Rubriek']]) else ""
            code = row[col_map['CoA_code']]
            niveau1 = str(row[col_map['Niveau1']]).strip() if pd.notna(row[col_map['Niveau1']]) else ""
            niveau2 = str(row[col_map['Niveau2']]).strip() if pd.notna(row[col_map['Niveau2']]) else ""

            # Skip if missing required values
            if not rubriek:
                skipped_rows += 1
                continue

            # Clean code
            code = clean_coa_code(code)
            if not code or not niveau1 or not niveau2:
                skipped_rows += 1
                continue

            # Normalize rubriek
            norm_rubriek = normalize_rubriek(rubriek)
            if not norm_rubriek:
                skipped_rows += 1
                continue

            # Add to index
            combination = (code, niveau1, niveau2)
            self.index.add(norm_rubriek, combination)
            valid_rows += 1

        # Resolve best combinations
        self.index.resolve()

        # Create matcher
        self.matcher = WVBalansMatcher(self.index)

        self.mapping_stats = {
            'total_rows': len(df),
            'valid_rows': valid_rows,
            'skipped_rows': skipped_rows,
            'unique_keys': len(self.index._resolved),
        }

        return self.mapping_stats

    def process_target(
        self,
        target_path_or_content,
        is_content: bool = False,
        filename: str = ""
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
        """
        Process a target file and enrich it with mappings.

        Args:
            target_path_or_content: File path or content bytes
            is_content: If True, first arg is content bytes
            filename: Filename (used when is_content=True)

        Returns:
            Tuple of (enriched_df, unmatched_df, statistics)
        """
        if self.matcher is None:
            raise RuntimeError("Must load mapping file first")

        # Read target CSV
        df, delimiter = read_csv_robust(target_path_or_content, is_content)
        self._target_delimiter = delimiter  # Bewaar voor output

        # Validate required columns
        col_map = validate_columns(df, self.REQUIRED_TARGET_COLS, "Target file")

        # Initialize result columns (ensure they don't exist or overwrite)
        df['CoA_code'] = ""
        df['Niveau1'] = ""
        df['Niveau2'] = ""

        # Track unmatched rows
        unmatched_rows = []
        match_methods = Counter()
        total_rows = len(df)
        fuzzy_near_misses = []

        # Reset matcher stats
        self.matcher.match_stats = Counter()

        # Process each row
        for idx, row in df.iterrows():
            rubriek = str(row[col_map['Rubriek']]).strip() if pd.notna(row[col_map['Rubriek']]) else ""

            if not rubriek:
                unmatched_rows.append({
                    'UniekeID': idx + 1,
                    'Rubriek': rubriek,
                    'normalisatie': '',
                })
                continue

            # Normalize
            norm_rubriek = normalize_rubriek(rubriek)

            # Match
            result, method = self.matcher.match(norm_rubriek)
            match_methods[method] += 1

            if result:
                df.at[idx, 'CoA_code'] = result[0]
                df.at[idx, 'Niveau1'] = result[1]
                df.at[idx, 'Niveau2'] = result[2]
            else:
                unmatched_rows.append({
                    'UniekeID': idx + 1,
                    'Rubriek': rubriek,
                    'normalisatie': norm_rubriek,
                })

                # Find near misses for reporting
                near_miss = self._find_near_miss(norm_rubriek)
                if near_miss:
                    fuzzy_near_misses.append((norm_rubriek, near_miss[0], near_miss[1]))

        # Create unmatched DataFrame
        unmatched_df = pd.DataFrame(unmatched_rows, columns=['UniekeID', 'Rubriek', 'normalisatie'])

        # Calculate fill rate
        filled_count = total_rows - len(unmatched_rows)
        fill_rate = filled_count / total_rows if total_rows > 0 else 0

        # Verify all combinations exist in mapping
        output_combos = set()
        for idx, row in df.iterrows():
            code = row['CoA_code']
            n1 = row['Niveau1']
            n2 = row['Niveau2']
            if code and n1 and n2:
                output_combos.add((code, n1, n2))

        valid_combos = set(self.index.global_freq.keys())
        # Also add fixed anchors as valid
        valid_combos.add(('101001', 'Omzet', 'Omzet'))
        valid_combos.add(('109001', 'Afschrijving', 'Afschrijving'))

        invalid_combos = output_combos - valid_combos

        self.run_stats = {
            'total_rows': total_rows,
            'filled_rows': filled_count,
            'unmatched_rows': len(unmatched_rows),
            'fill_rate': fill_rate,
            'fill_rate_pct': f"{fill_rate * 100:.1f}%",
            'match_methods': dict(match_methods),
            'meets_threshold': fill_rate >= self.min_fill_rate,
            'invalid_combinations': list(invalid_combos),
            'top_unmatched_first_words': self._get_top_unmatched_first_words(unmatched_df),
            'fuzzy_near_misses': fuzzy_near_misses[:10],
        }

        return df, unmatched_df, self.run_stats

    def _find_near_miss(self, norm_key: str) -> Optional[Tuple[str, float]]:
        """Find closest match that scored 85-89%."""
        from .matching import token_set_ratio

        candidates = self.index.get_candidates(norm_key)
        best_score = 0
        best_key = None

        for candidate in candidates:
            score = token_set_ratio(norm_key, candidate)
            if 85 <= score < 90 and score > best_score:
                best_score = score
                best_key = candidate

        if best_key:
            return (best_key, best_score)
        return None

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

        counts = Counter(first_words).most_common(top_n)
        return counts

    def save_results(
        self,
        enriched_df: pd.DataFrame,
        unmatched_df: pd.DataFrame,
        output_dir: str,
        base_filename: str
    ) -> Tuple[str, str]:
        """
        Save enriched and unmatched files.

        Args:
            enriched_df: Enriched DataFrame
            unmatched_df: Unmatched rows DataFrame
            output_dir: Output directory path
            base_filename: Base filename for output

        Returns:
            Tuple of (enriched_path, unmatched_path)
        """
        os.makedirs(output_dir, exist_ok=True)

        base = extract_base_name(base_filename)

        enriched_filename = get_output_filename(base)
        unmatched_filename = get_output_filename(base, '_unmatched')

        enriched_path = os.path.join(output_dir, enriched_filename)
        unmatched_path = os.path.join(output_dir, unmatched_filename)

        delimiter = getattr(self, '_target_delimiter', ',')
        write_csv_output(enriched_df, enriched_path, delimiter)

        if not unmatched_df.empty:
            write_csv_output(unmatched_df, unmatched_path, delimiter)
        else:
            unmatched_path = None

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

        if self.run_stats.get('invalid_combinations'):
            lines.extend([
                "",
                "WARNING - INVALID COMBINATIONS FOUND:",
            ])
            for combo in self.run_stats['invalid_combinations']:
                lines.append(f"  {combo}")

        if self.run_stats.get('top_unmatched_first_words'):
            lines.extend([
                "",
                "TOP 10 UNMATCHED FIRST WORDS:",
            ])
            for word, count in self.run_stats['top_unmatched_first_words']:
                lines.append(f"  {word}: {count}")

        if self.run_stats.get('fuzzy_near_misses'):
            lines.extend([
                "",
                "FUZZY NEAR MISSES (85-89% score):",
            ])
            for source, target, score in self.run_stats['fuzzy_near_misses']:
                lines.append(f"  '{source}' -> '{target}' ({score:.1f}%)")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


def run_must_pass_tests(mapper: WVBalansMapper) -> List[Dict[str, Any]]:
    """
    Run must-pass smoke tests for WV/Balans mapping.

    Returns:
        List of test results with status and details
    """
    results = []

    # Test cases: (input_rubriek, expected_niveau1, expected_niveau2, expected_code_if_fixed)
    test_cases = [
        # Omzet tests
        ('omzet', 'Omzet', 'Omzet', '101001'),
        ('omzet dagorders', 'Omzet', 'Omzet', '101001'),

        # Afschrijving tests
        ('afschrijving', 'Afschrijving', 'Afschrijving', '109001'),
        ('afschr.', 'Afschrijving', 'Afschrijving', '109001'),
        ('afschrijvingen', 'Afschrijving', 'Afschrijving', '109001'),

        # SVW/WIA/WGA tests - Niveau-namen moeten overeenkomen met werkelijke data
        ('svw premies', 'Personeelkosten', 'Sociale lasten', None),
        ('wia', 'Personeelkosten', 'Sociale lasten', None),
        ('wga', 'Personeelkosten', 'Sociale lasten', None),
        ('sociaal fonds', 'Personeelkosten', 'Sociale lasten', None),

        # WKR tests
        ('wkr bonus', 'Personeelkosten', 'Personeelskosten Overig', None),
        ('wkr vitaliteitsbudget', 'Personeelkosten', 'Personeelskosten Overig', None),

        # Prefab
        ('prefabkosten', 'Directe kosten', 'Materiaal', None),

        # Projectwaardering
        ('gefactureerde termijnen', 'Omzet', 'Projectwaardering /-resultaat', None),
        ('waarderingsresultaat', 'Omzet', 'Projectwaardering /-resultaat', None),
    ]

    for rubriek, expected_n1, expected_n2, expected_code in test_cases:
        norm = normalize_rubriek(rubriek)
        result, method = mapper.matcher.match(norm)

        test_result = {
            'input': rubriek,
            'normalized': norm,
            'expected': (expected_code, expected_n1, expected_n2) if expected_code else (None, expected_n1, expected_n2),
            'actual': result,
            'method': method,
            'passed': False,
            'reason': '',
        }

        if result:
            code, n1, n2 = result
            n1_match = n1.lower() == expected_n1.lower() if n1 and expected_n1 else False
            n2_match = n2.lower() == expected_n2.lower() if n2 and expected_n2 else False

            if expected_code:
                code_match = code == expected_code
                test_result['passed'] = code_match and n1_match and n2_match
                if not test_result['passed']:
                    test_result['reason'] = f"Expected code={expected_code}, got={code}" if not code_match else f"Niveau mismatch"
            else:
                test_result['passed'] = n1_match and n2_match
                if not test_result['passed']:
                    test_result['reason'] = f"Niveau mismatch: expected ({expected_n1}, {expected_n2}), got ({n1}, {n2})"
        else:
            test_result['reason'] = "No match found"

        results.append(test_result)

    return results
