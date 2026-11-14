# PLAN: beslislaag en beslislog voor zoeken en onderzoek (stap 1)

- **Status:** goedgekeurd 2026-11-14. Commits blijven lokaal op `feat/decision-log`. Geeft geen toestemming voor een push, een merge naar `main` of een providerrun; fase 7 vraagt aparte toestemming.
- **Aanleiding:** onderzoek van 2026-11-14 naar decision models. De stop- en routeringsregels in het zoek- en onderzoekspad zijn vaste constanten, drie config-velden doen niets, en nergens wordt vastgelegd welke beslissing op welke invoer is genomen. Zonder die data kan een geleerde regel niet getraind en niet beoordeeld worden.

## Goal

De regels die bepalen wanneer multi-hop stopt en welke zoekstrategie draait, komen op één expliciete plek te staan en zijn instelbaar via de config-velden die daar al voor bestaan.

Daarnaast komt er een lokaal, opt-in beslislog (JSONL) dat per zoekopdracht en per onderzoeksrun de invoer, de genomen beslissingen en de uitkomst vastlegt. Dat log is de meet- en trainingsdata voor de vervolgstappen (router voor onderzoeksdiepte, geleerde stopregel).

Met de standaardinstellingen verandert het gedrag van zoeken en onderzoek niet.

## Context

- **Repo / worktree:** `/home/disorder/Projects/Github/chunkhound/.claude/worktrees/decision-log`
- **Branch:** `feat/decision-log`, basis lokale `main` op `03cbc080`. Baseer niets op `origin/main`.
- **Omgeving:** er zijn geen Rust-wijzigingen. De eerste `uv run` in de worktree installeert de vergrendelde `chunkhound-native`-wheel; `make dev` is niet nodig.
- **Projectregels:** lees `AGENTS.md`, met name MODIFICATION_RULES (geen `print()` in de MCP-server) en TESTING_PHILOSOPHY. Schrijf alleen contracttests.

### Huidige situatie (geverifieerd op `03cbc080`)

- **Stopregels multi-hop:** `chunkhound/services/search/multi_hop_strategy.py`.
  - Constanten op r. 31-37: `MIN_EXPANSION_CANDIDATES = 5`, `SCORE_DROP_THRESHOLD = 0.15`, `MIN_RELEVANCE_FLOOR = 0.3`.
  - De lus op r. 186-361 stopt om zeven redenen: tijdslimiet, resultaatlimiet, te weinig kandidaten met score > 0, geen nieuwe buren, rerank-fout, scoredaling van een gevolgd top-chunk, en minimale topscore onder de vloer.
  - Elke reden gaat alleen als `logger.debug` naar het log.
- **Dode config:** `chunkhound/core/config/research_config.py` r. 140-159 definieert `multi_hop_min_candidates`, `multi_hop_score_degradation` en `multi_hop_min_relevance`. Ze worden uit env geladen (r. 409-416) maar nergens gelezen.
- **Strategiekeuze:** `chunkhound/services/search_service.py` r. 107-122 kiest multi-hop als `force_strategy == "multi_hop"` of als de provider `supports_reranking()` heeft.
- **Config-doorgifte:** `chunkhound/registry/__init__.py` r. 467-471 geeft `config.research` door aan `SearchService`, en die aan `MultiHopStrategy`. De teststub `_StubResearchConfig` in `tests/test_multi_hop_semantic_search.py` heeft alleen `exhaustive_mode` en de twee `get_effective_*`-methoden.
- **Onderzoek:** `PluggableResearchService.deep_research` in `chunkhound/services/research/v1/pluggable_research_service.py` (r. 184) is het enige ingangspunt voor v1, v2 en v3. De keuze single-pass of map-reduce valt op r. 411.
- **LLM-beslissingen:** `filter_relevant_followups` in `chunkhound/services/research/v1/question_generator.py` (r. 398) en `_select_gaps_by_elbow` in `chunkhound/services/research/shared/gap_detection.py` (r. 733).
- **Bestaande analytics:** `chunkhound/core/analytics/recorder.py` wordt opgezet in `chunkhound/mcp_server/base.py` r. 112 en `chunkhound/api/cli/main.py` r. 308.
- **Bestaande tests:** `tests/test_multi_hop_semantic_search.py` heeft per stopreden een test (r. 305-534). `tests/test_multi_hop_metrics.py` meet recall@k en MRR.

## Besluiten

1. **Het beslislog staat los van de Rust-analytics.** De analytics-recorder is gebouwd voor upload naar S3, redigeert querytekst en heeft een vast schema in Rust. Het beslislog is alleen lokaal, bevat querytekst en heeft per ronde scores nodig. Er komt geen Rust-wijziging.
2. **Opt-in, standaard uit.** Nieuwe config-sectie `decision_log` met `enabled` (standaard `false`), `path` (standaard `<projectroot>/.chunkhound/decisions.jsonl`) en `max_size_mb` (standaard 50). Env-variabelen volgen het patroon van analytics: `CHUNKHOUND_DECISION_LOG__ENABLED`, `CHUNKHOUND_DECISION_LOG__PATH`, `CHUNKHOUND_DECISION_LOG__MAX_SIZE_MB`.
3. **Het log bevat de ruwe querytekst** en chunk-id's met scores, maar geen bestands- of chunkinhoud. Zonder querytekst kan er geen router op getraind worden. Het log wordt nooit geüpload.
4. **Eén record per zoekopdracht en één per onderzoeksrun.** Rondes staan als lijst in het record. Dat geeft één schrijfactie per opdracht en de rondes zijn vanzelf gegroepeerd.
5. **Procesbrede schrijver, geen doorgifte via constructors.** Een module met `configure(...)` en `record(event, payload)`, opgezet op dezelfde twee plekken als `build_recorder`. `record` is een no-op als het log uit staat. Een `contextvars`-trace-id koppelt de zoekrecords van een onderzoeksrun aan die run.
6. **Het log mag een opdracht nooit laten falen.** Elke fout bij schrijven wordt gevangen en gaat als `logger.debug` weg. Geen `print()`.
7. **Rotatie:** boven `max_size_mb` wordt het bestand hernoemd naar `decisions.jsonl.1` (één generatie) en begint een nieuw bestand.
8. **De stopregels worden een pure policy.** Nieuw bestand `chunkhound/services/search/multi_hop_policy.py` met een onveranderlijke `MultiHopPolicy` (de drie drempels) en een `StopReason`-enum. De policy doet geen I/O en kent geen provider. Dit is de plek waar in een latere stap een geleerde regel komt.
9. **`multi_hop_min_candidates` vervangt `MIN_EXPANSION_CANDIDATES` op alle vier de plekken** waar die constante nu staat: het aantal topkandidaten dat wordt uitgebreid, het minimum om door te gaan, het aantal gevolgde chunks en het venster voor de minimale topscore. Eén waarde voor alle vier houdt het gedrag gelijk bij de standaardwaarde 5.
10. **Ontbrekende config-attributen vallen terug op de huidige constanten.** `config=None` en de teststub moeten blijven werken zonder aanpassing.
11. **Schema-versie in elk record.** Veld `schema_version: 1`. Het schema staat in fase 6 beschreven in de docs en geldt vanaf dan als contract.

### Schema v1 (richtlijn voor fase 3-5)

Gemeenschappelijke velden: `schema_version`, `ts` (ISO 8601 UTC), `event`, `trace_id`, `parent_trace_id` (of `null`), `chunkhound_version`.

- **`multi_hop_search`:**
  - `query`, `page_size`, `has_path_filter`, `provider`, `model`
  - `strategy_reason` (`forced` of `provider_supports_reranking`)
  - `policy` (de drie drempels, tijdslimiet, resultaatlimiet, `exhaustive_mode`)
  - `initial` (`n_results`, `top_scores`)
  - `rounds`: lijst van `{round, n_new_candidates, n_total, top_scores, max_score_drop, min_top_score, elapsed_s}`
  - `stop_reason`, `n_rounds`, `n_candidates`, `n_returned`, `elapsed_s`
- **`single_hop_search`:** `query`, `page_size`, `has_path_filter`, `provider`, `model`, `strategy_reason` (`forced` of `no_reranker`), `n_returned`, `elapsed_s`.
- **`research_run`:** `query`, `algorithm`, `has_path_filter`, `is_follow_up`, `depth_reached`, `nodes_explored`, `chunks_analyzed`, `num_clusters`, `synthesis_mode` (`single_pass` of `map_reduce`), `answer_chars`, `llm_usage` (verschil van `LLMManager.get_usage_stats()` voor en na de run), `success`, `error_type`, `elapsed_s`.
- **`followup_filter`:** `n_candidates`, `n_kept`, `candidates` (vraagteksten), `kept` (indexen in `candidates`), `fallback`.
- **`gap_selection`:** `n_candidates`, `n_selected`, `scores` (aflopend), `elbow_index` (of `null`), `selected` (indexen in `scores`).

`top_scores` is steeds de top-N volgens `multi_hop_min_candidates`.

## Buiten scope

- Een decision model, een router of een geleerde stopregel. Dit plan levert alleen de laag en de data.
- Wijzigingen aan de Rust-analytics of aan `chunkhound_native`.
- Andere constanten (elbow-drempels, tokenbudgetten, chunkgroottes, `MAX_DEPTH`).
- Het veld `relevance_threshold`, dat volgens de inventarisatie ook ongebruikt is. Dat is niet nagelopen en krijgt een eigen issue.
- `CHANGELOG.md`: de release-notes-skill beheert die.

## Constraints (gelden voor elke fase)

- Wijzig alleen de bestanden uit de fase, tenzij het strikt nodig is; meld elk extra bestand in het rapport.
- Commit, push en start geen andere fases. Geen echte LLM-, embedding- of rerank-aanroepen en geen netwerk.
- Geen `print()` in MCP-servercode. Geen forward references in type-annotaties tenzij nodig.
- Houd de context klein: zoek met `rg`, lees alleen relevante regelbereiken, draai gerichte tests met `-q --tb=short` en stuur lange uitvoer door `| tail -n 40`.
- Draai niet de volledige testsuite; dat doet Claude.
- Draai na elke wijziging `uv run ruff check <gewijzigde bestanden>` en `uv run ruff format <gewijzigde bestanden>`.

## Final report format (elke fase)

Hooguit ~15 regels:
1. Gewijzigde bestanden (één regel per bestand, met een korte reden)
2. Gedraaide tests, met resultaat
3. Afwijkingen van het plan en open punten

---

## Phase 1: stoppolicy en config-koppeling
- [x] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** de stopregels van multi-hop staan in een pure policy en de drie bestaande config-velden sturen ze aan. Gedrag bij standaardwaarden is ongewijzigd.
- **Files:** `chunkhound/services/search/multi_hop_policy.py` (nieuw), `chunkhound/services/search/multi_hop_strategy.py`, `chunkhound/services/search_service.py`, `chunkhound/core/config/research_config.py`, `tests/test_multi_hop_semantic_search.py`
- **Steps:**
  1. Maak `multi_hop_policy.py` met `StopReason` (zeven waarden, zie Context), een frozen dataclass `MultiHopPolicy(min_candidates, score_drop_threshold, min_relevance_floor)` en een `from_config(config)` die per attribuut terugvalt op de huidige constanten (besluit 10).
  2. Geef de policy twee pure controles: één vóór de uitbreiding (tijd, resultaatlimiet, aantal kandidaten) en één na het reranken (scoredaling, relevantievloer). Beide geven een `StopReason` of `None` terug.
  3. Laat `MultiHopStrategy.search` de policy gebruiken in plaats van de constanten, op alle vier de plekken (besluit 9). Houd de bestaande `logger.debug`-regels.
  4. Verplaats de strategiekeuze uit `search_service.py` r. 107-122 naar een pure functie in `multi_hop_policy.py` die `(strategie, reden)` teruggeeft. Het gedrag blijft gelijk.
  5. Corrigeer de `description` van de drie velden in `research_config.py` zodat die beschrijft wat het veld nu doet.
  6. Voeg contracttests toe (zie acceptatiecriteria).
- **Acceptance criteria:**
  - Alle bestaande tests in `tests/test_multi_hop_semantic_search.py` en `tests/test_multi_hop_metrics.py` slagen zonder dat ze zijn aangepast.
  - Nieuwe test: met een hogere `multi_hop_score_degradation` stopt de score-drop-fixture niet meer op die ronde.
  - Nieuwe test: met een lagere `multi_hop_min_relevance` stopt de lage-vloer-fixture niet meer op de vloer.
  - Nieuwe test: `CHUNKHOUND_RESEARCH_MULTI_HOP_MIN_CANDIDATES` komt via `ResearchConfig` in de policy terecht.
  - De drie modulconstanten blijven bestaan als standaardwaarden; er is één bron voor elke standaardwaarde.
- **Verify:** `uv run pytest tests/test_multi_hop_semantic_search.py tests/test_multi_hop_metrics.py -q --tb=short | tail -n 40` en `uv run mypy chunkhound/services/search | tail -n 20`
- **Notes:** de standaardwaarden in `research_config.py` (5 / 0.15 / 0.3) zijn nu gelijk aan de constanten; houd dat zo. Wijzig de tijds- en resultaatlimiet niet, die lopen al via `get_effective_*`. Test de policy niet los van de zoekstrategie: de bestaande fixtures zijn het contract.

## Phase 2: beslislog-module en config
- [x] Done
- **Depends on:** none (mag parallel aan fase 1, in een eigen worktree)
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** een procesbrede, opt-in JSONL-schrijver met config, rotatie en trace-id's. Nog geen aanroepen vanuit zoeken of onderzoek.
- **Files:** `chunkhound/core/decision_log.py` (nieuw), `chunkhound/core/config/decision_log_config.py` (nieuw), `chunkhound/core/config/config.py`, `chunkhound/mcp_server/base.py`, `chunkhound/api/cli/main.py`, `tests/unit/test_decision_log.py` (nieuw)
- **Steps:**
  1. Maak `DecisionLogConfig` naar het voorbeeld van `AnalyticsConfig` (velden en env-variabelen uit besluit 2) en neem het op in `Config`, inclusief `load_from_env`.
  2. Maak `decision_log.py` met `configure(config, target_dir)`, `record(event, payload)`, `is_enabled()` en een contextmanager `trace()` die een nieuw `trace_id` zet en het vorige als `parent_trace_id` bewaart.
  3. `record` vult de gemeenschappelijke velden uit Schema v1 aan en schrijft één regel per aanroep in append-modus, met `json.dumps(..., default=str)`.
  4. Bouw de rotatie uit besluit 7 en de foutafhandeling uit besluit 6.
  5. Roep `configure` aan naast `build_recorder` in `mcp_server/base.py` (r. 112) en `api/cli/main.py` (r. 308).
- **Acceptance criteria:**
  - Log uit (standaard): `record` schrijft niets en maakt geen bestand of map aan.
  - Log aan: elke regel is geldige JSON met `schema_version`, `ts`, `event` en `trace_id`.
  - Een record binnen een geneste `trace()` draagt het buitenste trace-id als `parent_trace_id`.
  - Een niet-schrijfbaar pad laat `record` niet falen.
  - Boven `max_size_mb` bestaat `decisions.jsonl.1` en gaat het schrijven door in een nieuw bestand.
  - `CHUNKHOUND_DECISION_LOG__ENABLED=true` zet het log aan via `Config`.
- **Verify:** `uv run pytest tests/unit/test_decision_log.py tests/test_config_integration.py -q --tb=short | tail -n 40` en `uv run mypy chunkhound/core/decision_log.py chunkhound/core/config | tail -n 20`
- **Notes:** gebruik `tmp_path` in tests, nooit de echte `.chunkhound/`. De module mag geen import van `chunkhound_native` hebben. Geen achtergrondthread en geen buffer: de records zijn klein en er is er één per opdracht.

## Phase 3: zoekpad instrumenteren
- [x] Done
- **Depends on:** Phase 1, Phase 2
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** elke semantische zoekopdracht schrijft één `multi_hop_search`- of `single_hop_search`-record volgens Schema v1.
- **Files:** `chunkhound/services/search/multi_hop_strategy.py`, `chunkhound/services/search_service.py`, `tests/test_multi_hop_semantic_search.py`
- **Steps:**
  1. Verzamel in `MultiHopStrategy.search` per ronde de velden uit Schema v1 in een lokale lijst en schrijf na de lus één record.
  2. Leg de `stop_reason` vast met de `StopReason` uit fase 1, ook voor de paden die nu met een kale `break` eindigen (geen nieuwe buren, rerank-fout).
  3. Schrijf in `search_service.py` het `single_hop_search`-record en geef de reden van de strategiekeuze door aan het multi-hop-record.
  4. Sla het verzamelen over als `decision_log.is_enabled()` onwaar is, zodat een uitgeschakeld log geen werk kost.
- **Acceptance criteria:**
  - Voor elk van de bestaande stopreden-fixtures staat de verwachte `stop_reason` in het record.
  - `n_rounds` in het record is gelijk aan het aantal uitbreidingsrondes van de fixture.
  - De zoekresultaten en de paginering zijn identiek met het log aan en uit.
  - Met het log uit wordt er niets geschreven.
  - Het record bevat geen chunk- of bestandsinhoud.
- **Verify:** `uv run pytest tests/test_multi_hop_semantic_search.py tests/test_multi_hop_metrics.py tests/unit/test_decision_log.py -q --tb=short | tail -n 40`
- **Notes:** voeg de log-asserties toe als één geparametriseerde test over de bestaande fixtures, niet als kopie van elke test. Elke zoekopdracht opent een eigen `decision_log.trace()`. Binnen een onderzoeksrun krijgt het zoekrecord daardoor een eigen `trace_id` en het trace-id van de run als `parent_trace_id`; daarbuiten is `parent_trace_id` `null`.

## Phase 4: onderzoeksrun instrumenteren
- [x] Done
- **Depends on:** Phase 2
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** elke `deep_research`-aanroep schrijft één `research_run`-record, ook als de run faalt, en de zoekrecords binnen de run verwijzen ernaar.
- **Files:** `chunkhound/services/research/v1/pluggable_research_service.py`, `chunkhound/services/research/factory.py`, een bestaand of nieuw testbestand onder `tests/unit/research/`
- **Steps:**
  1. Open in `deep_research` (r. 184) een `decision_log.trace()` om de hele run.
  2. Geef de algoritmenaam (`v1`, `v2`, `v3`) vanuit de factory mee aan de service, zodat het record die kan vastleggen.
  3. Leg `num_clusters` en `synthesis_mode` vast op de plek van de keuze (r. 411).
  4. Schrijf het record in een `finally`, met `success`, `error_type`, `elapsed_s` en het verschil in `LLMManager.get_usage_stats()`.
- **Acceptance criteria:**
  - Een geslaagde run met nep-LLM en nep-embeddings schrijft precies één `research_run`-record met `algorithm`, `synthesis_mode` en `success: true`.
  - Een run die een uitzondering gooit, schrijft een record met `success: false` en het uitzonderingstype, en de uitzondering bereikt de aanroeper ongewijzigd.
  - Zoekrecords uit de run hebben het trace-id van de run als `parent_trace_id`.
  - Het antwoord en de metadata van `deep_research` zijn identiek met het log aan en uit.
- **Verify:** `uv run pytest tests/unit/research tests/unit/test_code_research_dispatch.py -q --tb=short | tail -n 40`
- **Notes:** hergebruik de nep-providers uit de bestaande tests in `tests/unit/research/`; bouw geen nieuwe. Als `get_usage_stats()` voor een provider geen tellers geeft, laat `llm_usage` dan leeg en meld dat in het rapport. Parallelle strategieën (v3) draaien in `asyncio.gather`; contextvars gaan mee naar de taken, controleer dat met de test.

## Phase 5: LLM-beslissingen in onderzoek loggen
- [x] Done
- **Depends on:** Phase 2
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** het filteren van vervolgvragen en het selecteren van gaps schrijven elk een record, als data voor het latere vervangen van deze utility-LLM-keuzes.
- **Files:** `chunkhound/services/research/v1/question_generator.py`, `chunkhound/services/research/shared/gap_detection.py`, een testbestand onder `tests/unit/research/`
- **Steps:**
  1. Schrijf in `filter_relevant_followups` (r. 398) een `followup_filter`-record met de kandidaten en de gekozen indexen.
  2. Schrijf in `_select_gaps_by_elbow` (r. 733) een `gap_selection`-record met de scores, de elbow-index en de gekozen indexen.
- **Acceptance criteria:**
  - Beide records verschijnen met de velden uit Schema v1 wanneer het log aan staat, en dragen het trace-id van de lopende run.
  - De teruggegeven vragen en gaps zijn identiek met het log aan en uit.
  - Het terugvalpad van het vraagfilter (LLM faalt of geeft ongeldige uitvoer) schrijft ook een record, met een veld `fallback: true`.
- **Verify:** `uv run pytest tests/unit/research -q --tb=short | tail -n 40`
- **Notes:** lees van `gap_detection.py` alleen r. 733-855; het bestand is groot. Verander niets aan de selectielogica zelf.

## Phase 6: documentatie (Claude, niet pi-bolt)
- [x] Done
- **Depends on:** Phase 1-5
- **Goal:** gebruikers vinden de drie multi-hop-velden en het beslislog in de docs, en het schema staat vast.
- **Files:** `site/src/pages/docs/configuration.md`
- **Steps:**
  1. Voeg de drie multi-hop-velden toe aan de tabel bij r. 673-674, met env-variabele en bereik.
  2. Voeg een sectie `decision_log` toe met de drie velden, de env-variabelen, de standaardlocatie en de rotatie.
  3. Beschrijf Schema v1 per event en vermeld dat het log querytekst bevat, lokaal blijft en nooit wordt geüpload.
- **Acceptance criteria:**
  - Elke env-variabele in de docs bestaat in de code met dezelfde naam en standaardwaarde.
  - Elk veld in de schemabeschrijving komt voor in een echt record uit de tests.

## Phase 7: nulmeting (Claude, niet pi-bolt; vraagt aparte toestemming)
- [ ] Done
- **Depends on:** Phase 1-5
- **Goal:** een eerste verdeling van stopredenen en kosten op echte data, als uitgangspunt voor de vervolgstappen.
- **Steps:**
  1. Zet het log aan op de index van deze repo en draai een vaste lijst van ~30 zoekvragen en ~5 onderzoeksvragen.
  2. Tabelleer per stopreden het aantal zoekopdrachten, het aantal rondes en de doorlooptijd.
  3. Tabelleer per onderzoeksrun de doorlooptijd, het tokenverbruik en de synthesemodus.
  4. Zet de tabellen en de vragenlijst in dit plan onder "Nulmeting".
- **Notes:** dit doet echte embedding-, rerank- en LLM-aanroepen en kost dus quota. Voer het pas uit na expliciete toestemming.

---

## Final verification (Claude, na alle fases)
- [x] Smoke: `uv run pytest tests/test_smoke.py -v -n auto` (14 geslaagd)
- [x] Volledige suite: `uv run pytest tests/ -v` (als achtergrondtaak); zie de notitie hieronder
- [x] Lint en types: `uv run ruff check chunkhound` en `uv run mypy chunkhound`; geen nieuwe fouten ten opzichte van `main` (ruff per gewijzigd bestand gelijk of lager, mypy 991 fouten op beide)
- [x] `tests/test_multi_hop_metrics.py`: recall@k en MRR gelijk aan `main` (de test controleert exacte waarden)
- [x] Volledige diff nagelopen tegen het Goal; geen gedragswijziging bij standaardinstellingen
- [x] `.pi-handoff/` verwijderd; niets daaruit gecommit

**Notitie bij de volledige suite (2026-11-14).** De eerste run in de worktree gaf 5886 geslaagd, 114 mislukt en 158 errors. Alle 272 kwamen uit de testomgeving van de worktree, niet uit de wijzigingen:

- `/tmp` (tmpfs, 16 GB) liep vol tijdens de run: `No space left on device`.
- De venv van de worktree bevatte de oude `chunkhound_native` 5.2.1 uit de wheel. Tests die `chunkhound` als subproces buiten de repo starten, laadden die versie en misten `AnalyticsRecorder`.
- `site/node_modules` ontbrak, waardoor `npm run build` voor de site-tests faalde.

Na herstel (native module en `chunkhound.libs` uit de venv van de hoofdcheckout gekopieerd, `site/node_modules` gekopieerd, `--basetemp` op schijf) zijn de 65 betrokken testbestanden opnieuw gedraaid: 416 geslaagd, 9 overgeslagen, 1 mislukt. Die ene is `tests/contracts/test_native_self_relative_rpath.py`; die verwacht de Rust-buildmap `target/duckdb-download`, en die bestaat in deze worktree niet. Draai de volledige suite nog één keer in een checkout met een Rust-build voordat de branch naar een PR gaat.

## Progress log
| Date | Phase | sessionId | Commit | Notes |
|---|---|---|---|---|
| 2026-11-14 | 1 | `01a1d761-73a2-7440-a3c6-7394680a32cf` | zie `git log` | 31 gerichte tests en 14 smoke-tests groen. De standaardwaarden staan in `research_config.py` om een circulaire import te vermijden. Eén correctieronde: ongebruikte re-exports verwijderd, docstring bijgewerkt. |
| 2026-11-14 | 2 | `01a1d768-0556-7440-a3c6-73978dae849d` | zie `git log` | 9 contracttests voor het log; config- en smoke-tests groen. De CLI zet het log alleen op voor de commando's die ook analytics krijgen (o.a. `search`, `research`, `map`, `autodoc`). Trace-notitie van fase 3 aangescherpt. |
| 2026-11-14 | 3 | `01a1d76b-3313-7440-a3c6-7399088a8556` | zie `git log` | Eén geparametriseerde contracttest over 11 scenario's (alle zeven stopredenen en beide single-hop-redenen). `rounds` bevat ook de ronde waarop de policy stopt; `n_rounds` telt alleen de rondes die de stopcontrole doorkwamen, dus bij `score_drop` en `min_relevance` is `len(rounds) == n_rounds + 1`. Bij een rerank-fout is er geen ronde-item. |
| 2026-11-14 | 4 | `01a1d771-8827-7440-a3c6-739b655ea686` | zie `git log` | Zes contractgevallen; 268 gerichte tests en 14 smoke-tests groen. De sessie werd één keer onderbroken en in dezelfde sessie hervat. Met het log uit vraagt de run geen tellers op. `llm_usage` is leeg als de provider geen tellers geeft of het opvragen faalt. De hergebruikte nep-zoekservice vervangt `SearchService`; de test schrijft daarom op die grens een proefrecord in een eigen trace en controleert dat het de run als `parent_trace_id` heeft (v1, v2, v3 en de terugval naar v1). Overerving via `asyncio.gather` is gedekt door de test van het log zelf uit fase 2. Bij "geen codecontext gevonden" is `success` `true` en zijn `num_clusters` en `synthesis_mode` `null`. |
| 2026-11-14 | 5 | `01a1d96c-1257-70ae-9edb-743d87c3fd7f` | zie `git log` | Eén geparametriseerde contracttest over zes gevallen; 317 gerichte tests en 14 smoke-tests groen. Het vraagfilter schrijft ook een record als er hooguit één vraag is en de LLM niet wordt aangeroepen (`fallback: false`). `selected` bij `gap_selection` verwijst naar de aflopend gesorteerde scores, niet naar de invoervolgorde. `elbow_index` staat er ook als de elbow wel gevonden maar niet gebruikt is. Eén correctieronde: import naar moduleniveau, twee losse opmaakwijzigingen teruggedraaid. |
| 2026-11-14 | 6 | n.v.t. (Claude) | zie `git log` | De drie multi-hop-velden stonden al in de tabel, maar met de oude omschrijving; die is aangepast aan het werkelijke gedrag. Nieuwe sectie "Decision Log" met opties, privacy, rotatie en het recordformaat per event, plus een tabel van stopredenen met de bijbehorende instelling. Drie env-variabelen toegevoegd aan de lijst. Veldnamen en standaardwaarden zijn tegen de code gecontroleerd. |

---

## Prompts (voor Claude, per fase kopiëren)

**Een fase starten** (nieuwe sessie, model uit de fase):
> Read `AGENTS.md` and `docs/melly/plans/2026-11-14-beslislaag-en-beslislog.md` in `<cwd>`. Implement only Phase N. Follow the Constraints, the Besluiten and the Final report format in the plan. Do not start other phases.

**Feedback binnen een fase** (zelfde `sessionId`, zolang de context < ~200k is):
> Review feedback on Phase N: <concreet probleem, bestand:regel, verwacht gedrag>. Fix only this and report.

**Handoff** (zelfde `sessionId`, bij context > ~200k, bij escalatie naar astra of na compactie):
> Write `.pi-handoff/phase-N.md` (≤ 60 lines): decisions made, files changed, what was tried and failed, current test status, remaining steps. Reply only "written".

daarna in een nieuwe sessie:
> Read `AGENTS.md`, `docs/melly/plans/2026-11-14-beslislaag-en-beslislog.md` and `.pi-handoff/phase-N.md` in `<cwd>`. Continue Phase N from the handoff. Follow the Constraints and the Final report format in the plan.

**Na een timeout of annulering** (zelfde `sessionId`):
> You were interrupted. Check `git status` and `git diff`, then finish Phase N and report.
