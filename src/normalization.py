"""
Normalization functions for Taken and WV/Balans mapping.
"""
import re
from typing import Optional


# =============================================================================
# TAKEN NORMALIZATION (Part 1)
# =============================================================================

TAKEN_VERZUIM_KEYWORDS = [
    'ziekmelding', 'verzuim uren', 'arts bezoek', 'dokter', 'huisarts',
    'specialist', 'ziekenhuis', 'polikliniek', 'bedrijfsarts', 'arbo',
    'apotheek', 'consult'
]

TAKEN_SCHOLING_KEYWORDS = [
    'school', 'cursus', 'opleiding', 'training', 'workshop',
    'e learning', 'e-learning', 'certificering', 'hercertificering', 'bhv'
]

TAKEN_REISUREN_KEYWORDS = [
    'reisuren', 'reis tijd', 'reistijd', 'dienstreis', 'buiten werktijd'
]

TAKEN_URENREGISTRATIE_KEYWORDS = [
    'uren boeken', 'urenregistratie', 'uren schrijven', 'tijd schrijven', 'timesheet'
]

TAKEN_VERLOF_PATTERNS = [
    'verlof', 'adv', 'feestdagen', 'restant uren', 'seniorendagen'
]

TAKEN_PROJECTGEBONDEN_KEYWORDS = [
    'project', 'projectleider', 'projectmanager', 'projectcoordinator',
    'werkvoorbereider', 'wb', 'service', 'calculator', 'tekenaar',
    'autocad', 'cad', 'engineer', 'it specialist', 'it-specialist', 'ict specialist'
]

TAKEN_MONTAGE_KEYWORDS = [
    'montage', 'keuren', 'testen', 'in bedrijf stellen', 'ibs'
]


def normalize_taken(taak: str, taak_type: Optional[str] = None) -> str:
    """
    Normalize a Taak value according to Part 1 specifications.

    Args:
        taak: The task name to normalize
        taak_type: Optional type (Direct/Indirect) for type-specific clustering

    Returns:
        Normalized task key
    """
    if not taak or not isinstance(taak, str):
        return ""

    # 1. Lowercase
    text = taak.lower()

    # 2. Trim
    text = text.strip()

    # 3. Remove numeric prefix (max 10 chars): pattern "(digits) followed by space/-, :, ."
    text = re.sub(r'^[\d]{1,10}[\s\-\:\.]?\s*', '', text)

    # 4. Interpunction -> space
    text = re.sub(r'[^a-z0-9\s]', ' ', text)

    # 5. Multiple spaces -> single space
    text = re.sub(r'\s+', ' ', text).strip()

    # 6. Synonym clustering
    is_direct = taak_type and taak_type.strip().lower() == 'direct'

    # Check verzuim
    for kw in TAKEN_VERZUIM_KEYWORDS:
        if kw in text:
            return 'verzuim'

    # Check scholing
    for kw in TAKEN_SCHOLING_KEYWORDS:
        if kw in text:
            return 'scholing'

    # Check reisuren
    for kw in TAKEN_REISUREN_KEYWORDS:
        if kw in text:
            return 'reisuren'

    # Check urenregistratie
    for kw in TAKEN_URENREGISTRATIE_KEYWORDS:
        if kw in text:
            return 'urenregistratie'

    # Check verlof (any word containing verlof)
    if 'verlof' in text or any(p in text for p in TAKEN_VERLOF_PATTERNS):
        return 'verlof'

    # Type-specific clustering (only for Direct)
    if is_direct:
        # Check projectgebonden
        for kw in TAKEN_PROJECTGEBONDEN_KEYWORDS:
            if kw in text:
                return 'projectgebonden'

        # Check montage
        for kw in TAKEN_MONTAGE_KEYWORDS:
            if kw in text:
                return 'montage'

    return text


# =============================================================================
# WV/BALANS NORMALIZATION (Part 2)
# =============================================================================

# Pass 1: Typo fixes, abbreviations, compound words
# Wordt EERST uitgevoerd zodat samengestelde woorden intact blijven
WV_BALANS_PASS1 = [
    # === Typo fixes (FIRST - before anything else) ===
    (r'\bverrzekering\b', 'verzekering'),      # dubbele r
    (r'\bservcie\b', 'service'),                # letters omgedraaid

    # === Multi-word abbreviations (BEFORE single-word rules) ===
    (r'\bpers\s+kn\b', 'personeelskosten'),    # Pers.kn. → personeelskosten
    (r'\bsal\s+kn\b', 'salariskosten'),        # Sal.kn. → salariskosten

    # === Single-word abbreviations ===
    (r'\bdoorber\b', 'doorbelasting'),          # Doorber. → doorbelasting
    (r'\bonderh\b', 'onderhoud'),              # Onderh. → onderhoud
    (r'\breisk\b', 'reiskosten'),              # Reisk. → reiskosten
    (r'\buitbet\b', 'uitbetaling'),            # Uitbet. → uitbetaling
    (r'\badmie\b', 'administratie'),           # Admie → administratie
    (r'\bsoc\b', 'sociaal'),                   # Soc. → sociaal
    (r'\binkasso\b', 'incasso'),               # spelling variant
    (r'\bvoorz\b', 'voorziening'),             # Voorz. → voorziening
    (r'\bsvc\b', 'service'),                   # Svc → service

    # === Compound word splitting (met boundary check) ===
    (r'\bvzk\b', ' verzekering'),              # vzk → verzekering (als los woord)
    (r'(?<=[a-z])vzk\b', ' verzekering'),      # ziekengeldvzk → ziekengeld verzekering

    # === Samengestelde woorden EERST (voor generieke verwijderingen) ===
    (r'\blidmaatschapskosten\b', 'lidmaatschap'),
    (r'\breiskostenverg\b', 'reiskostenvergoeding'),
    (r'\bverzekeringspremies\b', 'verzekering'),
    (r'\bverzekeringskosten\b', 'verzekering'),
    (r'\binkoopkosten\b', 'inkoop'),
    (r'\bbalieverkopen\b', 'balie omzet'),
    (r'\bverkopen balie\b', 'balie omzet'),

    # === Synoniemen ===
    (r'\bverkopen\b', 'omzet'),
    (r'\bverkoop\b', 'omzet'),
    (r'\binkopen\b', 'inkoop'),
    (r'\bafschr\.\b', 'afschrijving'),
    (r'\bafschrijv\b', 'afschrijving'),
    (r'\bafschrijvingen\b', 'afschrijving'),
    (r'\bontv\.\b', 'ontvangen'),
    (r'\bintr\b', 'interest'),
    (r'\bkvk\b', 'kamer van koophandel'),
    (r'\bwg\b', 'werkgevers'),
    (r'\bohw\b', 'onderhanden werk'),
    (r'\bsvw\b', 'sociale verzekeringswet'),
    (r'\bwia\b', 'wia'),
    (r'\bwga\b', 'wga'),
    (r'\bwkr\b', 'werkkostenregeling'),
    (r'\boom\b', 'sociaal fonds'),
    (r'\bprefab\b', 'prefab'),
    (r'\bvso\b', 'vaststellingsovereenkomst'),
]

# Pass 2: Generieke woordverwijdering
# Wordt NA pass 1 uitgevoerd zodat samengestelde woorden al zijn omgezet
WV_BALANS_PASS2 = [
    (r'\bkosten\b', ''),    # remove (NA samengestelde woorden)
    (r'\bkn\b', ''),        # remove (abbreviation for kosten) - NA pers kn/sal kn
    (r'\bhardware\b', ''),  # remove
]


def normalize_rubriek(rubriek: str) -> str:
    """
    Normalize a Rubriek value according to Part 2 specifications.

    Args:
        rubriek: The rubriek name to normalize

    Returns:
        Normalized rubriek key
    """
    if not rubriek or not isinstance(rubriek, str):
        return ""

    # 1. Lowercase
    text = rubriek.lower()

    # 2. Trim
    text = text.strip()

    # 3. Remove numeric prefix (1-5 digits with optional space or - after)
    text = re.sub(r'^[\d]{1,5}[\s\-]?\s*', '', text)

    # 4. Interpunction -> space
    text = re.sub(r'[^a-z0-9\s]', ' ', text)

    # 5. Multiple spaces -> single space
    text = re.sub(r'\s+', ' ', text).strip()

    # 6. Apply replacements in twee passes
    # Pass 1: Typo fixes, abbreviaties, samengestelde woorden
    for pattern, replacement in WV_BALANS_PASS1:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Pass 2: Generieke woordverwijdering (NA samengestelde woorden)
    for pattern, replacement in WV_BALANS_PASS2:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def clean_coa_code(code) -> str:
    """
    Clean CoA_code: remove .0 suffix and ensure it's a string.
    """
    if code is None:
        return ""

    code_str = str(code).strip()

    # Remove .0 suffix
    if code_str.endswith('.0'):
        code_str = code_str[:-2]

    # Also handle float conversion issues
    try:
        if '.' in code_str:
            # Try to convert to int if it's a whole number
            float_val = float(code_str)
            if float_val == int(float_val):
                code_str = str(int(float_val))
    except (ValueError, TypeError):
        pass

    return code_str


def clean_taakgroepcode(code) -> str:
    """
    Clean Taakgroepcode: remove .0 suffix and ensure it's a string.
    """
    return clean_coa_code(code)  # Same logic
