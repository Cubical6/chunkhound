# Spec deel B: containers per proces (concept, nog niet bouwbaar)

- Datum: 2026-11-04 · Branch: `c4/shared-extraction-layer`
- **Status:** werkdocument. Dit bevat het ontwerp en de open reviewbevindingen, zodat er niets verloren gaat. Het wordt pas herzien na deel A en de echte maprun daarvan. Niets hiervan is goedgekeurd.
- Basis: [deel A](2026-11-03-omap-producent-design.md). Besluitenlog: de rijen "Containers per proces", "LikeC4", "Gecombineerde oplossing" en "D1" in [2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md).
- Prototypes (niet gevolgd, lokaal): `.scratch/c4-processes-research/`

## 1. Doel

C4 stelt dat *"all components inside a container execute in the same process space"*. ChunkHound draait als meerdere processen vanuit één codebase. Deel B maakt daarom containers per proces en plaatst componenten per proces, zonder extra modelaanroepen.

## 2. Ontwerp tot nu toe

**Begrippen.** Code-eenheid: een geselecteerd manifest; hierop draaien groepen, merge, titels en vergrendelde componenten. Procescontainer: een runtimegrens; alleen deze verschijnen als `container` in het contract.

**Herkennen zonder model:** startpunten uit `[project.scripts]`, `bin`, `[[bin]]` en Go-`main`; `Dockerfile`, `Procfile` en compose als het commando naar een bestand in de scope leidt; zelf gestarte processen via de commandokeuze (`daemon/discovery.py:1069`, `main.py:372`). Procespools blijven binnen hun ouder.

**Beslissen met `classify`:** langlopende subcommando's, gesynchroniseerde zelfstarts en andere processtarts (`process`: `yes`/`no`); commandotakken die een andere ingang lazy importeren (`mode`: `thin_client`/`full`/`no`). Een proces met een `thin_client`-tak en een `full`-tak wordt twee containers. Niet vast te stellen: geen splitsing, één container en een rapportregel.

**Plaatsing:** bereikbaar vanaf de startbestanden via verwijzingen met status `counts`, plus FFI-, crate- en Go-packagekoppelingen. Een component komt in een proces als minstens één bestand bereikbaar is; de kopie krijgt alleen die bestanden.

**Contract:** één kopie per proces, id `<component-id>@<container-slug>`, de omschrijving vermeldt `Gedeeld met …`, en een optioneel veld `shared_id`. Intern blijft één component; `identity._overlaps` gaat uit van één component per bestand, dus kopieën ontstaan ná de identiteitsstap.

**Eén component per bestand** wordt "per container". Dat wijzigt AutoDoc-besluitenlog rij 13 en AutoDoc-spec r. 23.

**AutoDoc:**
- `shared_id` in `model.py` en `loader.py`; tag `#gedeeld`, stijl en `notation` in de schrijver;
- `coverage.py:45–67`: één link per `shared_id`, naar de eerste kopie; elke container telt mee;
- `site_data.py` (rond regel 108): zoekresultaten ontdubbelen;
- `likec4_writer.py:306–310`: alleen `exclude`-regels voor relaties waarvan beide eindpunten in de view projecteren. Dit kan ook los eerder.

**Niet doen:** groepen binnen een containergrens (blijven leeg), samengevoegde focusview (tot 15.107 pixels breed), deployment-views als oplossing voor de modi (C4 toont daar geen componenten, en `with`-overrides werken daar niet in de fork).

**Bevestigd door `chunkhound research` en code:** de proxy is transport, de daemon doet het werk, directe stdio en HTTP draaien de engine zelf, Code Mapper en AutoDoc hebben alleen een CLI-pad.

## 3. Open bevindingen uit de review

Elk hiervan moet opgelost zijn voordat deze spec bouwbaar is.

### Kritiek

1. **Geen interne vorm.** `ElementKind`, `C4Evidence` en `ScopeLock` kunnen processen en plaatsing niet opslaan. Processen als interne containers verhogen het aantal titelaanroepen (`pipeline.py:408`) en views (`summaries.py:95`). Relaties die eindigen op een gesplitste eenheid hebben geen afbeelding (`assemble.py:154, 265`). Richting: `C4Evidence.processes` met sleutel, id, naam, omschrijving, startpunten, bereikbare bestanden en pijlen tussen processen, plus een tabel voor relatie-eindpunten.
2. **Procesgegevens overleven een run zonder merge niet.** `merge_container` doet geen aanroep als niets wacht (`merge.py:279`). Richting: `processes: {sleutel: {id, naam, omschrijving}}` en de pijlen in het lockbestand, en een vaste terugvalnaam uit het script of de rol.
3. **Herkenning raakt componenten.** Processleutels in de merge-prompt kunnen namen en indeling in de eerste run beïnvloeden. Richting: processen benoemen buiten de componentbeslissing.
4. **Tijdelijke classificatiefout verandert id's.** `_default` geeft "nee" (`classify.py:64–70`), dus het proces lijkt verwijderd en krijgt een nieuwe id. Richting: geen tombstone bij een terugval, en het vastgelegde proces behouden.

### Belangrijk

5. **Proxy lijkt te groot.** Gemeten: de proxy bereikt 189 bestanden, stdio 287, en 182 overlappen. `chunkhound/__init__.py:17–24` importeert `database` en `parser` alleen in `__getattr__`, maar de scan telt ze. Richting: `__getattr__`-imports uitsluiten, en een harde controle dat de proxy geen parsers of DuckDB bevat.
6. **Extra koppelingen in `references.py`** zouden relaties en verzonnen citaten maken (`assemble.py:206–221`). Richting: een aparte plaatsingsgraaf.
7. **`classify`-aansluiting.** Sleutels (`_classification_items` ontdubbelt op sleutel, `pipeline.py:161`), cache-invalidatie (`_known` negeert gewijzigde feiten) en de volgorde tegenover `accepted` en `_scan` zijn ongedefinieerd. Een `Procfile` onder een niet-geselecteerd manifest heeft geen eenheid.
8. **Sleutel instabiel.** `#<rol>` alleen bij een tweede proces verandert de sleutel van het eerste. Richting: altijd een rol bij entries via de commandokeuze.
9. **Samenvoegregel klopt niet.** `chunkhound-mcp` start stdio, `chunkhound mcp` standaard de proxy (`detector.py:1165–1210` gebruikt een andere regel).
10. **Meerdere manifesten.** Overschrijdt bereikbaarheid eenheden? Relaties tussen niet-gesplitste eenheden passen nu nergens.
11. **Kopieën naar externe elementen** slaan het bereikbaarheidsfilter over, waardoor een kopie een afhankelijkheid kan claimen die alleen een onbereikbaar bestand heeft.
12. **Samengevoegde labels op kopieën** vuren bijna nooit. Richting: weglaten; `likec4_writer.py:49–70` valt al terug.
13. **Herkenning buiten Python** is beperkt: de commandokeuze werkt alleen voor Python. Overweeg uitstel.

### Bekende meetwaarden, om opnieuw te toetsen

- Met één MCP-container: 47–50 componenten, 166–193 relaties, 61–64 views. Met minder `exclude`-regels: 0,56–0,61 MB DSL en 3,1–3,3 s build.
- Herkenning: 22 vormen, 52 processen, 0 onjuist, 3 gemist. **Optimistisch**, want de regels zijn op dezelfde projecten bijgesteld.
- De MCP-splitsing is nog niet in de plaatsing gemeten.

## 4. Eerste stap

Na deel A en de echte maprun: **de MCP-splitsing op deze repository bewijzen**, met de harde controle uit bevinding 5. Lukt dat niet, dan blijft het één MCP-container met de modi in de omschrijving.
