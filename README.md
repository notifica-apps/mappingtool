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
4. **Output**: verrijkt CSV-bestand met CoA_code, Niveau1, Niveau2 (of Taakgroepcode, Taakgroep)

## Mapping types

| Type | Bronbestand | Doelbestand | Output kolommen |
|------|-------------|-------------|-----------------|
| WV (Winst & Verlies) | `1000_export_WV_rubrieken_alle_klanten_*.csv` | `<klant>_export_WV_rubrieken_*.csv` | CoA_code, Niveau1, Niveau2 |
| Balans | `1000_export_Balans_rubrieken_alle_klanten_*.csv` | `<klant>_export_Balans_rubrieken_*.csv` | CoA_code, Niveau1, Niveau2 |
| Taken | `1000_export_Taken_alle_klanten_*.csv` | `<klant>_export_Taken_*.csv` | Taakgroepcode, Taakgroep |

## Gebruik

```bash
pip install -r requirements.txt
streamlit run app.py
```

De app draait op `http://localhost:8501`.

### Configuratie

In `app.py` staat het `DATA_BASE_PATH` dat verwijst naar de SharePoint-map met alle mapping-bestanden:

```
NotificaRAAS/
  generated_mapping_files/   # Input: alle export CSVs
  CoA_mappings/              # Output: WV mappings
  CoA_mappings_balans/       # Output: Balans mappings
  Taken_mappings/            # Output: Taken mappings
  learning_data/             # Self-learning data
```

## Architectuur

```
mappingtool/
  app.py                    # Streamlit UI
  requirements.txt
  src/
    normalization.py        # Normalisatie (afkortingen, typos, synoniemen)
    matching.py             # Matching algoritmen (exact, anchor, fuzzy, prefix)
    wv_balans_mapper.py     # WV & Balans mapper + smoke tests
    taken_mapper.py         # Taken mapper
    learning.py             # Self-learning module
    utils.py                # CSV I/O helpers
```
