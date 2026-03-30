# Mapping Tool

Automatische mapping van grootboekrekeningen (WV/Balans) en taken voor nieuwe klanten op basis van historische mappings van alle bestaande klanten.

## Kernprincipe

**Het mappingbestand (1000_) is ALTIJD leidend.**

- Elke output-combinatie (CoA_code + Niveau1 + Niveau2, of Taakgroepcode + Taakgroep) moet **exact** voorkomen in het mappingbestand.
- Er worden nooit nieuwe of afgeleide combinaties aangemaakt.
- CoA_code → Niveau1 → Niveau2 is een **vaste combinatie** (1-op-1). De code bepaalt altijd dezelfde Niveau1 en Niveau2.
- WV en Balans zijn **strikt gescheiden**: dezelfde CoA_code (bijv. 101001) kan in WV "Omzet | Omzet" zijn en in Balans "Immateriele Vaste Activa | Goodwill". Nooit mengen.

## Vaste combinaties (uit 1000-bronbestanden)

| Type | Aantal vaste combinaties |
|------|--------------------------|
| WV (Winst & Verlies) | 65 CoA_code → Niveau1 → Niveau2 |
| Balans | 25 CoA_code → Niveau1 → Niveau2 |
| Taken | 8 Taakgroepcode → Taakgroep |

### Overlap CoA_codes WV vs Balans

Deze codes bestaan in BEIDE types maar met ANDERE Niveau-waarden:

| CoA_code | WV | Balans |
|----------|-------|-------|
| 101001 | Omzet / Omzet | Immateriele Vaste Activa / Goodwill |
| 102001 | Directe kosten / Materiaal | Vaste Activa / Vaste Activa |
| 112001 | Financiele Baten en Lasten / Financiele Baten en Lasten | Langlopende schulden / Schulden Achtergesteld |
| 112002 | Financiele Baten en Lasten / Doorbelaste kosten en opbrengsten | Langlopende schulden / Schulden Bank |
| 112003 | Financiele Baten en Lasten / Overige bijzondere baten en lasten | Langlopende schulden / Overige langlopende schulden |

## Mapping types

| Type | Bronbestand | Doelbestand | Output kolommen |
|------|-------------|-------------|-----------------|
| WV | `1000_export_WV_rubrieken_alle_klanten_*.csv` | `<klant>_export_WV_rubrieken_*.csv` | CoA_code, Niveau1, Niveau2 |
| Balans | `1000_export_Balans_rubrieken_alle_klanten_*.csv` | `<klant>_export_Balans_rubrieken_*.csv` | CoA_code, Niveau1, Niveau2 |
| Taken | `1000_export_Taken_alle_klanten_*.csv` | `<klant>_export_Taken_*.csv` | Taakgroepcode, Taakgroep |

## Matching-strategie

Doel is 100% fill rate. De tool probeert alles te mappen via een cascade van methoden, van zeker naar beredeneerd:

### Stap 1: Exact match
Genormaliseerde rubriek komt exact overeen met een rubriek uit het mappingbestand. Bij meerdere combinaties voor dezelfde rubriek geldt de selectiehierarchie:
1. Meest voorkomende combinatie voor die rubriek
2. Hoogste globale frequentie
3. Laagste numerieke CoA_code

### Stap 2: Anchor match (regex-patronen)
Bekende patronen die altijd naar dezelfde categorie verwijzen. Gescheiden lijsten voor WV en Balans. Voorbeelden:

**WV anchors:**
- `wga|wia|svw|sociaal fonds` → Personeelkosten / Sociale lasten
- `door te belasten|doorbelasting` → Overige bedrijfskosten / Doorbelastingen
- `bestuursvergoeding|management fee` → Overige bedrijfskosten / Management Fee
- `ziekteverzuim|ziekengeld` → Personeelkosten / Sociale lasten

**Balans anchors:**
- `rabo|abn|ing` → Vlottende Activa / Liquide Middelen
- `\brc\b` (rekening courant) → Kortlopende schulden / Schulden aan groepsmaatschappijen
- `\bbtw\b|\bob\b` → Kortlopende schulden / Belastingen en premies
- `borgstorting` → Vlottende Activa / Overige Vorderingen
- `straat|weg|laan|pand` → Vaste Activa / Vaste Activa

**Elke anchor wordt gevalideerd**: de bijbehorende CoA_code + Niveau1 + Niveau2 moet exact in het mappingbestand staan. Zo niet, wordt de anchor overgeslagen.

### Stap 3: Fuzzy match
Token set ratio >= 90% tegen alle kandidaat-rubrieken die tokens delen met de doelrubriek.

### Stap 4: Prefix/subterm match
Als de ene term een prefix of volledige subset is van de andere.

### Harde validatie
Na elke match (ongeacht methode) wordt de resultaat-combinatie gevalideerd tegen de set van geldige combinaties uit het mappingbestand. Als de combinatie niet bestaat, wordt het resultaat **leeg** — er wordt nooit een ongeldige combinatie in de output gezet.

## Normalisatie

Rubrieken worden genormaliseerd voordat ze gematcht worden. Beide kanten (mapping en doel) doorlopen dezelfde normalisatie, zodat exact matching werkt ondanks schrijfverschillen.

### Stappen
1. Lowercase
2. Trim
3. Numeriek prefix verwijderen (bijv. "4100 Omzet" → "Omzet")
4. Interpunctie → spatie (punten, slashes, streepjes worden spaties)
5. Meervoudige spaties → enkele spatie
6. Synoniemen en afkortingen toepassen (zie hieronder)

### Afkortingen (automatisch uitgebreid)

| Afkorting | Wordt | Voorbeeld |
|-----------|-------|-----------|
| `doorber` | `doorbelasting` | Doorber. Kn → doorbelasting |
| `pers kn` | `personeelskosten` | Pers.kn. gerichte vrijstelling → personeelskosten gerichte vrijstelling |
| `sal kn` | `salariskosten` | Sal.Kn Bev → salariskosten bev |
| `onderh` | `onderhoud` | Onderh.invent. → onderhoud invent |
| `reisk` | `reiskosten` | Reisk. woon-werk → reiskosten woon werk |
| `uitbet` | `uitbetaling` | Daggeld uitbet. → daggeld uitbetaling |
| `admie` | `administratie` | Order-/admie-kosten → order administratie |
| `soc` | `sociaal` | Soc.fonds → sociaal fonds |
| `inkasso` | `incasso` | Inkasso kosten → incasso |
| `vzk` | `verzekering` | Ziekengeldvzk → ziekengeld verzekering |
| `voorz` | `voorziening` | Voorz.Vak.dag → voorziening vak dag |
| `vso` | `vaststellingsovereenkomst` | Afrekening VSO → afrekening vaststellingsovereenkomst |

### Typo-correcties

| Fout | Correctie |
|------|-----------|
| `verrzekering` | `verzekering` |
| `servcie` | `service` |

### Synoniemen

| Patroon | Wordt |
|---------|-------|
| `verkopen` / `verkoop` | `omzet` |
| `afschr.` / `afschrijvingen` | `afschrijving` |
| `wkr` | `werkkostenregeling` |
| `svw` | `sociale verzekeringswet` |
| `kosten` | *(verwijderd)* |
| `kn` | *(verwijderd, afkorting voor kosten)* |

## Output specificaties

| Eigenschap | Waarde |
|------------|--------|
| Delimiter | `;` (puntkomma) |
| Encoding | UTF-8 met BOM |
| Line endings | `\r\n` (CRLF) |
| Quoting | Minimaal (alleen waar nodig) |
| CoA_code formaat | String, nooit eindigend op `.0` |
| Bestandsnaam | `<basisnaam>_YYYY-MM-DD.csv` |
| Rij-telling | Exact gelijk aan input (geen dedup, geen overslaan) |
| Geen match | Lege string (nooit gokken buiten geldige combinaties) |
| Kolommen | Alle originele kolommen + 3 verrijkingskolommen achteraan |
| Unmatched bestand | Alleen aangemaakt als er unmatched items zijn |

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
    matching.py             # Matching algoritmen + anchor tabellen
    wv_balans_mapper.py     # WV & Balans mapper (met harde validatie)
    taken_mapper.py         # Taken mapper
    learning.py             # Self-learning module
    utils.py                # CSV I/O helpers
```

## Bulk upload in instellingen-app

De gegenereerde bestanden kunnen via de instellingen-app (app.notifica.nl) worden geupload:

| Bestand | Upload type |
|---------|------------|
| WV output | `coa-mapping` |
| Balans output | `coa-balans-mapping` |
| Taken output | `taken-mapping` |

De API leest `RegelKey` + `CoA_code` (of `Taakgroepcode`) uit het bestand. Niveau1/Niveau2 worden automatisch afgeleid uit de CoA_code via de vaste combinatie-tabel in de database.

**Let op:** WV en Balans NOOIT door elkaar uploaden. Dezelfde CoA_code verwijst naar andere Niveau-waarden per type.
