"""
Validation Module - Geport en verbeterd vanuit notifica_app mapping_api.py

Validatielogica voor mapping-bestanden en individuele mapping-acties.
"""
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd


def validate_coa_combo(
    niveau1: str,
    niveau2: str,
    schema_df: pd.DataFrame,
    niveau1_col: str = 'Niveau1',
    niveau2_col: str = 'Niveau2',
) -> bool:
    """
    Valideer dat een (Niveau1, Niveau2) combinatie bestaat in het referentieschema.

    Args:
        niveau1: Niveau1 waarde
        niveau2: Niveau2 waarde
        schema_df: DataFrame met geldige schema-combinaties
        niveau1_col: Kolomnaam voor Niveau1
        niveau2_col: Kolomnaam voor Niveau2

    Returns:
        True als de combinatie geldig is
    """
    if schema_df is None or schema_df.empty:
        return True  # Geen schema beschikbaar → geen validatie

    mask = (
        (schema_df[niveau1_col].str.strip() == niveau1.strip()) &
        (schema_df[niveau2_col].str.strip() == niveau2.strip())
    )
    return mask.any()


def get_valid_niveau2_for_niveau1(
    niveau1: str,
    schema_df: pd.DataFrame,
    niveau1_col: str = 'Niveau1',
    niveau2_col: str = 'Niveau2',
) -> List[str]:
    """
    Haal alle geldige Niveau2 opties op voor een gegeven Niveau1.
    Gebruikt voor cascading dropdowns.

    Args:
        niveau1: Geselecteerde Niveau1 waarde
        schema_df: DataFrame met geldige schema-combinaties

    Returns:
        Gesorteerde lijst van Niveau2 waarden
    """
    if schema_df is None or schema_df.empty:
        return []

    mask = schema_df[niveau1_col].str.strip() == niveau1.strip()
    values = schema_df.loc[mask, niveau2_col].dropna().str.strip().unique().tolist()
    return sorted(values)


def get_unique_niveau1(
    schema_df: pd.DataFrame,
    niveau1_col: str = 'Niveau1',
) -> List[str]:
    """Haal alle unieke Niveau1 waarden op."""
    if schema_df is None or schema_df.empty:
        return []
    return sorted(schema_df[niveau1_col].dropna().str.strip().unique().tolist())


def validate_bulk_rows(
    rows: List[Dict],
    valid_combos: Set[Tuple],
    mapping_type: str = 'WV',
    max_errors: int = 20,
) -> Tuple[List[Dict], List[str]]:
    """
    Valideer een lijst rijen voor bulk import/correctie.

    Args:
        rows: Lijst van dicts met mapping data
        valid_combos: Set van geldige (code, N1, N2) of (code, groep) tuples
        mapping_type: 'WV', 'Balans', of 'Taken'
        max_errors: Maximaal aantal fouten om te tonen

    Returns:
        Tuple van (valid_rows, errors)
    """
    valid_rows = []
    errors = []

    for i, row in enumerate(rows, 1):
        if len(errors) >= max_errors:
            errors.append(f"... en meer fouten (max {max_errors} getoond)")
            break

        if mapping_type in ('WV', 'Balans'):
            code = str(row.get('CoA_code', '')).strip()
            n1 = str(row.get('Niveau1', '')).strip()
            n2 = str(row.get('Niveau2', '')).strip()

            if not code or not n1 or not n2:
                errors.append(f"Rij {i}: CoA_code, Niveau1 of Niveau2 ontbreekt")
                continue

            combo = (code, n1, n2)
        else:
            code = str(row.get('Taakgroepcode', '')).strip()
            groep = str(row.get('Taakgroep', '')).strip()

            if not code or not groep:
                errors.append(f"Rij {i}: Taakgroepcode of Taakgroep ontbreekt")
                continue

            combo = (code, groep)

        if valid_combos and combo not in valid_combos:
            if mapping_type in ('WV', 'Balans'):
                errors.append(f"Rij {i}: Combinatie ({code}, {n1}, {n2}) bestaat niet in mapping")
            else:
                errors.append(f"Rij {i}: Combinatie ({code}, {groep}) bestaat niet in mapping")
            continue

        valid_rows.append(row)

    return valid_rows, errors


def detect_duplicates(
    df: pd.DataFrame,
    key_cols: List[str],
) -> pd.DataFrame:
    """
    Vind duplicate rijen op basis van key kolommen.

    Returns:
        DataFrame met alleen de duplicate rijen (alle voorkomens)
    """
    if df.empty:
        return pd.DataFrame()

    # Filter alleen kolommen die bestaan
    existing_cols = [c for c in key_cols if c in df.columns]
    if not existing_cols:
        return pd.DataFrame()

    duplicated = df.duplicated(subset=existing_cols, keep=False)
    return df[duplicated].sort_values(existing_cols)
