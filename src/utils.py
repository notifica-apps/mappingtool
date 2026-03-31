"""
CSV reading/writing utilities with robust handling.
"""
import csv
import io
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pytz
import pandas as pd


def detect_delimiter(sample: str) -> str:
    """
    Detect CSV delimiter by trying in order: ; -> , -> | -> tab
    """
    delimiters = [';', ',', '|', '\t']

    for delim in delimiters:
        try:
            reader = csv.reader(io.StringIO(sample), delimiter=delim)
            rows = list(reader)
            if len(rows) > 1 and len(rows[0]) > 1:
                # Check if all rows have similar column count
                col_counts = [len(row) for row in rows[:5]]
                if max(col_counts) == min(col_counts) and col_counts[0] > 1:
                    return delim
        except:
            continue

    return ';'  # Default


def read_csv_robust(file_path_or_content, is_content: bool = False) -> Tuple[pd.DataFrame, str]:
    """
    Read CSV with robust encoding and delimiter detection.

    Args:
        file_path_or_content: Either a file path or file content bytes
        is_content: If True, file_path_or_content is bytes content

    Returns:
        Tuple of (DataFrame, detected_delimiter)
    """
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']

    content = None

    if is_content:
        raw_content = file_path_or_content
    else:
        with open(file_path_or_content, 'rb') as f:
            raw_content = f.read()

    # Try encodings
    for encoding in encodings:
        try:
            content = raw_content.decode(encoding)
            break
        except (UnicodeDecodeError, AttributeError):
            continue

    if content is None:
        # Fallback: permissive decoding
        content = raw_content.decode('utf-8', errors='replace')

    # Detect delimiter
    delimiter = detect_delimiter(content[:5000])

    # Read with pandas
    try:
        df = pd.read_csv(
            io.StringIO(content),
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            na_values=[''],
            encoding='utf-8'
        )
    except Exception as e:
        raise ValueError(f"Failed to parse CSV: {e}")

    # Normalize column names (strip whitespace, preserve case for matching)
    df.columns = [col.strip() for col in df.columns]

    return df, delimiter


def normalize_column_name(name: str) -> str:
    """Normalize column name for case-insensitive matching."""
    return name.strip().lower()


def find_column(df: pd.DataFrame, target_names: List[str]) -> Optional[str]:
    """
    Find a column by trying multiple names (case-insensitive).

    Args:
        df: DataFrame to search
        target_names: List of possible column names to find

    Returns:
        The actual column name in the DataFrame, or None if not found
    """
    col_map = {normalize_column_name(col): col for col in df.columns}

    for target in target_names:
        normalized = normalize_column_name(target)
        if normalized in col_map:
            return col_map[normalized]

    return None


def validate_columns(df: pd.DataFrame, required: List[str], file_description: str) -> Dict[str, str]:
    """
    Validate that all required columns exist (case-insensitive).

    Args:
        df: DataFrame to validate
        required: List of required column names
        file_description: Description for error messages

    Returns:
        Dictionary mapping required name -> actual column name

    Raises:
        ValueError if any required column is missing
    """
    col_mapping = {}
    missing = []

    for req in required:
        actual = find_column(df, [req])
        if actual is None:
            missing.append(req)
        else:
            col_mapping[req] = actual

    if missing:
        raise ValueError(
            f"{file_description} is missing required columns: {', '.join(missing)}. "
            f"Available columns: {', '.join(df.columns)}"
        )

    return col_mapping


def get_output_filename(base_name: str, suffix: str = "") -> str:
    """
    Generate output filename with today's date (Europe/Amsterdam timezone).

    Args:
        base_name: Base filename (without extension)
        suffix: Optional suffix like '_unmatched'

    Returns:
        Filename with date appended
    """
    # Get Amsterdam timezone date
    tz = pytz.timezone('Europe/Amsterdam')
    today = datetime.now(tz).strftime('%Y-%m-%d')

    # Clean base name: remove existing date patterns and timestamps
    # Pattern: _YYYY-MM-DD or _YYYY-MM-DDTHH_MM_SS...
    import re
    base_name = re.sub(r'_\d{4}-\d{2}-\d{2}(T[\d_\.]+Z?)?$', '', base_name)

    return f"{base_name}{suffix}_{today}.csv"


def write_csv_output(df: pd.DataFrame, output_path: str):
    """
    Write DataFrame to CSV with vaste opmaak:
    - Delimiter: ;
    - Encoding: UTF-8 met BOM
    - Line endings: CRLF
    """
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        df.to_csv(
            f,
            sep=';',
            index=False,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator='\r\n',
        )


def extract_base_name(filename: str) -> str:
    """
    Extract base name from filename, removing extension and date/timestamp suffixes.
    """
    import re

    # Remove extension
    base = os.path.splitext(filename)[0]

    # Remove date patterns
    base = re.sub(r'_\d{4}-\d{2}-\d{2}(T[\d_\.]+Z?)?$', '', base)

    return base


def is_mapping_file(filename: str) -> bool:
    """Check if filename indicates a mapping file (1000_...)."""
    return filename.startswith('1000_')


def get_file_type(filename: str) -> Optional[str]:
    """
    Determine file type from filename.

    Returns:
        'WV', 'Balans', 'Taken', or None
    """
    filename_lower = filename.lower()

    if 'wv_rubrieken' in filename_lower or 'wv rubrieken' in filename_lower:
        return 'WV'
    elif 'balans_rubrieken' in filename_lower or 'balans rubrieken' in filename_lower:
        return 'Balans'
    elif 'taken' in filename_lower:
        return 'Taken'

    return None


def write_excel_output(
    enriched_df: pd.DataFrame,
    output_path: str,
    schema_df: pd.DataFrame = None,
    quality_df: pd.DataFrame = None,
):
    """
    Schrijf resultaten naar Excel met meerdere sheets.

    Args:
        enriched_df: Verrijkte mapping data
        output_path: Pad voor output bestand
        schema_df: Optioneel referentieschema (apart tabblad)
        quality_df: Optioneel kwaliteitsrapport (apart tabblad)
    """
    try:
        import openpyxl
    except ImportError:
        # Fallback naar CSV als openpyxl niet beschikbaar is
        csv_path = output_path.replace('.xlsx', '.csv')
        write_csv_output(enriched_df, csv_path)
        return csv_path

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        enriched_df.to_excel(writer, sheet_name='Mapping', index=False)

        if schema_df is not None and not schema_df.empty:
            schema_df.to_excel(writer, sheet_name='Referentie Schema', index=False)

        if quality_df is not None and not quality_df.empty:
            quality_df.to_excel(writer, sheet_name='Kwaliteitsrapport', index=False)

    return output_path
