# Mapping Tool

Automatische mapping van grootboekrekeningen (WV/Balans) en taken voor nieuwe klanten op basis van historische mappings van alle bestaande klanten.

## Werking

1. **Brondata laden**: het model leest een CSV met alle bestaande mappings van alle klanten (de "alle_klanten" exports uit de instellingen-app)
2. **Normalisatie**: rubrieken/taken worden genormaliseerd (lowercase, interpunctie verwijderen, afkortingen uitbreiden, typo's corrigeren)
3. **Matching** via een cascade van methoden:
   - **Exact match**: genormaliseerde rubriek komt exact overeen met een bestaande mapping
   - **Anchor match**: regex-patronen voor bekende categorieen (bijv. `wga` -> Sociale lasten, `doorbelasting` -> Doorbelastingen)
   - **Fuzzy match**: token set ratio >= 90% tegen alle kandidaten
   - **Prefix/subterm**: als de ene term een prefix of subset is van de andere
4. **Kwaliteitsvalidatie**: na matching worden resultaten gevalideerd tegen geldige combinaties
5. **Output**: verrijkt CSV-bestand met CoA_code, Niveau1, Niveau2 (of Taakgroepcode, Taakgroep)

## Mapping types

| Type | Bronbestand | Doelbestand | Output kolommen |
|------|-------------|-------------|-----------------|
| WV (Winst & Verlies) | `1000_export_WV_rubrieken_alle_klanten_*.csv` | `<klant>_export_WV_rubrieken_*.csv` | CoA_code, Niveau1, Niveau2 |
| Balans | `1000_export_Balans_rubrieken_alle_klanten_*.csv` | `<klant>_export_Balans_rubrieken_*.csv` | CoA_code, Niveau1, Niveau2 |
| Taken | `1000_export_Taken_alle_klanten_*.csv` | `<klant>_export_Taken_*.csv` | Taakgroepcode, Taakgroep |

## Workflow nieuwe klant mappen

### Stap 1: Bronbestanden controleren

Zorg dat in `generated_mapping_files/` de volgende bestanden staan:

- Nieuwste `1000_export_WV_rubrieken_alle_klanten_*.csv`
- Nieuwste `1000_export_Balans_rubrieken_alle_klanten_*.csv`
- Nieuwste `1000_export_Taken_alle_klanten_*.csv`
- De 3 klant-CSVs: `<klant>_export_WV_rubrieken_*.csv`, `<klant>_export_Balans_rubrieken_*.csv`, `<klant>_export_Taken_*.csv`

### Stap 2: Vorige klant afvoeren

**Voordat je begint:** verplaats ALLE bestanden van de vorige klant naar de GEDAAN-map. Dit geldt voor:

- `generated_mapping_files/` — de input CSVs (`<klant>_export_*.csv`)
- `CoA_mappings/` — de WV output
- `CoA_mappings_balans/` — de Balans output
- `Taken_mappings/` — de Taken output
- Eventuele `_unmatched` bestanden van eerdere runs

```
NotificaRAAS/
  GEDAAN (afvoeren uit mappings mappen)/   # Afgeronde klant-exports + outputs
```

De `1000_`-bronbestanden (alle_klanten) blijven ALTIJD staan in `generated_mapping_files/`.

### Stap 3: Mapping uitvoeren

Start de Streamlit app:

```bash
pip install -r requirements.txt
streamlit run app.py
```

De app draait op `http://localhost:8501`.

Per mapping type (WV, Balans, Taken):

1. Selecteer het mapping type in de sidebar
2. Selecteer het nieuwste `1000_*_alle_klanten_*` bronbestand
3. Selecteer het klant-doelbestand
4. Klik "Start Mapping"
5. Controleer fill rate (doel: >= 90%)
6. Review unmatched items en low-confidence matches
7. Sla op naar output directory

### Stap 4: Upload naar instellingen-app

Upload de gegenereerde bestanden via de instellingen-app (app.notifica.nl):

| Bestand | Upload type |
|---------|------------|
| WV output | `coa-mapping` |
| Balans output | `coa-balans-mapping` |
| Taken output | `taken-mapping` |

**Let op:** WV en Balans NOOIT door elkaar uploaden. Dezelfde CoA_code verwijst naar andere Niveau-waarden per type.

### Stap 5: Klant afvoeren

Verplaats ALLE bestanden van deze klant naar de GEDAAN-map:

- Input CSVs uit `generated_mapping_files/`
- Output CSVs uit `CoA_mappings/`, `CoA_mappings_balans/`, `Taken_mappings/`
- Eventuele `_unmatched` bestanden

Pas daarna de volgende klant starten.

## Kwaliteitsanalyse (quality.py)

De tool bevat een kwaliteitsmodule die inconsistenties in mapping bestanden detecteert. Beschikbaar via het "Kwaliteitsrapport" tabblad in de Streamlit app.

### Analyses

| Analyse | Wat het detecteert |
| ------- | ----------------- |
| **Code-reeks consistentie** | Rubrieken in dezelfde nummerreeks (bijv. 334x) waar 1 afwijkt van de meerderheid |
| **Naam-groep consistentie** | Rubrieken met dezelfde eerste 2 woorden maar verschillende classificatie |
| **Duplicaten** | Rubrieken die na normalisatie dezelfde key opleveren maar naar verschillende (Niveau1, Niveau2) wijzen |
| **Semantische checks** | Rubrieken waar de naam niet past bij de classificatie (bijv. "inkoop" niet bij "Directe kosten") |

### Semantische regels

**WV:**

- `inkoop` -> Directe kosten
- `omzet` -> Omzet
- `salaris`, `pensioen` -> Personeelkosten
- `afschrijving` -> Afschrijving
- `verzekering` -> Overige bedrijfskosten of Personeelkosten
- `huur` -> Overige bedrijfskosten
- `rente`, `interest` -> Financiele Baten en Lasten

**Balans:**

- `bank` -> Vlottende Activa
- `btw` -> Kortlopende schulden
- `voorziening` -> Voorzieningen
- `kapitaal` -> Eigen vermogen

## Validatie (validation.py)

Hulpmodule voor validatie van mapping-acties:

- **validate_coa_combo**: controleer of een (Niveau1, Niveau2) combinatie geldig is
- **get_valid_niveau2_for_niveau1**: cascading dropdown - welke Niveau2 opties horen bij een Niveau1
- **validate_bulk_rows**: valideer een lijst rijen voor bulk import/correctie
- **detect_duplicates**: vind duplicate rijen op basis van key kolommen

## Configuratie

In `app.py` staat het `DATA_BASE_PATH` dat verwijst naar de SharePoint-map met alle mapping-bestanden:

```
NotificaRAAS/
  generated_mapping_files/                 # Input: alle export CSVs (1000_ en klant-bestanden)
  CoA_mappings/                            # Output: WV mappings
  CoA_mappings_balans/                     # Output: Balans mappings
  Taken_mappings/                          # Output: Taken mappings
  learning_data/                           # Self-learning data (correcties uit Review)
  GEDAAN (afvoeren uit mappings mappen)/   # Afgeronde klant-exports
```

Pad configureerbaar via `.env`:

```
DATA_BASE_PATH=C:\Users\tobia\OneDrive - Notifica B.V\Documenten - Sharepoint Notifica intern\102. Klantmappen\0000 - NotificaRAAS
```

## Architectuur

```
mappingtool/
  app.py                    # Streamlit UI (mapping, kwaliteitsrapport, review, learning dashboard)
  requirements.txt
  src/
    normalization.py        # Normalisatie (afkortingen, typos, synoniemen)
    matching.py             # Matching algoritmen (exact, anchor, fuzzy, prefix)
    wv_balans_mapper.py     # WV & Balans mapper (met harde validatie tegen geldige combinaties)
    taken_mapper.py         # Taken mapper
    learning.py             # Self-learning module (correcties opslaan en hergebruiken)
    quality.py              # Kwaliteitsanalyse (inconsistenties, duplicaten, semantische checks)
    validation.py           # Validatie (combo-checks, cascading dropdowns, bulk validatie)
    utils.py                # CSV I/O helpers (delimiter detectie, output formatting)
```

## Streamlit pagina's

| Pagina | Functie |
| ------ | ------- |
| **Mapping Tool** | Hoofdpagina: selecteer bestanden, voer mapping uit, bekijk resultaten, sla op |
| **Kwaliteitsrapport** | Analyseer bronbestand op inconsistenties en afwijkingen |
| **Review & Correcties** | Bekijk en corrigeer individuele matches (low confidence, unmatched) |
| **Learning Dashboard** | Overzicht van geleerde mappings uit eerdere correcties |
| **Instellingen** | Configuratie en data paden |
