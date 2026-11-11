# PLAN: herhaalruns van `map` en `autodoc` versnellen (ontwikkelcache en `--c4-only`)

- **Spec:** [2026-11-11-herhaalruns-cache-design.md](../specs/2026-11-11-herhaalruns-cache-design.md). Lees §2-§6 en §10 (uitkomst fase 0) voordat je begint; daar staan de seams met file:line.
- **Status:** goedgekeurd 2026-11-11. Geeft geen toestemming voor een providerrun (fase 7) of een push.

## Goal

Een herhaalrun van `chunkhound map` en `chunkhound autodoc` tijdens ontwikkeling moet minuten kosten in plaats van uren. Daarvoor zijn drie dingen nodig:
- een modus `map --c4-only` zonder HyDE en zonder topic-research;
- een opt-in cache `--dev-cache` voor het HyDE-plan, voor de research per topic (geldig zolang de bewijsbestanden ongewijzigd zijn) en voor de LLM-stappen van AutoDoc;
- `--refresh-plan` om het plan te verversen.

Zonder deze vlaggen verandert er niets.

## Context

- Repo: `/home/disorder/Projects/Github/chunkhound`, basis `main` vanaf `6fbba30e`. Elke fase draait in een eigen worktree en branch (zie Uitvoering).
- Projectregels: lees `AGENTS.md`, met name TESTING_PHILOSOPHY: alleen contracttests, en nepdiensten alleen op echte externe grenzen (LLM-provider).
- Opslag: `DecisionStore` in `chunkhound/services/extraction/store.py:140`, root `.chunkhound/extraction/decisions` (zie C4: `chunkhound/code_mapper/c4/decisions.py:432-476`). De store heeft geen hervalidatiehaak, dus fase 2 bouwt een dunne laag erboven.
- Besluiten (spec §7):
  - een topic is geldig zolang zijn bewijsbestanden ongewijzigd zijn;
  - het plan wordt met `--dev-cache` automatisch hergebruikt, ook na codewijzigingen;
  - de vlagnamen zijn `--c4-only`, `--dev-cache` en `--refresh-plan`.

## Constraints (voor elke fase)

- Wijzig alleen de bestanden die in de fase staan, tenzij het strikt nodig is. Noem een extra bestand in het rapport.
- Niet committen, niet pushen en geen andere fasen beginnen.
- Geen echte LLM-calls en geen netwerk. Draai `chunkhound map`, `chunkhound autodoc` en `chunkhound index` niet tegen een echte provider. Tests gebruiken een nep-provider.
- Zonder `--dev-cache` mag er geen cachebestand worden gelezen of geschreven. Bestaand gedrag en bestaande tests blijven groen.
- Geen configuratie- of omgevingsvariant van de vlaggen, alleen CLI-vlaggen.
- `AGENTS.md` niet wijzigen. Geen `print()` in MCP-serverbestanden. Geen forward references in type-annotaties tenzij nodig.
- Houd de context klein:
  - zoek met `rg` en lees alleen relevante regelbereiken;
  - draai gerichte tests met `-q --tb=short` en stuur lange uitvoer door `| tail -n 40`;
  - draai niet de volledige suite; dat doet Claude.
- Draai in de worktree altijd `uv run --no-sync ...`, na eenmalig `make dev` (bootstrap van de native extensie).
- Lint en types op de gewijzigde bestanden: `uv run --no-sync ruff check <bestanden>` en `uv run --no-sync mypy <gewijzigde chunkhound-bestanden>`.

## Final report format (elke fase)

Maximaal ~15 regels:
1. Gewijzigde bestanden, één regel per bestand met een korte reden.
2. Gedraaide tests, lint en mypy, met de resultaten.
3. Afwijkingen van het plan en open punten.

## Uitvoering

- Elke fase krijgt één nieuwe pi-bolt-sessie in een eigen worktree: `git worktree add /home/disorder/orca/workspaces/chunkhound/cache-fN -b map-cache/fN <basis>`.
- De basis is `main` of de branch waarvan de fase afhangt.
- Na elke fase:
  - Claude reviewt de diff en draait de verify-opdracht en de smoke-tests;
  - Claude vinkt de fase af en commit (alleen als de gebruiker daarom vraagt);
  - Claude merget daarna in een integratiebranch `map-cache/integration`.
- Parallel mogelijk:
  - fase 1 met fase 2;
  - fase 3 met fase 4, na fase 2.

---

## Phase 1: `map --c4-only`
- [ ] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** `chunkhound map --c4-only` draait de volledige C4-analyse met een echte LLM, zonder DB- of embedding-setup, zonder HyDE en zonder topic-research. Daarna schrijft het de C4-uitvoer weg (spec §3, §10).
- **Files:**
  - `chunkhound/api/cli/parsers/code_mapper_parser.py`
  - `chunkhound/api/cli/commands/code_mapper.py`
  - een test in `tests/code_mapper/c4/test_cli_contract.py` (of een nieuw testbestand daarnaast)
- **Steps:**
  1. Voeg de vlag `--c4-only` toe bij de C4- en uitvoeropties (`code_mapper_parser.py:70-76,123-125`).
  2. Valideer in de command: combineren met `--no-c4` of met `--plan` (`--overview-only`) is een fout (`code_mapper.py:274-283`).
  3. Vertak in `_run_requested_outputs` (`code_mapper.py:328-344`), vóór de keuze tussen trial en full:
     - maak de echte map-LLM-manager;
     - vervang `c4.llm` door `C4Llm(..., trial=False)`;
     - doe `await c4.finish(await c4.analyze(), None)`;
     - laat de bestaande staging, publicatie en `c4.write` (`:311-324`) intact.
  4. Zet een regel `c4-only: topics skipped` in het rapport. Laat bestaande topicbestanden in de uitvoermap staan.
- **Acceptance criteria:**
  - Test `test_map_c4_only_makes_no_research_calls`: met een nep-LLM ontstaat een C4-model met `kind` "full", zonder HyDE- of research-calls en zonder topicbestanden.
  - `--c4-only` samen met `--no-c4` of samen met `--plan` geeft een foutmelding (in dezelfde test of een tweede kleine contracttest).
  - Bestaande tests in `tests/code_mapper` blijven groen.
- **Verify:** `uv run --no-sync pytest tests/code_mapper -q --tb=short -n auto | tail -n 40`
- **Notes:**
  - Zonder de vervanging van de trial-LLM blijft de uitvoer ten onrechte op `kind` "trial" staan.
  - `finish_c4` accepteert `topics=None` al (`c4/pipeline.py:762-774,817,883-890`); verander daar niets.

## Phase 2: DevCache-laag boven `DecisionStore`
- [ ] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** één kleine, herbruikbare module voor alle ontwikkelcaches. Fase 3 tot en met 5 gebruiken alleen deze module (spec §6, §10).
- **Files:**
  - nieuw `chunkhound/services/extraction/dev_cache.py`
  - eventueel kleine aanpassingen in `chunkhound/services/extraction/store.py`
  - test `tests/services/extraction/test_dev_cache.py` (of de bestaande map voor store-tests)
- **Steps:**
  1. Maak `DevCache(root, *, enabled)`, die `DecisionStore` op `.chunkhound/extraction/decisions` gebruikt.
     - `get(question, question_version, provider, item, validate=None)` geeft het antwoord terug, of `None` bij een miss of afwijzing.
     - `validate(answer) -> bool`. Een afgewezen item telt als miss, en alleen geaccepteerde items worden ge-`touch`t.
     - `put(...)` schrijft een envelop met `created_at` (UTC ISO) en het antwoord.
     - Als `enabled=False`, doet het object niets: geen lezen en geen schrijven.
  2. Voeg een helper toe die een `ProviderIdentity` (`store.py:31`) afleidt uit een LLM-provider-instantie van `llm_manager`: provider, model, reasoning effort en base_url. Hergebruik wat C4 al doet als dat kan.
  3. Voeg een helper `source_manifest_version(paths_globs, base) -> str` toe:
     - de sha256 over de gesorteerde relatieve paden plus de sha256 per bestand, met een expliciete formaatversie;
     - zijn de bronbestanden niet leesbaar, dan geeft hij `None` en zet de aanroeper de cache voor die stap uit ("fail closed").
  4. Houd een teller bij van hergebruikte en nieuwe items per vraag, voor het rapport.
- **Acceptance criteria:**
  - Test: `put` gevolgd door `get` met dezelfde sleuteldelen geeft het antwoord terug. Een ander model of een andere `question_version` geeft een miss.
  - Test: een `validate` die `False` teruggeeft levert een miss op.
  - Test: met `enabled=False` ontstaan er geen bestanden.
- **Verify:** `uv run --no-sync pytest tests/services/extraction -q --tb=short -n auto | tail -n 40`
- **Notes:** geen koppeling met C4-typen. Verander het gedrag van `DecisionStore` voor C4 niet.

## Phase 3: AutoDoc-cache en `autodoc --dev-cache`
- [ ] Done
- **Depends on:** Phase 2
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** met `--dev-cache` hergebruikt AutoDoc de cleanup per topic, het homepage-overzicht en de navigatie met woordenlijst (spec §4, §10).
- **Files:**
  - de autodoc-parser (`rg -n "map-in" chunkhound/api/cli/parsers`)
  - `chunkhound/api/cli/commands/autodoc.py:60-75`
  - `chunkhound/api/cli/commands/autodoc_generate.py:36-71`
  - `chunkhound/autodoc/generator.py`
  - `chunkhound/autodoc/cleanup.py`
  - `chunkhound/autodoc/ia.py`
  - een test in `tests/autodoc/`
- **Steps:**
  1. Voeg de vlag `--dev-cache` toe aan `autodoc`. Geef een optionele `DevCache` door tot in de cleanup en de IA-stappen.
  2. Cleanup (`cleanup.py:80-152`):
     - render eerst de prompts en vul de hits direct in `cleaned[idx]` in;
     - stuur alleen de misses in batches naar de provider;
     - sla elke succesvolle uitkomst meteen op, ook die van de fallback per topic;
     - laat `_batch_complete_with_backoff` ongewijzigd.
     - Sleutel: `question` is `autodoc_cleanup`; `item` is de sha256 van de gerenderde gebruikersprompt; `question_version` is de sha256 van de systeemprompt, het sjabloon en `max_completion_tokens`; de provider is de identiteit van de rol `autodoc_cleanup`.
  3. Homepage (`ia.py:265-298`): doe de lookup na het renderen. Sla alleen een niet-lege uitkomst op en behoud het huidige gedrag bij een fout.
  4. Navigatie en woordenlijst (`ia.py:171-199`): doe de lookup na de prompt en het schema. Cache de ruwe JSON en laat bij een hit de bestaande validatie opnieuw draaien.
  5. Zet in de uitvoer een regel `dev-cache: cleanup X reused / Y new, homepage …, site_ia …`.
- **Acceptance criteria:**
  - Test `test_autodoc_dev_cache_second_run_makes_no_llm_calls`: twee keer `autodoc --map-in <fixture> --dev-cache` met een nep-provider. De tweede run doet nul LLM-calls en de pagina's zijn identiek.
  - Test: één gewijzigd topicbestand geeft precies één nieuwe cleanup-call. De homepage- en IA-calls draaien dan opnieuw, omdat hun prompt veranderde.
  - Zonder `--dev-cache` ontstaan er geen cachebestanden. Bestaande tests in `tests/autodoc` blijven groen.
- **Verify:** `uv run --no-sync pytest tests/autodoc -q --tb=short -n auto | tail -n 40`
- **Notes:** de interne kaartrun via `autodoc_autorun.py` hoort bij fase 6, niet bij deze fase.

## Phase 4: `map --dev-cache` voor het HyDE-plan en `--refresh-plan`
- [ ] Done
- **Depends on:** Phase 2
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** met `--dev-cache` worden de ruwe HyDE-antwoorden (arch en ops) bewaard en hergebruikt, ook na codewijzigingen. `--refresh-plan` forceert een nieuw plan (spec §5.2, §10).
- **Files:**
  - `chunkhound/api/cli/parsers/code_mapper_parser.py`
  - `chunkhound/api/cli/commands/code_mapper.py`
  - `chunkhound/code_mapper/pipeline.py`
  - `chunkhound/code_mapper/service.py` (alleen om de audience en de cache door te geven)
  - een test in `tests/code_mapper/`
- **Steps:**
  1. Voeg de vlaggen `--dev-cache` en `--refresh-plan` toe aan `map`.
     - `--refresh-plan` zonder `--dev-cache` is een fout.
     - Beide vlaggen samen met `--c4-only` is ook een fout, als fase 1 al gemerged is; anders noteer je het als open punt.
  2. Geef de `DevCache` en de audience door tot in `run_code_mapper_overview_hyde`. De audience zit nu niet in de HyDE-signatuur (`pipeline.py:132-145`), en `service.py:243` heeft hem wel.
  3. Doe de lookup vóór de scope-sampling (`pipeline.py:234`). Bij een hit:
     - geen HyDE-calls;
     - de opgeslagen ruwe antwoorden gaan door de bestaande parsing (`:397-425`) en de artefactschrijfstap (`:377-395`).
  4. Sla de antwoorden op na succesvolle calls (`:375`).
     - Sleutel: `question` is `hyde_plan`.
     - `item` bestaat uit de repository-identiteit (het absolute pad van de projectroot), het scopelabel, `comprehensiveness`, `max_points`, het ops-budget, de audience en de sha256 van de inhoud van het `--context`-bestand.
     - `question_version` is de sha256 van de modussjablonen, het contextsjabloon en de inline-objective (`:281-330`).
     - De provider is die van de HyDE-provider.
     - Layout en snippets horen niet in de sleutel.
  5. Met `--refresh-plan` volgt geen lookup, wel opslag. Het rapport vermeldt `plan reused (from <created_at>)` of `plan refreshed`.
- **Acceptance criteria:**
  - Test: de tweede map-run met `--dev-cache` en een nep-provider doet nul HyDE-calls en geeft dezelfde PoI-lijst. Dat geldt ook nadat een bronbestand in de fixture is gewijzigd.
  - Test: met `--refresh-plan` doet de run wel HyDE-calls.
  - Zonder `--dev-cache` ontstaan geen cachebestanden.
- **Verify:** `uv run --no-sync pytest tests/code_mapper -q --tb=short -n auto | tail -n 40`
- **Notes:** de topic-cache hoort bij fase 5. Raak `_run_point_once` in deze fase niet aan.

## Phase 5: topic-cache met geldigheid op bewijsniveau
- [ ] Done
- **Depends on:** Phase 4
- **Model:** `openai-codex/gpt-6.1-sol` / `high`
- **Goal:** met `--dev-cache` wordt de research per topic hergebruikt zolang de bewijsbestanden ongewijzigd zijn (spec §5.3, §10).
- **Files:**
  - `chunkhound/code_mapper/service.py`
  - `chunkhound/api/cli/commands/code_mapper.py` (alleen voor de rapportregels)
  - eventueel `chunkhound/services/extraction/dev_cache.py`
  - een test in `tests/code_mapper/`
- **Steps:**
  1. Bereken bij de start van de run één keer het broncodemanifest als `question_version` voor `topic_research`. Het dekt `chunkhound/services/research/**/*.py`, `chunkhound/services/prompts/**/*.py` en `chunkhound/services/deep_research_service.py`. Geeft het manifest `None`, dan staat de topic-cache uit en vermeldt het rapport dat.
  2. Doe in `_run_point_once` (`service.py:430-479`), na `section_query` en vóór de research, een lookup.
     - `item` bevat `section_query`, `path_filter`, de researchconfiguratie (comprehensiveness en relevante limieten), en de identiteiten van de utility- en de synthesisprovider.
     - Cache alleen het resultaatwoordenboek per topic (`{"answer", "metadata"}`), niet `CodeMapperPipelineResult`.
  3. Opslaan:
     - sla alleen bruikbare successen op, met in de envelop de bewijsbestanden uit `metadata.sources.files`, genormaliseerd naar paden relatief aan de indexbasis;
     - voeg per bestand de `content_hash` toe via `get_file_by_path` (`duckdb_provider.py:2897-2932`), per run per pad bewaard.
  4. Valideren bij een hit:
     - elk bewijsbestand bestaat nog in de index en heeft een niet-lege hash die gelijk is aan de opgeslagen hash;
     - zo niet, dan telt het als miss en volgt nieuwe research.
     - `None == None` telt niet als gelijk.
  5. Laat workers, nummering, retries en de weergave van fouten (`service.py:507-614`) ongewijzigd.
  6. Rapport: `dev-cache: topics X reused / Y re-researched (evidence changed) / Z new`, plus de hint `run chunkhound index after code changes`.
- **Acceptance criteria:**
  - Test `test_dev_cache_second_run_makes_no_llm_calls` (map): met een fixture-index en een nep-provider doet de tweede run nul LLM-calls voor HyDE en topics.
  - Test `test_changed_evidence_file_reresearches_only_that_topic`: na een gewijzigde hash van het bewijsbestand van één topic draait alleen dat topic opnieuw.
  - Test `test_prompt_or_provider_change_misses`: een andere modelnaam geeft een miss.
- **Verify:** `uv run --no-sync pytest tests/code_mapper -q --tb=short -n auto | tail -n 40`
- **Notes:**
  - De paden kunnen soms absoluut zijn (`research/shared/file_reader.py:79-95`); normaliseer ze.
  - Gebruik de DB-hash, niet een hash van het bestand op schijf.
  - Kost deze fase meer dan ~150k context, stop dan en meld het. Splits niet zelf.

## Phase 6: `autodoc --dev-cache` doorgeven aan de interne kaartrun
- [ ] Done
- **Depends on:** Phase 3, Phase 4 (en Phase 5 voor de volledige winst)
- **Model:** `openai-codex/gpt-6.1-terra` / `low`
- **Goal:** `autodoc` zonder `--map-in` geeft `--dev-cache` door aan de map-run die het intern start.
- **Files:**
  - `chunkhound/api/cli/commands/autodoc_autorun.py:312-348` en de aanroepers daarvan
  - een test in `tests/autodoc/test_autodoc_cli_autorun_options.py`
- **Steps:**
  1. Geef `dev_cache` expliciet door via de signatuur tot in de handmatig gebouwde map-`Namespace`.
  2. Zet `refresh_plan=False` en `c4_only=False` expliciet in die `Namespace`.
- **Acceptance criteria:**
  - Test: de autorun-`Namespace` bevat `dev_cache=True` als `autodoc --dev-cache` zonder `--map-in` draait.
  - Bestaande autorun-tests blijven groen.
- **Verify:** `uv run --no-sync pytest tests/autodoc -q --tb=short -n auto | tail -n 40`

## Phase 7: meetrun (Run 12), alleen na expliciete toestemming
- [ ] Done
- **Depends on:** Phase 1-6, gemerged en geverifieerd
- **Uitvoering:** door Claude, niet door pi-bolt.
- **Opzet:** op een worktree van de integratiebranch, met een verse index:
  1. `map --dev-cache` (koud);
  2. `map --dev-cache` (warm, geen wijziging);
  3. `autodoc --map-in … --dev-cache`, twee keer;
  4. één wijziging in een bestand dat bewijs is voor één topic, daarna `chunkhound index` en opnieuw `map --dev-cache`;
  5. `map --c4-only`.
- **Acceptance:**
  - de warme map-run duurt minder dan 5 minuten;
  - de tweede AutoDoc-run doet nul LLM-calls;
  - na de wijziging wordt alleen het betrokken topic opnieuw onderzocht;
  - `--c4-only` duurt minder dan 3 minuten met een warme besliscache.
- **Vastleggen:** de tijden en tellers in het besluitenlog, en het bewijs in `.scratch/omap-a12/`.

---

## Final verification (Claude, na alle fasen)
- [ ] Volledige suite: `uv run pytest tests/ -v` (als achtergrondtaak)
- [ ] Lint en types: `uv run ruff check chunkhound` en `uv run mypy chunkhound`
- [ ] Review van de complete diff tegen het doel en de spec
- [ ] `.pi-handoff/` verwijderd; niets daaruit gecommit

## Progress log
| Date | Phase | sessionId | Commit | Notes |
|---|---|---|---|---|

---

## Prompts (voor Claude, per fase te kopiëren)

**Fase starten** (nieuwe sessie, model uit de fase):
> Read `AGENTS.md` and `docs/melly/plans/2026-11-11-herhaalruns-cache.md` in `<worktree>`, and the referenced sections of the spec. Implement only Phase N. Follow the Constraints and the Final report format in the plan. Do not start other phases.

**Feedback binnen een fase** (dezelfde `sessionId`, zolang de context onder ~200k blijft):
> Review feedback on Phase N: <concreet probleem, file:line, verwacht gedrag>. Fix only this and report.

**Handoff** (dezelfde `sessionId`):
> Write `.pi-handoff/phase-N.md` (≤ 60 lines): decisions made, files changed, what was tried and failed, current test status, remaining steps. Reply only "written".

**Na een timeout of annulering** (dezelfde `sessionId`):
> You were interrupted. Check `git status` and `git diff`, then finish Phase N and report.
