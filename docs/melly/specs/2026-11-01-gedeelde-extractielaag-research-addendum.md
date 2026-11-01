# Addendum: research op de gedeelde extractielaag (spec §9, fase 3)

- Datum: 2026-11-01 · Branch: `c4/shared-extraction-layer`
- **Status:** beslispunten A–E genomen (rij 90–92, 94–95); fase-3-plan, implementatie en providerrun nog niet goedgekeurd
- Hoort bij: [2026-11-01-gedeelde-extractielaag-design.md](2026-11-01-gedeelde-extractielaag-design.md) §9 en §11.3; besluitenlog rij 76, 81, 86
- Fase 1 en 2 (laag en C4) zijn gebouwd in `chunkhound/services/extraction/` en `chunkhound/code_mapper/c4/documented.py`

## 1. Wat dit addendum moet beslissen

Spec §9 legt het contract vast: research levert zijn clusters aan als bundels, met echte regelnummers, zonder persistente opslag, en met ongewijzigd foutgedrag. Bij het nalezen van de researchcode kwamen vijf punten naar voren die de spec nog niet beslist. Die staan hieronder, elk met een aanbeveling.

## 2. Feiten uit de code

| # | Feit | Bron |
|---|---|---|
| F1 | Feitextractie gebruikt `llm.complete` (vrije tekst) met tolerant JSON-parsen, niet `complete_structured_typed`. Ondersteunt een provider geen gestructureerde uitvoer, dan werkt research vandaag toch. | `evidence_ledger/extractor.py:301–309`, `_extract_json_array` |
| F2 | Gestructureerde uitvoer is per provider een capaciteit; sommige providers hebben die standaard niet. | `core/config/provider_registry.py`, `llm_config.py` (`supports_structured_outputs`) |
| F3 | Mislukt de aanroep voor een cluster, dan geeft research een lege ledger terug en gaat het verder. Er is geen herhaling en geen fatale fout. | `extractor.py:306–309` |
| F4 | Clusters zijn begrensd op 15.000–50.000 tokens volgens `estimate_tokens` (ongeveer 60.000–200.000 tekens). De laag heeft een doelgrootte van 150.000 tekens, inclusief overhead. | `clustered_extractor.py:29–30`; `budget.py` |
| F5 | Het aantal feiten per cluster is `max(3, tokens × 25 / 100.000)`; het uitvoerbudget is 8.000 tokens per cluster. | `clustered_extractor.py:33–34,115–124`; `extractor.py:26` |
| F6 | De inhoud van een bestand is óf het hele bestand, óf indexstukken met `\n\n...\n\n` ertussen. Bij een overschreden budget wordt afgekapt op tekens, midden in een regel. Decodering gebruikt `errors="ignore"`. | `file_reader.py:98–190` |
| F7 | Feiten kunnen een URL en een sectie hebben in plaats van regels (webbronnen). `FactEntry.generate_id` gebruikt de regels of de sectie in de id. | `extractor.py:180–230`; `models.py:53–103` |
| F8 | Regelnummers van feiten komen terug in de bronverwijzing `pad:start-eind` van de ledger, en daarmee in de synthese. | `ledger.py:478–479,772–822` |

## 3. Voorstellen per beslispunt

### A. Aanroepvorm: gestructureerd of tekst (F1, F2)

De laag kent nu alleen `StructuredCall`. Zou research overstappen op gestructureerde uitvoer, dan breekt research bij providers zonder die capaciteit.

**Besluit (rij 90):** de laag krijgt een tweede adapter, `TextCall`. Het extractiedoel levert dan een `parse(text) -> dict[id, part]`. Een tekst die niet te parsen is, telt als onleesbaar en leidt tot halveren. Bundelen, budget en regelvertaling blijven gelijk, en research blijft op elke provider werken.

### B. Clustergrootte tegenover de doelgrootte van de laag (F4)

Een cluster van 50.000 tokens is ongeveer 200.000 tekens. Dat is groter dan de doelgrootte van 150.000 tekens. De laag zou zulke clusters vóór verzending halveren, wat meer aanroepen geeft dan nu.

**Besluit (rij 91):** research krijgt een eigen doelgrootte per extractiedoel. Die mag de clustergrens volgen, maar nooit boven de opgegeven invoerlimiet van de provider uitkomen. Voor C4 verandert er niets. Halveert de laag toch een cluster, bijvoorbeeld bij een lage limiet, dan verdeelt research het feitenquotum naar verhouding.

### C. Bronnen zonder regels (F7)

Research krijgt zijn invoer altijd als bestanden: `file_reader` leest uit de index, en websearch schrijft opgehaalde pagina's naar tijdelijke bestanden die tijdelijk worden geïndexeerd (`mcp_server/tools.py:872`). Een URL of sectie komt alleen voor in de *uitvoer*, wanneer het model een feit zo lokaliseert.

**Besluit (rij 92):** alle researchinvoer gaat via de laag; clusters worden niet gesplitst. Het researchdoel accepteert ook feiten met een sectie of URL. Zo'n feit krijgt het pad van zijn fragment, zonder regelbereik, net als nu.

### D. Foutgedrag (F3)

De laag geeft per fragment `Failed` terug, en werpt fatale fouten op, zoals een invoerweigering.

**Besluit (rij 94):**
- Mislukte fragmenten krijgen samen één herstelpoging, nadat de overige clusters klaar zijn.
- Mislukken ze daarna nog, dan gaat research door zonder die feiten. Het aantal ontbrekende fragmenten komt in de metadata van het researchresultaat en in het log. Zo gaan er geen feiten meer stil verloren.
- Een invoerweigering blijft ook voor research een fatale configuratiefout.
- Extra aanroepen komen er alleen bij mislukkingen.

### E. Invoeromzetting en decodering (F6)

Alle huidige verkenningsstrategieën lezen met `max_tokens=None` (`wide_coverage_strategy.py:183`, `parallel_strategy.py:248`, `bfs_exploration_strategy.py:501`). Afkappen midden in een regel komt in de praktijk dus niet voor. Wel ziet het model nu geen regelnummers, en bij grote bestanden losse stukken met `...` ertussen.

**Besluit (rij 95):**
- Een heel bestand wordt bereik `1..n`. Grote bestanden worden de uitgebreide indexstukken (natuurlijke grenzen), waarbij overlap wordt samengevoegd.
- Decodering blijft `errors="ignore"`.
- Het ongebruikte afkappen op tekens wordt afkappen op een regelgrens, voor het geval een strategie later een totaalbudget meegeeft.
- Voor de huidige strategieën verandert alleen dat het model echte regelnummers ziet.

## 4. Gevolgen

| Onderdeel | Gevolg |
|---|---|
| Regelnummers | worden echt (F8), en daarmee worden de bronverwijzingen in `code_research` betrouwbaarder |
| Fact-id's | veranderen, omdat ze de regels bevatten (F7). Bestaande ledgers worden niet bewaard, dus geen migratie. |
| Kosten en kwaliteit | niet gemeten; acceptatie vraagt een vergelijking op vaste vragen (spec §10.12), en dat is een providerrun met aparte goedkeuring |
| Uitvoerbudget | blijft 8.000 tokens per researchbundel, via `max_completion_tokens` van het doel |

## 5. Acceptatie (aanvulling op spec §10.12)

1. Elke `FactEntry` met een regelbereik valt binnen een aangeleverd bereik.
2. Met een provider zonder gestructureerde uitvoer extraheert research nog steeds feiten. Getest met een nep op de providergrens die alleen `complete` ondersteunt.
3. Een mislukt fragment krijgt één herstelpoging. Blijft het mislukken, dan levert het geen feiten en geen fatale fout op, maar het telt mee in de metadata. Een invoerweigering is fataal.
4. Bij een opgegeven totaalbudget wordt afgekapt op een regelgrens; zonder budget verandert de geselecteerde inhoud niet.
5. Bestaande research- en MCP-tests blijven groen.
6. Kwaliteitsvergelijking op vaste vragen, met aparte goedkeuring.

## 6. Open punten

- Implementatieplan voor fase 3, ter goedkeuring.
- Kwaliteitsvergelijking op vaste vragen (providerrun) met aparte goedkeuring.
