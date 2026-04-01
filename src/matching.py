"""
Matching algorithms for Taken and WV/Balans mapping.
"""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple
import re


def token_set_ratio(s1: str, s2: str) -> float:
    """
    Calculate token set similarity ratio (similar to fuzzywuzzy token_set_ratio).
    Order-independent comparison of token sets.
    """
    if not s1 or not s2:
        return 0.0

    tokens1 = set(s1.lower().split())
    tokens2 = set(s2.lower().split())

    if not tokens1 or not tokens2:
        return 0.0

    # Intersection and differences
    intersection = tokens1 & tokens2
    diff1 = tokens1 - tokens2
    diff2 = tokens2 - tokens1

    # Build comparison strings
    sorted_intersection = ' '.join(sorted(intersection))
    combined1 = ' '.join(sorted(intersection | diff1))
    combined2 = ' '.join(sorted(intersection | diff2))

    # Compare different combinations
    ratios = []

    if sorted_intersection:
        ratios.append(SequenceMatcher(None, sorted_intersection, combined1).ratio())
        ratios.append(SequenceMatcher(None, sorted_intersection, combined2).ratio())
        ratios.append(SequenceMatcher(None, combined1, combined2).ratio())
    else:
        ratios.append(SequenceMatcher(None, combined1, combined2).ratio())

    return max(ratios) * 100 if ratios else 0.0


def token_sort_ratio(s1: str, s2: str) -> float:
    """
    Calculate token sort ratio: sort tokens alphabetically and compare.
    """
    if not s1 or not s2:
        return 0.0

    sorted1 = ' '.join(sorted(s1.lower().split()))
    sorted2 = ' '.join(sorted(s2.lower().split()))

    return SequenceMatcher(None, sorted1, sorted2).ratio() * 100


def prefix_match(target: str, candidate: str) -> bool:
    """
    Check if candidate is a prefix of target or vice versa (token-level).
    """
    target_tokens = target.lower().split()
    candidate_tokens = candidate.lower().split()

    if not target_tokens or not candidate_tokens:
        return False

    # Check if one is prefix of the other
    min_len = min(len(target_tokens), len(candidate_tokens))
    return target_tokens[:min_len] == candidate_tokens[:min_len]


def subterm_match(target: str, candidate: str) -> bool:
    """
    Check if one string fully contains the other (token-level).
    """
    target_tokens = set(target.lower().split())
    candidate_tokens = set(candidate.lower().split())

    if not target_tokens or not candidate_tokens:
        return False

    return target_tokens.issubset(candidate_tokens) or candidate_tokens.issubset(target_tokens)


class MappingIndex:
    """
    Index for efficient mapping lookups with frequency-based tie-breaking.
    """

    def __init__(self):
        # Main index: normalized_key -> (code, group/niveau) with frequencies
        self.exact_index: Dict[str, Dict[Tuple, int]] = defaultdict(lambda: defaultdict(int))

        # Token index for fuzzy matching candidate narrowing
        self.token_index: Dict[str, Set[str]] = defaultdict(set)

        # First-word index
        self.first_word_index: Dict[str, Set[str]] = defaultdict(set)

        # Global frequencies
        self.global_freq: Dict[Tuple, int] = defaultdict(int)

        # Type-specific indices (for Taken)
        self.type_index: Dict[str, Dict[str, Dict[Tuple, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )

        # Client-specific indices
        self.client_index: Dict[str, Dict[str, Dict[Tuple, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )

        # Resolved best combinations per key
        self._resolved: Dict[str, Tuple] = {}
        self._resolved_by_type: Dict[str, Dict[str, Tuple]] = defaultdict(dict)

    def add(
        self,
        normalized_key: str,
        combination: Tuple,
        taak_type: Optional[str] = None,
        client_id: Optional[str] = None
    ):
        """Add a mapping entry to the index."""
        if not normalized_key or not combination:
            return

        # Update exact index
        self.exact_index[normalized_key][combination] += 1
        self.global_freq[combination] += 1

        # Update token index
        tokens = normalized_key.split()
        for token in tokens:
            if len(token) >= 3:
                self.token_index[token].add(normalized_key)

        # Update first-word index
        if tokens:
            self.first_word_index[tokens[0]].add(normalized_key)

        # Update type-specific index
        if taak_type:
            type_key = taak_type.strip().lower()
            self.type_index[type_key][normalized_key][combination] += 1

        # Update client-specific index
        if client_id:
            self.client_index[client_id][normalized_key][combination] += 1

    def resolve(self):
        """
        Resolve the best combination for each key using tie-break rules:
        1. Highest frequency within that key
        2. Highest global frequency
        3. Lowest numeric code
        """
        self._resolved = {}

        for key, combinations in self.exact_index.items():
            self._resolved[key] = self._select_best(combinations)

        # Resolve by type
        for type_key, type_data in self.type_index.items():
            for key, combinations in type_data.items():
                self._resolved_by_type[type_key][key] = self._select_best(combinations)

    def _select_best(self, combinations: Dict[Tuple, int]) -> Tuple:
        """Select best combination using tie-break rules."""
        if not combinations:
            return None

        candidates = list(combinations.items())

        # Sort by: -local_freq, -global_freq, numeric_code
        def sort_key(item):
            combo, local_freq = item
            global_freq = self.global_freq.get(combo, 0)

            # Extract numeric code for comparison
            code = combo[0] if combo else ''
            try:
                numeric_code = int(str(code).replace('.0', ''))
            except (ValueError, TypeError):
                numeric_code = float('inf')

            return (-local_freq, -global_freq, numeric_code)

        candidates.sort(key=sort_key)
        return candidates[0][0]

    def get_exact(self, normalized_key: str, taak_type: Optional[str] = None) -> Optional[Tuple]:
        """Get exact match for a normalized key."""
        if taak_type:
            type_key = taak_type.strip().lower()
            if type_key in self._resolved_by_type and normalized_key in self._resolved_by_type[type_key]:
                return self._resolved_by_type[type_key][normalized_key]

        return self._resolved.get(normalized_key)

    def get_candidates(self, normalized_key: str, taak_type: Optional[str] = None) -> Set[str]:
        """Get candidate keys that share tokens with the target."""
        candidates = set()
        tokens = normalized_key.split()

        for token in tokens:
            if len(token) >= 3:
                candidates.update(self.token_index.get(token, set()))

        if tokens:
            candidates.update(self.first_word_index.get(tokens[0], set()))

        # Filter by type if specified
        if taak_type:
            type_key = taak_type.strip().lower()
            if type_key in self._resolved_by_type:
                candidates = candidates & set(self._resolved_by_type[type_key].keys())

        return candidates

    def get_all_keys(self, taak_type: Optional[str] = None) -> Set[str]:
        """Get all keys in the index."""
        if taak_type:
            type_key = taak_type.strip().lower()
            if type_key in self._resolved_by_type:
                return set(self._resolved_by_type[type_key].keys())
        return set(self._resolved.keys())

    def get_top_by_type(self, taak_type: str) -> Optional[Tuple]:
        """Get the most common combination for a given type."""
        type_key = taak_type.strip().lower()

        if type_key not in self.type_index:
            return None

        # Aggregate all combinations for this type
        type_combos: Dict[Tuple, int] = defaultdict(int)
        for key_combos in self.type_index[type_key].values():
            for combo, freq in key_combos.items():
                type_combos[combo] += freq

        if not type_combos:
            return None

        return self._select_best(type_combos)

    def get_top_by_client_and_type(self, client_id: str, taak_type: str) -> Optional[Tuple]:
        """Get the most common combination for a given client and type."""
        if client_id not in self.client_index:
            return None

        type_key = taak_type.strip().lower()

        # Filter client entries by type
        client_type_combos: Dict[Tuple, int] = defaultdict(int)
        for key, combos in self.client_index[client_id].items():
            # Check if this key exists in the type index
            if type_key in self.type_index and key in self.type_index[type_key]:
                for combo, freq in combos.items():
                    client_type_combos[combo] += freq

        if not client_type_combos:
            return None

        return self._select_best(client_type_combos)


class TakenMatcher:
    """
    Matcher for Taken (task) mapping with all specified matching strategies.
    """

    # Anchor patterns: regex → genormaliseerde key die in de index moet staan
    # Deze vangen variaties op die normalisatie niet exact reduceert
    ANCHOR_PATTERNS = [
        (r'^verzuim|ziekte|ziek\b', 'verzuim'),
        (r'^scholing|cursus|opleiding|training|workshop', 'scholing'),
        (r'^reisuren|reistijd|reis\s*uren', 'reisuren'),
        (r'^urenregistratie|uren\s*boek|timesheet', 'urenregistratie'),
        (r'^verlof|adv\b|feestdag', 'verlof'),
        (r'^montage|keuren|testen|in bedrijf stellen', 'montage'),
        (r'^project\b|werkvoorbereider|engineer', 'projectgebonden'),
    ]

    def __init__(self, index: MappingIndex, valid_combos: set = None):
        self.index = index
        self.match_stats = Counter()
        self.valid_combos = valid_combos or set()

    def match(
        self,
        normalized_key: str,
        taak_type: str,
        client_id: Optional[str] = None
    ) -> Tuple[Optional[Tuple], str]:
        """
        Match a normalized task key to a mapping combination.

        Args:
            normalized_key: Normalized task key
            taak_type: Type (Direct/Indirect) - required
            client_id: Optional client ID for client-specific matching

        Returns:
            Tuple of (combination, match_method) or (None, 'unmatched')
        """
        type_key = taak_type.strip().lower() if taak_type else ''

        # Step A: Exact match
        result = self.index.get_exact(normalized_key, taak_type)
        if result:
            self.match_stats['A_exact'] += 1
            return result, 'A_exact'

        # Step B: Anchor match via regex patterns
        for pattern, anchor_key in self.ANCHOR_PATTERNS:
            if re.search(pattern, normalized_key, re.IGNORECASE):
                result = self.index.get_exact(anchor_key, taak_type)
                if result:
                    if not self.valid_combos or result in self.valid_combos:
                        self.match_stats['B_anchor'] += 1
                        return result, 'B_anchor'

        # Step C: Prefix/subterm match
        candidates = self.index.get_candidates(normalized_key, taak_type)
        for candidate_key in candidates:
            if prefix_match(normalized_key, candidate_key) or subterm_match(normalized_key, candidate_key):
                result = self.index.get_exact(candidate_key, taak_type)
                if result:
                    self.match_stats['C_prefix'] += 1
                    return result, 'C_prefix'

        # Step D: Token set ratio >= 90%
        best_score = 0
        best_result = None
        best_key = None

        for candidate_key in candidates:
            score = token_set_ratio(normalized_key, candidate_key)
            if score >= 90 and score > best_score:
                result = self.index.get_exact(candidate_key, taak_type)
                if result:
                    best_score = score
                    best_result = result
                    best_key = candidate_key

        if best_result:
            self.match_stats['D_token_set'] += 1
            return best_result, 'D_token_set'

        # Step E: Token sort + difflib >= 90%
        best_score = 0
        best_result = None

        for candidate_key in candidates:
            score = token_sort_ratio(normalized_key, candidate_key)
            if score >= 90 and score > best_score:
                result = self.index.get_exact(candidate_key, taak_type)
                if result:
                    best_score = score
                    best_result = result

        if best_result:
            self.match_stats['E_token_sort'] += 1
            return best_result, 'E_token_sort'

        # Step G: Token-based majority voting
        tokens = [t for t in normalized_key.split() if len(t) >= 3]
        if tokens:
            votes: Dict[Tuple, int] = defaultdict(int)

            for token in tokens:
                token_keys = self.index.token_index.get(token, set())
                for key in token_keys:
                    combo = self.index.get_exact(key, taak_type)
                    if combo:
                        votes[combo] += 1

            if votes:
                # Get winner with >= 2 votes
                top_votes = sorted(votes.items(), key=lambda x: (-x[1], x[0]))
                if top_votes[0][1] >= 2:
                    self.match_stats['G_majority'] += 1
                    return top_votes[0][0], 'G_majority'

        # Step H: Backstop
        if client_id:
            result = self.index.get_top_by_client_and_type(client_id, taak_type)
            if result:
                self.match_stats['H_client_top'] += 1
                return result, 'H_client_top'

        result = self.index.get_top_by_type(taak_type)
        if result:
            self.match_stats['H_type_top'] += 1
            return result, 'H_type_top'

        self.match_stats['unmatched'] += 1
        return None, 'unmatched'


class WVBalansMatcher:
    """
    Matcher for WV/Balans (rubriek) mapping with anchors and guardrails.

    Anchors verwijzen naar (Niveau1, Niveau2) paren. Bij het matchen wordt
    gecontroleerd of dat paar daadwerkelijk in de geladen brondata (index) bestaat.
    Zo niet, wordt de anchor overgeslagen — er worden nooit codes verzonnen.
    """

    # Fixed anchors with exact codes (alleen voor WV, niet voor Balans)
    FIXED_ANCHORS = [
        (r'^omzet$|^balie omzet$', ('101001', 'Omzet', 'Omzet')),
        (r'^afschrijving$|^afschr$', ('109001', 'Afschrijving', 'Afschrijving')),
    ]

    # WV-specifieke anchors — alleen actief als Niveau1/Niveau2 in de index zit
    WV_NIVEAU_ANCHORS = [
        # --- Resultaat deelneming (EERST - voorkomt false match op prefab/holding anchors) ---
        (r'\bresultaat\s+deelneming\b', ('Financiele Baten en Lasten', 'Resultaat Deelneming (financiele baten en lasten)')),

        # --- Personeelskosten ---
        (r'^pensioen', ('Personeelkosten', 'Pensioenlasten')),
        (r'^reiskosten|reiskosten\s+woon|woon\s*werk', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'sociale verzekeringswet|svw|wia|wga|werkgeversdeel|wg deel|sociaal fonds',
         ('Personeelkosten', 'Sociale lasten')),
        (r'ziekteverzuim|ziekengeld', ('Personeelkosten', 'Sociale lasten')),
        (r'premiekorting|loonheffingskorting', ('Personeelkosten', 'Sociale lasten')),
        (r'ongevallenverzekering', ('Personeelkosten', 'Sociale lasten')),
        (r'werkkostenregeling', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'personeelskosten.*(vrijstelling|waardering|intermediair)', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'tipcheque|personeelsgeschenk|kerstpakket', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'vaststellingsovereenkomst|transitievergoeding|ontslagvergoeding', ('Personeelkosten', 'Personeelskosten Overig')),

        # --- Directe kosten ---
        (r'^inleen', ('Directe kosten', 'Onderaanneming')),
        (r'toeslag onderaanneming', ('Directe kosten', 'Onderaanneming')),
        (r'toeslag (montage|ondersteuning|materiaal)', ('Directe kosten', None)),
        (r'\bprefab\b|prefab', ('Directe kosten', 'Materiaal')),
        (r'bouwbegeleiding', ('Directe kosten', 'Directe arbeidkosten')),

        # --- Omzet ---
        (r'gefactureerd.*ew|gefactureerde.*termijnen|gefactureerde.*verkopen',
         ('Omzet', 'Projectwaardering /-resultaat')),
        (r'opbrengst afgesloten werken|kosten afgesloten werken|waarderingsresultaat|schade',
         ('Omzet', 'Projectwaardering /-resultaat')),
        (r'verkoopfacturen', ('Omzet', 'Omzet')),
        (r'^gefactureerd', ('Omzet', 'Omzet')),

        # --- Overige bedrijfskosten ---
        (r'door te belasten|doorbelasting', ('Overige bedrijfskosten', 'Doorbelastingen')),
        (r'opslag doorbelast', ('Overige bedrijfskosten', 'Doorbelastingen')),
        (r'^onderhoud', ('Overige bedrijfskosten', 'Huisvestingkosten')),
        (r'tekenmateriaal', ('Overige bedrijfskosten', 'Kantoorkosten')),
        (r'datacommunicatie|telecommunicatie|telefoonvergoeding|telefoon',
         ('Overige bedrijfskosten', 'Kantoorkosten')),
        (r'parkeerkosten|bedrijfsauto', ('Overige bedrijfskosten', 'Autokosten en overige Transportkosten')),
        (r'container|vracht', ('Overige bedrijfskosten', 'Autokosten en overige Transportkosten')),
        (r'gereedschap', ('Overige bedrijfskosten', 'Gereedschaps- en exploitatiekosten')),
        (r'automatisering', ('Overige bedrijfskosten', 'Kantoorkosten')),
        (r'bedrijfsaansprakelijkheidsverzekering', ('Overige bedrijfskosten', 'Verzekeringskosten')),
        (r'bestuursvergoeding|managementvergoeding|management\s*fee|beheersvergoeding',
         ('Overige bedrijfskosten', 'Management Fee')),
        (r'incasso', ('Overige bedrijfskosten', 'Algemene kosten')),
        (r'\bcertificat', ('Overige bedrijfskosten', 'Algemene kosten')),
        (r'kwijtschelding|afboek', ('Overige bedrijfskosten', 'Bijzondere baten en lasten')),
        (r'order.*administratie', ('Overige bedrijfskosten', 'Algemene kosten')),
        (r'werkzaamheden\s+via', ('Overige bedrijfskosten', 'Algemene kosten')),

        # --- Directe kosten extra ---
        (r'\baftimmering\b', ('Directe kosten', 'Materiaal')),
        (r'\bproductiebedrijven\b', ('Directe kosten', 'Onderaanneming')),

        # --- Personeelkosten extra ---
        (r'\boverwerkuren\b', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'\bovernachtingsuren\b', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'\bstoringsdiensten\b', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'\bwasgeld\b', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'\bcommissarissenbeloning\b', ('Overige bedrijfskosten', 'Management Fee')),
        (r'\brvu\s+fonds\b', ('Personeelkosten', 'Personeelskosten Overig')),
        (r'\bvv\s+agv\s+bov\b', ('Personeelkosten', 'Sociale lasten')),
        (r'\blkv\b', ('Personeelkosten', 'Sociale lasten')),
        (r'\boctrooikosten\b', ('Overige bedrijfskosten', 'Algemene kosten')),
        (r'\bkamer van koophandel\b', ('Overige bedrijfskosten', 'Algemene kosten')),
        (r'\bparkbijdrage\b', ('Overige bedrijfskosten', 'Huisvestingkosten')),
        (r'\bcalculatiebureau\b', ('Overige bedrijfskosten', 'Algemene kosten')),
        (r'\buitleen\b.*\bic\b', ('Overige bedrijfskosten', 'Doorbelastingen')),
        (r'\bwerkenresultaat\b', ('Omzet', 'Projectwaardering /-resultaat')),
        (r'\bba\s+niet\s+projectgebonden\b', ('Omzet', 'Projectwaardering /-resultaat')),
        (r'\bcorr\s+ba\b', ('Omzet', 'Projectwaardering /-resultaat')),
        (r'\bartikelgroep\b', ('Directe kosten', 'Materiaal')),
        (r'^montage\b', ('Directe kosten', 'Directe arbeidkosten')),
        (r'^w\s+.*\bproj\b', ('Directe kosten', 'Directe arbeidkosten')),
        (r'\bstoring\b', ('Directe kosten', 'Directe arbeidkosten')),
        (r'\bregiewerk\b', ('Directe kosten', 'Directe arbeidkosten')),
        (r'\bstekkerklaar\b', ('Directe kosten', 'Directe arbeidkosten')),
        (r'\bgrootboekrekening\b', ('Overige bedrijfskosten', 'Algemene kosten')),
        (r'\bprijsverschil\b', ('Directe kosten', 'Materiaal')),
        (r'\bkoel\b.*\bvries\b', ('Directe kosten', 'Directe arbeidkosten')),
        (r'\bkoudwater\b', ('Directe kosten', 'Directe arbeidkosten')),
        (r'\bklimaat\b', ('Directe kosten', 'Directe arbeidkosten')),

        # --- Financieel ---
        (r'doorbelasting\s+ohw|\bohw\b|doorbelasting\s+onderhanden werk', ('Onderhanden werk', None)),
        (r'interest|rente', ('Financiele Baten en Lasten', None)),
        (r'mutatie.*voorziening', ('Balans', 'voorzieningen')),
        (r'^resultaat', ('Financiele Baten en Lasten', 'Resultaat Deelneming (financiele baten en lasten)')),
        (r'voorraad', ('Omzet', 'Projectwaardering /-resultaat')),
    ]

    # Balans-specifieke anchors — alle Niveau-paren komen uit de brondata
    BALANS_NIVEAU_ANCHORS = [
        # --- Liquide middelen (bankrekeningen) ---
        (r'\brabo\b|\babn\b|\bing\b|\byounique\b|\bknab\b|\btriodos\b|\bgiro\b',
         ('Vlottende Activa', 'Liquide Middelen')),
        # IBAN-patroon (NL + 2 cijfers + bankcode)
        (r'^nl\d{2}\s',
         ('Vlottende Activa', 'Liquide Middelen')),

        # --- Belastingen ---
        (r'\bbtw\b|\bob\b', ('Kortlopende schulden', 'Belastingen en premies sociale verzekering')),
        (r'betaling.*(belasting|loonheffing|lh\b)',
         ('Kortlopende schulden', 'Belastingen en premies sociale verzekering')),

        # --- Deelnemingen ---
        (r'^deelneming\b', ('Financiele Vaste Activa', 'Deelneming')),

        # --- Rekening courant (intercompany) ---
        (r'\brekening courant\b', ('Kortlopende schulden', 'Schulden aan groepsmaatschappijen')),
        (r'\brc\b', ('Kortlopende schulden', 'Schulden aan groepsmaatschappijen')),

        # --- Betaling/schulden ---
        (r'betaling.*(vakantie|wga|er\b)', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'^betaling\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'vooruitontvangen', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'abonnement.*omzet|gerealiseerde omzet', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'^te bet\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'^nog te bet\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'\binhouding\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'\btussenrek\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'\bkrediteuren\b', ('Kortlopende schulden', 'Crediteuren')),

        # --- Voorzieningen ---
        (r'garantievoorziening|garantievoorz', ('Voorzieningen', 'Overige voorzieningen')),
        (r'voorziening', ('Voorzieningen', 'Overige voorzieningen')),

        # --- Vorderingen ---
        (r'borgstorting', ('Vlottende Activa', 'Overige Vorderingen')),
        (r'voorschot', ('Vlottende Activa', 'Overige Vorderingen')),
        (r'nog te factur', ('Vlottende Activa', 'Overige Vorderingen')),

        # --- Eigen vermogen ---
        (r'kapitaalversterking|kapitaal', ('Eigen vermogen', 'Geplaatst Kapitaal')),

        # --- Vaste activa ---
        (r'aanschaf', ('Vaste Activa', 'Vaste Activa')),
        (r'\bpand\b|straat\b|weg\b|laan\b|plein\b', ('Vaste Activa', 'Vaste Activa')),
        (r'\binventaris', ('Vaste Activa', 'Vaste Activa')),
        (r'\bafschrijving\s+pand', ('Vaste Activa', 'Vaste Activa')),

        # --- Immaterieel ---
        (r'rechten.*intellectuele|intellectueel', ('Immateriele Vaste Activa', 'Goodwill')),

        # --- Inkoopwaarde (onderhanden projecten) ---
        (r'\binkoopwaarde\b', ('Vlottende Activa', 'Onderhanden projecten')),

        # --- Pensioenvoorziening ---
        (r'\bpensioenvoorziening\b', ('Voorzieningen', 'Overige voorzieningen')),

        # --- Winst lopend jaar ---
        (r'\bwinst\s+lopend\b', ('Eigen vermogen', 'Onverdeeld resultaat')),

        # --- Aandeel derden ---
        (r'\baandeel\s+derden\b', ('Eigen vermogen', 'Aandeel Derden')),

        # --- Cumulatief aflossing (leaseauto's) ---
        (r'\bcumulatief\s+aflossing\b', ('Vaste Activa', 'Vaste Activa')),

        # --- Voorraad ---
        (r'\bvoorraad', ('Vlottende Activa', 'Voorraden')),
        (r'\bmagazijn', ('Vlottende Activa', 'Voorraden')),

        # --- Vorderingen extra ---
        (r'\bte ontvangen\b', ('Vlottende Activa', 'Overige Vorderingen')),
        (r'\bvordering\b', ('Vlottende Activa', 'Overige Vorderingen')),
        (r'\bverrekening\b', ('Vlottende Activa', 'Overige Vorderingen')),

        # --- Schulden extra ---
        (r'\bwga\b.*\baf te dragen\b', ('Kortlopende schulden', 'Belastingen en premies sociale verzekering')),
        (r'\bwia\b.*\baf te dragen\b', ('Kortlopende schulden', 'Belastingen en premies sociale verzekering')),
        (r'\baflopende verplichting\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'\binkoopfacturen\b', ('Kortlopende schulden', 'Crediteuren')),

        # --- Eigen vermogen extra ---
        (r'\begalisatie\s+reserve\b', ('Eigen vermogen', 'Overige reserves')),
        (r'\bbalansopening\b', ('Eigen vermogen', 'Onverdeeld resultaat')),

        # --- Overig ---
        (r'\bgeactiveerde\b', ('Vaste Activa', 'Vaste Activa')),
        (r'\bkantoorvoorraad\b', ('Vlottende Activa', 'Voorraden')),
        (r'\bvaste\s+termijn\s+rekening\b', ('Vlottende Activa', 'Liquide Middelen')),
        (r'\bconversie\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'\bcorrectie\s+wb\b|\bcorr\s+wb\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),
        (r'^toegevoegd\b', ('Kortlopende schulden', 'Overige schulden en overlopende passiva')),

        # --- Onderhanden projecten ---
        (r'^project\b', ('Vlottende Activa', 'Onderhanden projecten')),

        # --- Intercompany (BV-namen zonder RC/lening prefix → schulden groepsmaatschappijen) ---
        (r'^(?!.*\b(?:rc|lening|deelneming|kapitaal|borgstorting)\b).*(?:/|beveiliging|automation|nedkom)',
         ('Kortlopende schulden', 'Schulden aan groepsmaatschappijen')),

        # --- Deelnemingen (BV-namen zonder RC) ---
        (r'\bholding\b|\bb\s*v\b|\bbv\b', ('Financiele Vaste Activa', 'Deelneming')),
    ]

    def __init__(self, index: MappingIndex):
        self.index = index
        self.match_stats = Counter()

        # Detecteer of dit een Balans of WV index is op basis van de Niveau1-waarden
        self._is_balans = self._detect_balans()

        # Kies de juiste anchor-lijst op basis van het type
        self.NIVEAU_ANCHORS = self.BALANS_NIVEAU_ANCHORS if self._is_balans else self.WV_NIVEAU_ANCHORS

        # Build niveau lookup from index
        self.niveau_to_codes: Dict[Tuple[str, str], List[Tuple]] = defaultdict(list)
        self._build_niveau_lookup()

    def _detect_balans(self) -> bool:
        """Detecteer of de geladen index Balans-data bevat (vs WV).

        Kijkt naar de Niveau1-waarden: Balans heeft 'Vaste Activa', 'Vlottende Activa', etc.
        WV heeft 'Omzet', 'Personeelkosten', 'Overige bedrijfskosten', etc.
        """
        balans_indicators = {'vaste activa', 'vlottende activa', 'kortlopende schulden',
                             'langlopende schulden', 'eigen vermogen', 'voorzieningen',
                             'financiele vaste activa', 'immateriele vaste activa'}
        n1_values = set()
        for key, combo in self.index._resolved.items():
            if combo and len(combo) >= 3:
                n1_values.add(combo[1].lower().strip())

        overlap = n1_values & balans_indicators
        return len(overlap) >= 2  # Als 2+ Balans-Niveau1 waarden voorkomen → Balans

    def _build_niveau_lookup(self):
        """Build lookup from (Niveau1, Niveau2) to available codes."""
        for key, combo in self.index._resolved.items():
            if combo and len(combo) >= 3:
                code, n1, n2 = combo[0], combo[1], combo[2]
                # Normalize for lookup
                n1_norm = n1.lower().strip() if n1 else ''
                n2_norm = n2.lower().strip() if n2 else ''
                self.niveau_to_codes[(n1_norm, n2_norm)].append(combo)

        # Sort each list by numeric code (lowest first)
        for key in self.niveau_to_codes:
            self.niveau_to_codes[key].sort(key=lambda c: self._numeric_code(c[0]))

    def _numeric_code(self, code: str) -> int:
        """Convert code to numeric for comparison."""
        try:
            return int(str(code).replace('.0', ''))
        except (ValueError, TypeError):
            return float('inf')

    def _find_by_niveau(self, niveau1: str, niveau2: Optional[str]) -> Optional[Tuple]:
        """Find best combination matching the given niveaus.

        Uses a 3-step fallback strategy:
        1. Exact match on (Niveau1, Niveau2)
        2. Exact Niveau1, any Niveau2
        3. Substring match on Niveau1 (and optionally Niveau2)
        This handles naming variations across clients (e.g. 'Personeelkosten' vs 'Personeelskosten').
        """
        n1_norm = niveau1.lower().strip() if niveau1 else ''

        # Step 1: Exact (n1, n2) match
        if niveau2:
            n2_norm = niveau2.lower().strip()
            combos = self.niveau_to_codes.get((n1_norm, n2_norm), [])
            if combos:
                return combos[0]  # Already sorted by lowest code

        # Step 2: Exact n1 match, any n2
        for (n1, n2), combos in self.niveau_to_codes.items():
            if n1 == n1_norm:
                if combos:
                    return combos[0]

        # Step 3: Similarity match on n1 (handles 'Personeelkosten' vs 'Personeelskosten' etc.)
        n2_norm = niveau2.lower().strip() if niveau2 else ''
        best_match = None
        best_score = 0.0

        for (n1, n2), combos in self.niveau_to_codes.items():
            if not combos:
                continue
            # Check n1 similarity (SequenceMatcher ratio > 0.85)
            n1_ratio = SequenceMatcher(None, n1_norm, n1).ratio()
            if n1_ratio < 0.85:
                continue
            # If we have a target n2, prefer matches where n2 also matches
            if n2_norm:
                n2_ratio = SequenceMatcher(None, n2_norm, n2).ratio()
                if n2_ratio >= 0.85:
                    combined = n1_ratio + n2_ratio
                    if combined > best_score:
                        best_score = combined
                        best_match = combos[0]
                    continue
            # Track best n1-only match
            if n1_ratio > best_score:
                best_score = n1_ratio
                best_match = combos[0]

        return best_match

    def match(self, normalized_key: str) -> Tuple[Optional[Tuple], str]:
        """
        Match a normalized rubriek key to a mapping combination.

        Returns:
            Tuple of (combination, match_method) or (None, 'unmatched')
        """
        # Step 1: Exact match
        result = self.index.get_exact(normalized_key)
        if result:
            self.match_stats['exact'] += 1
            return result, 'exact'

        # Step 2: Fixed anchors (alleen voor WV, niet voor Balans)
        if not self._is_balans:
            for pattern, fixed_combo in self.FIXED_ANCHORS:
                if re.search(pattern, normalized_key, re.IGNORECASE):
                    self.match_stats['anchor_fixed'] += 1
                    return fixed_combo, 'anchor_fixed'

        # Step 3: Niveau anchors
        for pattern, (niveau1, niveau2) in self.NIVEAU_ANCHORS:
            if re.search(pattern, normalized_key, re.IGNORECASE):
                combo = self._find_by_niveau(niveau1, niveau2)
                if combo:
                    self.match_stats['anchor_niveau'] += 1
                    return combo, 'anchor_niveau'

        # Step 4: Fuzzy match on candidates
        candidates = self.index.get_candidates(normalized_key)

        best_score = 0
        best_result = None

        for candidate_key in candidates:
            score = token_set_ratio(normalized_key, candidate_key)
            if score >= 90 and score > best_score:
                result = self.index.get_exact(candidate_key)
                if result:
                    best_score = score
                    best_result = result

        if best_result:
            self.match_stats['fuzzy'] += 1
            return best_result, 'fuzzy'

        # Step 5: Prefix/subterm fallback
        for candidate_key in candidates:
            if len(normalized_key) >= 4 and len(candidate_key) >= 4:
                if prefix_match(normalized_key, candidate_key) or subterm_match(normalized_key, candidate_key):
                    result = self.index.get_exact(candidate_key)
                    if result:
                        self.match_stats['prefix'] += 1
                        return result, 'prefix'

        self.match_stats['unmatched'] += 1
        return None, 'unmatched'
