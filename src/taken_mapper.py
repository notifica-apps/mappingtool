"""
Taken (Task) Mapping Module - Part 1 Implementation
"""
import os
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pytz

from .normalization import normalize_taken, clean_taakgroepcode
from .matching import MappingIndex, TakenMatcher
from .utils import (
    read_csv_robust,
    validate_columns,
    write_csv_output,
    get_output_filename,
    extract_base_name,
)


class TakenMapper:
    """
    Mapper for Taken (tasks) that enriches target files with Taakgroepcode and Taakgroep.
    """

    REQUIRED_MAPPING_COLS = ['Taak', 'Taakgroepcode', 'Taakgroep']
    REQUIRED_TARGET_COLS = ['Taak', 'Type']
    OPTIONAL_COLS = ['Klantnummer']

    def __init__(self, min_fill_rate: float = 0.90):
        self.min_fill_rate = min_fill_rate
        self.index: Optional[MappingIndex] = None
        self.matcher: Optional[TakenMatcher] = None
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

        # Validate required columns
        col_map = validate_columns(df, self.REQUIRED_MAPPING_COLS, "Mapping file")

        # Check optional columns
        has_type = 'Type' in df.columns
        has_client = 'Klantnummer' in df.columns

        # Build index
        self.index = MappingIndex()

        valid_rows = 0
        skipped_rows = 0

        for idx, row in df.iterrows():
            taak = str(row[col_map['Taak']]).strip() if pd.notna(row[col_map['Taak']]) else ""
            code = row[col_map['Taakgroepcode']]
            groep = str(row[col_map['Taakgroep']]).strip() if pd.notna(row[col_map['Taakgroep']]) else ""

            # Skip if missing required values
            if not taak or pd.isna(code) or not groep:
                skipped_rows += 1
                continue

            # Clean code
            code = clean_taakgroepcode(code)
            if not code:
                skipped_rows += 1
                continue

            # Get optional values
            taak_type = str(row['Type']).strip() if has_type and pd.notna(row.get('Type')) else None
            client_id = str(row['Klantnummer']).strip() if has_client and pd.notna(row.get('Klantnummer')) else None

            # Normalize taak
            norm_taak = normalize_taken(taak, taak_type)
            if not norm_taak:
                skipped_rows += 1
                continue

            # Add to index
            combination = (code, groep)
            self.index.add(norm_taak, combination, taak_type, client_id)
            valid_rows += 1

        # Resolve best combinations
        self.index.resolve()

        # Create matcher
        self.matcher = TakenMatcher(self.index)

        self.mapping_stats = {
            'total_rows': len(df),
            'valid_rows': valid_rows,
            'skipped_rows': skipped_rows,
            'unique_keys': len(self.index._resolved),
            'has_type': has_type,
            'has_client': has_client,
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

        # Check for optional Klantnummer
        has_client = 'Klantnummer' in df.columns

        # Initialize result columns
        df['Taakgroepcode'] = ""
        df['Taakgroep'] = ""

        # Track unmatched rows
        unmatched_rows = []
        match_methods = Counter()
        total_rows = len(df)

        # Reset matcher stats
        self.matcher.match_stats = Counter()

        # Process each row
        for idx, row in df.iterrows():
            taak = str(row[col_map['Taak']]).strip() if pd.notna(row[col_map['Taak']]) else ""
            taak_type = str(row[col_map['Type']]).strip() if pd.notna(row[col_map['Type']]) else ""
            client_id = str(row['Klantnummer']).strip() if has_client and pd.notna(row.get('Klantnummer')) else None

            if not taak or not taak_type:
                unmatched_rows.append({
                    'UniekeID': idx + 1,
                    'Klantnummer': client_id or '',
                    'Taak': taak,
                    'Type': taak_type,
                    'normalisatie': '',
                })
                continue

            # Normalize
            norm_taak = normalize_taken(taak, taak_type)

            # Match
            result, method = self.matcher.match(norm_taak, taak_type, client_id)
            match_methods[method] += 1

            if result:
                df.at[idx, 'Taakgroepcode'] = result[0]
                df.at[idx, 'Taakgroep'] = result[1]
            else:
                unmatched_rows.append({
                    'UniekeID': idx + 1,
                    'Klantnummer': client_id or '',
                    'Taak': taak,
                    'Type': taak_type,
                    'normalisatie': norm_taak,
                })

        # Create unmatched DataFrame
        unmatched_df = pd.DataFrame(unmatched_rows, columns=['UniekeID', 'Klantnummer', 'Taak', 'Type', 'normalisatie'])

        # Calculate fill rate
        filled_count = total_rows - len(unmatched_rows)
        fill_rate = filled_count / total_rows if total_rows > 0 else 0

        # Verify all combinations exist in mapping
        output_combos = set()
        for idx, row in df.iterrows():
            code = row['Taakgroepcode']
            groep = row['Taakgroep']
            if code and groep:
                output_combos.add((code, groep))

        valid_combos = set(self.index.global_freq.keys())
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
            'top_unmatched': self._get_top_unmatched_terms(unmatched_df),
        }

        return df, unmatched_df, self.run_stats

    def _get_top_unmatched_terms(self, unmatched_df: pd.DataFrame, top_n: int = 10) -> List[Tuple[str, int]]:
        """Get top N most frequent unmatched normalized terms."""
        if unmatched_df.empty:
            return []

        counts = unmatched_df['normalisatie'].value_counts().head(top_n)
        return [(term, count) for term, count in counts.items()]

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
            "TAKEN MAPPING REPORT",
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

        if self.run_stats.get('top_unmatched'):
            lines.extend([
                "",
                "TOP 10 UNMATCHED TERMS:",
            ])
            for term, count in self.run_stats['top_unmatched']:
                lines.append(f"  {term}: {count}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)
