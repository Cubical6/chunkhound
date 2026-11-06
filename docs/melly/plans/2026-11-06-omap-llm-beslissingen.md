# O-MAP: LLM-beslissingen voor personen en externe systemen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Op OMP: seriële Orca-workers, per taak implementatie en onafhankelijke review, daarna eindreview. Steps use checkbox (`- [ ]`) syntax for tracking. Een afwijking van de goedgekeurde spec eerst voorleggen.

**Goal:** dienstentabellen vullen ontbrekende personen en externe systemen aan; gesloten beslissingen verwijderen ruis en toetsen LLM-samenvoegingen; ongewijzigde invoer vraagt niets opnieuw.

**Architecture:** `decide` controleert de onbewerkte documentuitkomst vóór `_identify`; `consolidate` stelt per soort groepen voor en toetst overblijvende leden en paren vóór `_titles`. Een Strategy-runner deelt de levenscyclus van de vijf gesloten vragen, met `DecisionStore` naast de bestaande extractiecache. Synchrone assemblage past eerst de LLM-merges en daarna de omgezette lockregels toe.

**Tech Stack:** Python `>=3.10,<3.15`, Pydantic 2, tree-sitter `0.25.2`, tree-sitter-markdown `0.5.1`, tree-sitter-language-pack `0.9.0`, pytest/pytest-asyncio, ruff en mypy; geen nieuwe dependencies (`pyproject.toml:18,50-52`, `uv.lock:3792-3793,4073-4074,4122-4123`).

**Spec:** [2026-11-06-omap-llm-beslissingen-design.md](../specs/2026-11-06-omap-llm-beslissingen-design.md) §1–§13. **Model:** [map-structuuranalyse.md](../models/map-structuuranalyse.md) R17–R23, §2–§5. **Besluiten:** [2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md), rijen van 2026-11-06 vanaf “Domeinmodel · personen”.

**Status:** goedgekeurd 2026-11-06 (besluit: Planreview · goedkeuring). Uitvoering via de seriële Orca-coordinator; run 6, wijziging van de run-5-overrides en push niet goedgekeurd.

## Project Commands

Vanuit de uitvoering-worktree, via `uv`. **Project bootstrap** voor de nieuwe uitvoering-worktree: `Makefile:45-59` en besluit “O-MAP §20 · execution bootstrap” schrijven de lokale native extensie voor. Alleen de bestaande repo-dependencies en extensie installeren; geen nieuwe tooling of index.

```bash
set -e
make dev
```

Daarna `--no-sync`, zodat uv niet opnieuw de native wheel over de lokale extensie installeert. De smoke-opdracht blijft dezelfde verplichte suite. Reviewers draaien bootstrap/generator niet opnieuw; alleen de read-only kwaliteitscommando's.

```bash
uv run --no-sync pytest tests/code_mapper tests/services/extraction -q -p no:cacheprovider -n auto
uv run --no-sync pytest tests/test_smoke.py -v -n auto
uv run --no-sync python scripts/generate_c4_schemas.py
```

De schemagenerator alleen in Taak 1. Rode/groene deelruns staan per taak hieronder. Reviewers draaien dezelfde kwaliteitscommando's, zonder autofix, met commandolokale `TMPDIR` in de eigen canonieke genegeerde SDD-workspace. De volledige suite `uv run pytest tests/ -v` alleen vóór een PR; dit plan maakt of pusht geen PR.
Lint en types per taak (exacte paden; tests alleen linten):

| Taak | Lint                                                                                                                                                                                                                                                                                              | Types                                                                                                                                                                         |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | `uv run --no-sync ruff check chunkhound/code_mapper/c4/model.py chunkhound/code_mapper/c4/curation.py chunkhound/code_mapper/c4/assemble.py tests/code_mapper/c4/test_assemble.py tests/code_mapper/c4/test_lockfile.py`                                                                          | `uv run --no-sync mypy chunkhound/code_mapper/c4/model.py chunkhound/code_mapper/c4/curation.py chunkhound/code_mapper/c4/assemble.py`                                        |
| 2    | `uv run --no-sync ruff check chunkhound/services/extraction/store.py chunkhound/code_mapper/c4/decisions.py chunkhound/code_mapper/c4/llm.py chunkhound/code_mapper/c4/pipeline.py tests/code_mapper/c4/test_decisions.py tests/code_mapper/c4/conftest.py tests/code_mapper/c4/test_pipeline.py` | `uv run --no-sync mypy chunkhound/services/extraction/store.py chunkhound/code_mapper/c4/decisions.py chunkhound/code_mapper/c4/llm.py chunkhound/code_mapper/c4/pipeline.py` |
| 3    | `uv run --no-sync ruff check chunkhound/code_mapper/c4/tables.py chunkhound/code_mapper/c4/decisions.py tests/code_mapper/c4/test_decisions.py tests/code_mapper/c4/conftest.py`                                                                                                                  | `uv run --no-sync mypy chunkhound/code_mapper/c4/tables.py chunkhound/code_mapper/c4/decisions.py`                                                                            |
| 4    | `uv run --no-sync ruff check chunkhound/code_mapper/c4/consolidation.py chunkhound/code_mapper/c4/decisions.py chunkhound/code_mapper/c4/pipeline.py tests/code_mapper/c4/test_decisions.py tests/code_mapper/c4/test_pipeline.py tests/code_mapper/c4/conftest.py`                               | `uv run --no-sync mypy chunkhound/code_mapper/c4/consolidation.py chunkhound/code_mapper/c4/decisions.py chunkhound/code_mapper/c4/pipeline.py`                               |

**Bekende nulmeting:** vóór dit plan faalde `tests/autodoc/test_architecture_generation.py::test_missing_model_is_warning_not_cli_failure` met `Error: No ChunkHound project found.` Geen fix, skip of nieuwe verwachte fout voor dit plan. Van de eerdere achtergrondrun is geen betrouwbaar totaal beschikbaar; geen groene nulmeting claimen.

## Global Constraints

- De goedgekeurde spec is leidend; één commit per taak, eigen paden expliciet stagen; geen push.
- Geen echte providerrun, geen wijziging/verwijdering van de gebruikersbestanden `.chunkhound/map.lock.json` of `.chunkhound/extraction`. Proeven schrijven alleen in hun eigen tijdelijke repo. Run 6 en het tijdelijk weghalen van run-5-overrides vragen aparte toestemming (§12).
- `.superpowers/design/c4-shared-extraction-claude-handoff.md` is gebruikersmateriaal en blijft ongestaged.
- `SCHEMA_VERSION` blijft **5**; document-`_VALIDATOR_VERSION` blijft **3**. Eigen vraagversies hashen prompt + antwoordschema + eigen validatorversie.
- Interne paar, contract en AutoDoc veranderen niet van formaat. `classify`, bestaande component-`merge`, `titles` en `summaries` veranderen niet van beslisgedrag.
- Alle zes nieuwe vragen gebruiken `C4Llm.call(..., provider="utility")`, één ronde; geen stemmen. Bewijs is geen instructie; prompts, code en rapportregels zijn Engels.
- `DecisionStore` valideert cachehits opnieuw; corrupte/vreemde bestanden zijn misses. Fallback nooit bewaren; trial nooit schrijven, touch/prune inbegrepen.
- Nieuwe proeven gebruiken de bestaande fake alleen aan de providergrens. Geen tests op prompttekst, private helpers, doorgegeven argumenten of incidentele totale aantallen.
- Elke taak leest `AGENTS.md` uit de context en `skill://test-driven-development` vóór productiecode. Na runtimebewijs werkt die taak `CHANGELOG.md` bij; geen aparte documentatie-/opruimtaak.
- Geen git-tags of versiebump; geen nieuwe tooling of contextbestanden. Bestaande LSP gebruiken, bij ontbrekende server de melding vastleggen en exact zoeken met `grep`.

## Review Focus

1. **Cacheschade:** onleesbaar JSON, verkeerde sleutel/versie of een opgeslagen ongeldig antwoord mag geen oude beslissing uitvoeren — Taak 2, `test_r23_bad_cache_is_a_miss`.
2. **Bundelgrenzen:** meerdere bundels mogen elkaars uitgestelde herkansing niet overschrijven; ook een te groot ondeelbaar item veroorzaakt geen te grote aanvraag — Taak 2, `test_decision_bundles_retry_independently`; Taak 4, `test_oversized_group_does_not_call_provider`.
3. **Markdown is geen platte tekst:** opmaak, links, code, escaped pipes en niet-ASCII-tekst mogen term, citaat of regelnummers niet beschadigen — Taak 3, `test_r21_visible_cells_keep_source_lines`.
4. **Botsende overrides:** meerdere bron-id's die één doel worden moeten onafhankelijk van invoervolgorde dezelfde naam, merge en melding geven — Taak 1, `test_r22_remapped_override_conflicts_are_deterministic`.
5. **Gedeeltelijke storing:** hits blijven gelden, alleen gemiste items vallen terug, en een volgende run vraagt die missers opnieuw — Taak 4, `test_r23_partial_failure_preserves_cached_decisions`.

## Bestanden, grenzen en volgorde

| Taak | Eigen verantwoordelijkheid                                                   | Nieuwe bestanden / belangrijkste wijzigingen                                                      |
| ---- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 1    | Synchrone uitvoering van merges, omzetten van overrides en lockcontract      | `assemble.py`, `curation.py`, `model.py`, gegenereerd lock-schema                                 |
| 2    | Cache + gedeelde gesloten runner + elementcontrole, bruikbaar in de pipeline | `services/extraction/store.py`, nieuw `c4/decisions.py`, `c4_element.md`, `llm.py`, `pipeline.py` |
| 3    | Tabellen en rij-elementen, op de runner van Taak 2                           | nieuw `c4/tables.py`, uitbreiding `decisions.py`, `c4_table.md`, `c4_row.md`                      |
| 4    | Open groepen, gesloten overblijvend lid/paren, `keep_apart`, eindintegratie  | nieuw `c4/consolidation.py`, drie prompts, `pipeline.py`                                          |

Uitvoervolgorde **1 → 2 → 3 → 4**. Taak 3 en 4 delen `decisions.py`/fixtures; geen parallelle mutaties. Geen wijziging van `contract.py`, AutoDoc of de documentextractieprompt. Elke taak levert werkend gedrag, niet alleen ongebruikte interfaces.

**Gronding:** ChunkHound-MCP ontbreekt in deze sessie → bestaande scoutbevindingen, `find`/`grep`/`read`; niet indexeren. LSP `references` op `assemble_with_notes` leverde 17 verwijzingen op, waaronder `pipeline.py:844` en `test_assemble.py`; publieke signaturen blijven behouden. De huidige `LlmSteps` is een retry-tracker (`pipeline.py:91-115`), geen object met methoden per stap: de modeloperaties `decide()`/`consolidate()` worden vrije functies, zoals de bestaande stappen. Ontwerpclaim, geen extra refactor.

---

### Task 1: Twee assemblagepasses en lockregels die het doel volgen (§7)

**Files:**

- Modify: `chunkhound/code_mapper/c4/model.py:153-161`
- Modify: `chunkhound/code_mapper/c4/schemas/map_lock.schema.json` (gegenereerd)
- Modify: `chunkhound/code_mapper/c4/curation.py:16-25,51-91,178-224`
- Modify: `chunkhound/code_mapper/c4/assemble.py:76-104,444-512`
- Test: `tests/code_mapper/c4/test_assemble.py`, `tests/code_mapper/c4/test_lockfile.py`, bestaand `tests/code_mapper/c4/test_output_contract.py`
- Modify: `CHANGELOG.md` (na bewijs)

**Classes:** `Overrides`, `ScopeLock`, `AssemblyInput`, `CurationState`; consumeert bestaande `Element`, `Relation`, `Citation`, `Reference`, `Group`, `RuntimeUnit`, `C4Evidence`, `UnlinkedCounts`, `AssemblyNotes`.

**Read:** spec §1, §7, §11; `docs/melly/models/map-structuuranalyse.md` R7/R9/R13–R16/R22 en §2; `chunkhound/code_mapper/c4/assemble.py:107-118,330-512`; `chunkhound/code_mapper/c4/curation.py`; `chunkhound/code_mapper/c4/merge.py:119-139`; `chunkhound/code_mapper/c4/lockfile.py`; projectregels en TDD-skill.

**Tools:**

- `lsp` references op `Overrides`, `AssemblyInput`, `CurationState` en `curate` — vóór wijziging van de geëxporteerde symbolen
- `bash` `uv run --no-sync python scripts/generate_c4_schemas.py` — na het lockveld
- `bash` Project Commands (pytest, smoke, ruff, mypy) — vóór commit

**Interfaces:**

- `Overrides.keep_apart: list[tuple[str, str]] = Field(default_factory=list)`; `AssemblyInput.merges: dict[str, str] = field(default_factory=dict)`, als laatste veld zodat bestaande positionele callers kloppen.
- `prepare_assembly(inp: AssemblyInput) -> tuple[CurationState, UnlinkedCounts]` in `assemble.py`: bestaande opbouw t/m documentrelaties, vóór curation/namen/coverage; nieuwe toestand per aanroep, geen mutatie van `inp`.
- `CurationState.absorbed: dict[str, str] = field(default_factory=dict)` bevat uitsluitend de geaccepteerde merges van die `curate`-aanroep.
- `curate(state: CurationState, titles: dict[str, str], overrides: Overrides, *, prefix: str = "C4-overrides:") -> CurationState`.
- `remap_overrides(overrides: Overrides, absorbed: dict[str, str]) -> tuple[Overrides, tuple[str, ...]]` in `curation.py`; bron én doel van `merge`, keys van `drop`/`names`/`descriptions` volgen `absorbed`; overige velden blijven gelijk.
- Bestaande `assemble` en `assemble_with_notes` behouden signatuur. Beide gebruiken dezelfde voorbereiding, pass 1 met `Overrides(merge=inp.merges)` en prefix `C4-decisions:`, omzetten, pass 2 lock, dan names/descriptions/titles/coverage. Alle meldingen blijven in `AssemblyNotes.ignored_overrides`.

**Acceptance:**

- Promise: een LLM-merge verliest geen bewijs of handmatige correctie; een oude v5-lock blijft leesbaar.
- Evidence: onderstaande R22-tests, lock-roundtrip en `test_shipped_schema_matches_model`; source: `chunkhound/code_mapper/c4/curation.py` en `chunkhound/code_mapper/c4/lockfile.py`.
- Judged by: tests — de precieze voorrang uit spec §7.3 is hieronder met uitvoer vastgelegd; geen menselijke naamkeuze toegevoegd.

- [ ] **Step 1: Rode contracttests.** Gebruik `assembly_input()`; in `test_assemble.py`:
  - `test_r22_lock_overrides_follow_llm_target`: `inp.merges={"external:stripe":"external:payments"}` met bestaand Payments-doel; parametriseer de zeven rijen van spec §7.3. Assert drop op Stripe verwijdert Payments, source/target-merge volgen Payments, zelfmerge meldt `same element`, bron-names/descriptions gelden op Payments, eigen Payments-regel wint. `titles`/`labels`/`classifications`/`placements` blijven onaangeroerd.
  - `test_r22_remapped_override_conflicts_are_deterministic`: twee bronnen gaan naar hetzelfde doel; conflicterende merge/names/descriptions. Assert regel van het laagste oorspronkelijke id wint tenzij het doel een eigen names/description heeft; melding bevat `conflict after merge`; omgekeerde dict/list-volgorde geeft gelijke uitvoer en meldingen.
  - `test_r18_llm_merge_preserves_evidence`: alleen het doel resteert, relaties/citaten zijn omgezet, tellers en status volgen codebewijs, zelfrelaties vervallen, statische `Reference.to` blijft origineel. Herhaalde assemblage is gelijk en `inp` blijft ongewijzigd. Ongeldige pass-1-merge meldt `C4-decisions:`, ongeldige lockmerge `C4-overrides:`.
  - In `test_lockfile.py`: breid `test_override_section_is_never_rewritten` uit met `keep_apart=[("external:google","external:google-gemini")]`; assert gelijke paren na schrijven/lezen. Nieuwe `test_v5_lock_without_keep_apart_is_readable`: `overrides.keep_apart == []`, bestaande drop/merge behouden; fout type/paarlengte blijft laadfout zonder overschrijven.
- [ ] **Step 2: Rood draaien.** `uv run --no-sync pytest tests/code_mapper/c4/test_assemble.py tests/code_mapper/c4/test_lockfile.py -q -p no:cacheprovider` — nieuwe gevallen falen door ontbrekend veld/mergegedrag, niet door een gebroken fixture.
- [ ] **Step 3: Implementeren.** Voeg velden en bovenstaande functies toe, gebruik bestaande curation voor beide passes en genereer schema's. Houd R13–R16 gelijk; pas alleen de bedoelde overridevelden om. Sorteer conflicten op oorspronkelijke id; dedupliceer drop na omzetting. `keep_apart` wordt hier alleen opgeslagen, niet tegen handmatige merges afgedwongen.
- [ ] **Step 4: Groen en runtimebewijs.** Dezelfde deelrun en Project Commands, alles groen. Voer bovendien in een tijdelijke lokale Python-proef `assemble_with_notes` uit met een LLM-merge plus een bron-drop; toon doel afwezig, oorspronkelijke referentie aanwezig en relevante meldingen. Geen provider nodig. Werk na bewijs het changelog bij en verwijder de proef.
- [ ] **Step 5: Commit.** Stage uitsluitend de Files van deze taak; `feat(c4): apply LLM merges before remapped lock overrides`.

### Task 2: Elementcontrole, gedeelde runner en cache per item (§3.1, §5–§6, §8)

**Files:**

- Modify: `chunkhound/services/extraction/store.py`
- Create: `chunkhound/code_mapper/c4/decisions.py`
- Create: `chunkhound/code_mapper/prompts/c4_element.md`
- Modify: `chunkhound/code_mapper/c4/llm.py:32-43,105-108`
- Modify: `chunkhound/code_mapper/c4/pipeline.py:615-640,754-789,838-853`
- Create: `tests/code_mapper/c4/test_decisions.py`
- Modify: `tests/code_mapper/c4/conftest.py`, `tests/code_mapper/c4/test_pipeline.py`, `CHANGELOG.md`

**Classes:** `DecisionStore`, `DecisionQuestion`, `ElementQuestion`, `DecisionOutcome`; technische `DecisionValue`, `DecisionAnswer`, `DecisionCounts`, `DecisionResults`; consumeert `DocElement`, `DocRelation`, `DocumentedOutcome`, `ProviderIdentity`, `C4Llm`, `StepReport`, `RetryQueue`, bestaande `ExtractionStore` en `LlmSteps`.

**Read:** spec §1, §3.1, §4–§6, §8, §11; `docs/melly/models/map-structuuranalyse.md` R17/R20/R23, §2–§5; `chunkhound/services/extraction/store.py`; `chunkhound/services/extraction/runner.py:43-63`; `chunkhound/services/extraction/budget.py`; `chunkhound/services/extraction/bundles.py:77-111`; `chunkhound/code_mapper/c4/classify.py:94-207`; `chunkhound/code_mapper/c4/documented.py:81-119,288-330,535-564`; `tests/code_mapper/c4/test_documented.py:70-113`; projectregels en TDD-skill.

**Tools:**

- `lsp` references op `_build_lock` en `ProviderIdentity` — vóór de signatuur-/cachewijziging
- `bash` Project Commands (pytest, smoke, ruff, mypy) — vóór commit

**Interfaces:**

- `DecisionStore(root: Path, *, read_only: bool)` krijgt de root `.chunkhound/extraction/decisions`; `get(question: str, key_parts: dict[str, Any]) -> dict[str, Any] | None`, `put(question: str, key_parts: dict[str, Any], value: dict[str, Any]) -> None`, `touch(question: str, key: str) -> None`, `prune(now: float | None = None) -> None`.
- Gebruik `key_from_parts` en `_write_json_durable`. Haal zo nodig gedeelde touch/prune-bestandsoperaties uit de bestaande methoden, zonder `ExtractionStore`-semantiek te veranderen. Cachepayload bevat format, key, key_parts en answer; get controleert pad/key/parts vóór antwoordvalidatie door de vraag.
- `DecisionValue` heeft `id: str`, `value: str`; `DecisionAnswer` heeft `decisions: list[DecisionValue]`; beide `extra="forbid"`. `DecisionCounts(total, reused, new, fallback, trial)` zijn integer-velden met default 0. `DecisionResults` bevat `values: dict[str, str]` en `counts: DecisionCounts`.
- `class DecisionQuestion(Protocol[SubjectT])` met `name: str`, `version: str`, `values: frozenset[str]`, `item(subject: SubjectT) -> dict[str, Any]`, `validate(answer: DecisionAnswer, items: Mapping[str, SubjectT], *, cached: bool = False) -> dict[str, str]`, `fallback(subject: SubjectT) -> str`. `SubjectT = TypeVar("SubjectT", contravariant=True)` houdt Python 3.10 ondersteund. Validatie retourneert canonieke waarden; bij cached=True zijn die al canoniek, maar alle ids/waarden/lidmaatschappen worden opnieuw getoetst. `ElementQuestion` gebruikt `DocElement`; payload sluit zijn voorgestelde soort uit, fallback gebruikt die soort wel.
- `async run_decisions(question: DecisionQuestion[SubjectT], subjects: Mapping[str, SubjectT], *, project_root: Path, llm: C4Llm, retries: RetryQueue, step: Literal["decide", "consolidate"], reason: str) -> DecisionResults` in `decisions.py`. Mappingkeys zijn stabiele lokale subjectkeys; korte prompt-id's bestaan alleen tijdens de aanvraag. De functie draint de geplande herkansingen vóór zij definitieve values/counts retourneert; callers consumeren geen voorlopige uitkomst.
- `DecisionOutcome` bevat `documented: DocumentedOutcome`, `added: list[DocElement]`, `kinds: dict[str, str]`, `dropped: list[str]`, `report_lines: tuple[str, ...]`. `kinds` gebruikt de subjectkeys, `dropped` de namen voor het rapport.
- `async decide(*, project_root: Path, doc_files: Sequence[str], system_name: str, documented: DocumentedOutcome, llm: C4Llm, retries: RetryQueue) -> DecisionOutcome`. Deze taak controleert elementen; Taak 3 vult dezelfde functie aan met tabellen/rijen.
- `prune_decision_cache(project_root: Path) -> None`. `_build_lock` krijgt expliciet `raw_documented: DocumentedOutcome`; caller geeft de oorspronkelijke extractie mee, nooit `DecisionOutcome.documented`.

**Acceptance:**

- Promise: een element krijgt de juiste soort of verdwijnt; dezelfde bronbeslissing wordt hergebruikt zonder modelaanroep en zonder de onbewerkte lock te verliezen.
- Evidence: R20/R23-tests hieronder plus pipeline-locktest; source: `chunkhound/services/extraction/store.py` en `chunkhound/code_mapper/c4/documented.py`.
- Judged by: tests — vaste providerantwoorden beschermen de goedgekeurde beslisregels en foutgrenzen; echte modelkwaliteit pas in run 6.

- [ ] **Step 1: Rode tests op `decide` en de pipeline, niet op de private runner.**
  - `test_r20_element_decisions_change_map_not_raw_lock`: Astro → neither, AI assistant van external → person, Stripe → external; assemble toont geen Astro/citaten daarop en wel `person:ai-assistant`; achtergebleven Astro-relatie verhoogt `notes.unlinked.no_match`. Oorspronkelijke `DocumentedOutcome` blijft gelijk. Pipeline-lock bevat de oorspronkelijke Astro/AI-assistant-elementen en extractieversie; rapport noemt verwijdering/soortwijziging.
  - `test_r23_element_cache_reuses_only_unchanged_items`: herhaal dezelfde invoer in andere volgorde: 0 elementaanroepen; verander één citaat: alleen dat item gevraagd. Wijzig elementprompt of validatorversie: alle elementitems opnieuw. Wijzig utility-provider/model/effort/base_url: opnieuw; wijzig alleen synthesis: niet.
  - `test_r23_bad_cache_is_a_miss`: beschadig een echt aangemaakt cachebestand, parametriseer onleesbaar JSON, key/parts mismatch, verkeerde formatversie en ongeldig answer; volgende run vraagt opnieuw en voert de corrupte beslissing niet uit.
  - `test_closed_answers_retry_then_fall_back`: parametriseer ontbrekend, dubbel, onbekend id, ongeldige waarde en extra veld. Precies één uitgestelde herkansing; bij tweede afwijzing blijft de oorspronkelijke soort, `, fallback` zichtbaar, geen nieuwe cache-entry. Configuratiefout propageert zonder fallback.
  - `test_decision_bundles_retry_independently`: maak via de echte inputlimiet minstens twee bundels; de eerste antwoorden worden afgewezen, herkansingen geven verschillende geldige beslissingen. Assert beide kaartuitkomsten kloppen, elke aanvraag past inclusief envelop/schema binnen het budget. Ondeelbaar te groot element krijgt fallback zonder te grote aanvraag.
  - `test_r23_trial_is_read_only`: één cachehit en één miss; geen provider calls, hit werkt, miss houdt soort, rapport noemt trial; inhoud/mtime van cache en lock blijven gelijk, ontbrekende cachemap wordt niet gemaakt.
  - `test_r23_pruning_keeps_reused_items`: echte cachehit van een 31 dagen oud item wordt aangeraakt en behouden; ongebruikte JSON ouder dan 30 dagen en tijdelijke bestanden ouder dan 1 dag verdwijnen, recente bestanden blijven. Dezelfde pipeline in trial laat inhoud en mtimes onaangeroerd.
- [ ] **Step 2: Rood draaien.** `uv run --no-sync pytest tests/code_mapper/c4/test_decisions.py tests/code_mapper/c4/test_pipeline.py -q -p no:cacheprovider` — nieuwe tests falen op ontbrekend gedrag.
- [ ] **Step 3: Runner/cache implementeren.** Canonieke sleutel bevat exact format/question/question_version/utility-ProviderIdentity/item. Item is exact de zichtbare payload zonder kort id/volgorde. Sorteer stabiele keys, seed shuffle met sha256 daarvan; bundel gemiste items per vraag binnen `effective_target`, meet de volledige aanvraag met schema/envelop. Niet afkappen; ondeelbaar te groot → fallback/rapport, geen call. Valideer de volledige bundel vóór enig item wordt opgeslagen. Hergebruik touch/prune-semantiek: JSON na 30 ongebruikte dagen, tijdelijke bestanden na 1 dag; read_only blokkeert ook mkdir/touch/prune.
- [ ] **Step 4: Elementcontrole integreren.** Promptheader `C4 step: decide`, `C4 question: c4_element`; `Items:\n` gevolgd door een JSON-lijst `{id, ...payload}`; antwoord gebruikt `decisions`. Runner roept `llm.call(step, ..., provider="utility")` aan; stepreport met `reason`, retrykey `<step>:<vraag>:<bundel>`, drain vóór consumptie. Registreer `decide` en `consolidate` en alle vijf nieuwe afwijsregels uit spec §8; houd bestaande regels. `decide` bouwt een aparte documentuitkomst met oorspronkelijke relaties; de gewone assemblage telt verdwenen eindpunten. Geen nieuwe fallback-velden in het contract; markering loopt via StepReport, trial via beslisrapport. Gebruik `draft.steps`, zodat echte fallback meetelt in de bestaande runadministratie.
- [ ] **Step 5: Caller/fixtures bijwerken.** Bereken `doc_files_for` één keer voor extractie en decide. Na extractie/drain: `raw_docs` bewaren, `decide`, aangepaste docs naar `_identify`/fingerprint/AssemblyInput, raw naar `_build_lock` en documentrapport. Prune besliscache naast documentcache alleen na niet-fatale niet-trial run. `ScriptedLLM.calls` blijft per step tellen; voeg `question_calls: Counter[str]` toe en dispatch antwoorden op `C4 question` als aanwezig, anders bestaande step. JSON-items-helper en callable default `c4_element`: `beheerder` → person, `Stripe` → external; overige gebruikte termen expliciet per test, nooit via verborgen promptmetadata. Behoud echte replay-/foutcontracten; verwijder incidentele totaalcall-/rapportvolgordeasserts, niet opnieuw vastpinnen.
- [ ] **Step 6: Groen en runtimebewijs.** Dezelfde deelrun en Project Commands, alles groen. Tijdelijke proef met echte `decide` + assemblage en scripted provider: Astro verdwijnt, tweede aanroep gebruikt cache, corrupt item vraagt opnieuw. Toon kaart/calltelling en bestandstoestand; werk changelog bij en verwijder proef.
- [ ] **Step 7: Commit.** Stage uitsluitend de Files; `feat(c4): validate documented elements with cached decisions`.

### Task 3: Dienstentabellen en zichtbare rijtermen (§3.1, §4, R21)

**Files:**

- Create: `chunkhound/code_mapper/c4/tables.py`
- Create: `chunkhound/code_mapper/prompts/c4_table.md`, `chunkhound/code_mapper/prompts/c4_row.md`
- Modify: `chunkhound/code_mapper/c4/decisions.py`
- Modify: `tests/code_mapper/c4/test_decisions.py`, `tests/code_mapper/c4/conftest.py`, `CHANGELOG.md`

**Classes:** `ServiceTable`, `TableRow`, `TableQuestion`, `RowQuestion`; consumeert `DecisionQuestion`, `DecisionStore`, `DecisionOutcome`, `DocElement`, `DocRelation`, `Citation`.

**Read:** spec §3.1, §4, §6, §11, §13; `docs/melly/models/map-structuuranalyse.md` R21/R23, §2–§5; `chunkhound/parsers/mappings/markdown.py:129-152`; `chunkhound/parsers/parser.py:126-136`; `chunkhound/services/extraction/fragments.py:103-142,234-272`; `chunkhound/code_mapper/c4/identity.py:25-26`; `chunkhound/code_mapper/c4/decisions.py` uit Taak 2; projectregels en TDD-skill.

**Tools:**

- `lsp` references op `decide` — vóór het uitbreiden van de pipeline-uitkomst
- `bash` Project Commands (pytest, smoke, ruff, mypy) — vóór commit

**Interfaces:**

- In `tables.py`: frozen `TableRow(line: int, cells: tuple[str, ...], raw: str)` en `ServiceTable(path: str, headings: tuple[str, ...], header: tuple[str, ...], rows: tuple[TableRow, ...])`; cells/header zijn zichtbare tekst, raw is de oorspronkelijke bronrij.
- `read_tables(project_root: Path, doc_files: Sequence[str]) -> list[ServiceTable]`; uitsluitend de geselecteerde bronbestanden, oorspronkelijke 1-based regels.
- `TableQuestion: DecisionQuestion[ServiceTable]`: service_list/other, fallback other; item bevat pad, koppad, header en eerste drie ruwe rijen. `RowQuestion: DecisionQuestion[tuple[ServiceTable, TableRow]]`: external/person/neither, fallback neither; item bevat pad, koppad, header en die ene ruwe rij. Niet de volledige tabel of het document.
- Bestaande `decide(...)` en `DecisionOutcome` blijven gelijk. `added` bevat uitsluitend de na elementcontrole/deduplicatie werkelijk toegevoegde rij-elementen; `report_lines` krijgt de tabel-/rijtellingen uit spec §8.

**Acceptance:**

- Promise: ook een door de open documentstap overgeslagen OpenCode CLI verschijnt met controleerbaar rijcitaat; configuratietabellen veroorzaken geen nieuwe actoren.
- Evidence: R21-tests en selectieve rijcache hieronder; source: `chunkhound/parsers/mappings/markdown.py` en `chunkhound/code_mapper/c4/identity.py`.
- Judged by: tests — zichtbare tekst, bronregels, relatieoriëntatie en ontdubbelen zijn deterministisch; herkenning van echte dienstentabellen pas run 6.

- [ ] **Step 1: Rode tests in `test_decisions.py`.**
  - `test_r21_service_row_adds_element_and_uses_relation`: documentextractie mist OpenCode CLI; table=service_list, row=external. Assert `external:opencode-cli` met naam `OpenCode CLI`, verified documentation-citaat exact op de ruwe rij, `system -> external` met titel `uses`. Parametriseer row=person: `person -> system`; row=neither en lege eerste cel leveren niets.
  - `test_r21_visible_cells_keep_source_lines`: tabel onder geneste headings met `Open**Code** CLI`, `[Tool](https://example.test)`, code span, nadruk, escaped pipe en Unicode; assert zichtbare namen zonder markup/URL, exacte bronregel en ruwe rij blijven behouden. Een tabelachtige tekst in een code fence levert niets; kolomscheiding volgt parserknopen, geen `split("|")`.
  - `test_r21_other_table_adds_nothing`: vlaggentabel → other; geen rowaanvragen en geen toegevoegde elementen/relaties.
  - `test_r21_deduplicates_after_element_check`: bestaande gelijksoortige/genormaliseerde term houdt eigen relaties, rij-uses vervalt; bestaande term na neither blokkeert rij niet; verandering van soort blokkeert alleen een rij van die nieuwe soort. Gebruik `element_id(kind, term)` voor R4, niet een tweede normalisatieregel.
  - `test_r23_only_changed_late_row_is_asked_again`: minimaal vijf rijen; verander rij vier terwijl de eerste drie en headings/header gelijk blijven. Assert geen tableaanvraag, precies die ene row wordt gevraagd; verschoven korte id's veroorzaken geen andere misses. Nieuwe headings/header of eerste-drie-rij-inhoud invalideert de tabelbeslissing.
- [ ] **Step 2: Rood draaien.** `uv run --no-sync pytest tests/code_mapper/c4/test_decisions.py -q -p no:cacheprovider` — nieuwe R21-gevallen falen.
- [ ] **Step 3: Tabellen lezen.** Gebruik de bestaande block-parser/query `pipe_table` en inline-tree-sitter-knopen voor zichtbare tekst (linklabel, code, nadruk); geen regex-stripper of nieuwe Markdown-library. Haal headings uit de AST, inclusief omsluitende context, met oorspronkelijke bytes/regels; nooit een heel document meesturen. Librarygebruik toetsen aan de geïnstalleerde, hierboven vastgelegde versies; bestaande grammar-probe opnieuw alleen bij een concrete API-onzekerheid.
- [ ] **Step 4: Vragen integreren.** Beide prompts `C4 step: decide`; `C4 question: c4_table` of `c4_row`, met dezelfde JSON-envelop als element; criteria exact spec §4, schema `DecisionAnswer`. Draai tabelvragen, dan alleen rijen van service_list; elementcontrole blijft alleen voor oorspronkelijke documentelementen. Daarna dedupliceren. Rijcitaat is `Citation(target=None, file=path, start_line=line, end_line=line, source="documentation", verified=True)` (`model.py:109-115`); de ruwe rij blijft in `TableRow.raw` en de vraagpayload, niet in een nieuw Citation-veld. Geen `verify_term` voor rij-elementen. Lock blijft uitsluitend raw-documentuitkomst bewaren.
- [ ] **Step 5: Groen en runtimebewijs.** Fixtures krijgen callable `c4_table`-default other en `c4_row`-default neither; scenario's overschrijven expliciet. Dezelfde deelrun en Project Commands. Tijdelijke proef leest een echt Markdown-bestand met `Open**Code** CLI`, voert decide/assemble uit en toont naam, rijcitaat en uses-richting; tweede run 0 decide-calls. Werk changelog bij; verwijder proef.
- [ ] **Step 6: Commit.** Stage uitsluitend de Files; `feat(c4): derive documented actors from service table rows`.

### Task 4: LLM-samenvoeging, keep_apart en volledige keten (§3.2–§4, §6–§8)

**Files:**

- Create: `chunkhound/code_mapper/c4/consolidation.py`
- Create: `chunkhound/code_mapper/prompts/c4_group.md`, `chunkhound/code_mapper/prompts/c4_survivor.md`, `chunkhound/code_mapper/prompts/c4_pair.md`
- Modify: `chunkhound/code_mapper/c4/decisions.py` (survivor/pair-strategieën)
- Modify: `chunkhound/code_mapper/c4/pipeline.py:776-789,838-853`
- Modify: `tests/code_mapper/c4/test_decisions.py`, `tests/code_mapper/c4/test_pipeline.py`, `tests/code_mapper/c4/conftest.py`, `CHANGELOG.md`

**Classes:** `MergeGroup`, `ConsolidationOutcome`, `SurvivorQuestion`, `PairQuestion`; consumeert `AssemblyInput`, `CurationState`, `Overrides`, `DecisionQuestion`, `DecisionStore`, `DecisionOutcome`, `Element`, `Relation`, `Reference`, `Citation`, `C4Model`, `C4Evidence`, `ScopeLock`, `RunInfo`, `HistoryEdge`, `MergedArrow`, `LlmSteps`.

`C4Options` uit het model blijft ongewijzigd: geen nieuwe CLI-opties. Alle andere ongewijzigde modelklassen hierboven worden alleen door de keten geconsumeerd.

**Read:** spec §1–§13; `docs/melly/models/map-structuuranalyse.md` R17–R23, §2–§5; `chunkhound/code_mapper/c4/assemble.py` en `chunkhound/code_mapper/c4/curation.py` uit Taak 1; `chunkhound/code_mapper/c4/decisions.py` uit Taak 2–3; `chunkhound/code_mapper/c4/pipeline.py:500-531,553-640,742-876`; `tests/code_mapper/c4/test_pipeline.py:131-150,220-290`; projectregels en TDD-skill.

**Tools:**

- `lsp` references op `prepare_assembly` en `AssemblyInput` — vóór integratie van de nieuwe stap
- `bash` Project Commands (pytest, smoke, ruff, mypy) — vóór commit

**Interfaces:**

- Frozen `MergeGroup(kind: Literal["person", "external"], members: tuple[str, ...], survivor: str | None = None)`; `ConsolidationOutcome(merges: dict[str, str], report_lines: tuple[str, ...])` in `consolidation.py`.
- `async propose_groups(*, state: CurationState, kind: Literal["person", "external"], project_root: Path, llm: C4Llm, retries: RetryQueue) -> list[MergeGroup]`: één ondeelbaar item per soort, payload gesorteerd op echte element-id, eigen Pydantic-model `groups: [{members: list[str]}]` met extra forbid. Leden in prompt hebben korte id's; vertaal gevalideerde uitkomst naar echte id's vóór cacheopslag, en valideer bestaande id's opnieuw bij hergebruik. Drain de eigen herkansingen vóór terugkeer, zoals `run_decisions`; rapporteer via `llm.report("consolidate", "groups")`.
- `SurvivorQuestion: DecisionQuestion[MergeGroup]` en `PairQuestion: DecisionQuestion[tuple[str, str]]` krijgen bij constructie de kandidaatmetadata uit `state`. Survivor-payload bevat leden met id/naam/omschrijving; pair-payload de vaste rollen survivor/other met naam/omschrijving/bron. Gebruik voor lid-id's een lokale aliasmapping uit de gesorteerde groepsleden, onafhankelijk van bundelpositie; `validate(..., cached=False)` vertaalt het gekozen korte lid-id naar het echte id. `cached=True` toetst het opgeslagen echte id rechtstreeks aan dezelfde groep. Fallback survivor is intern `""` (groep vervalt, nooit cachen); pair is different. Alleen same levert `other -> survivor`.
- `async consolidate(*, state: CurationState, overrides: Overrides, project_root: Path, llm: C4Llm, retries: RetryQueue) -> ConsolidationOutcome`. Vult niets in de lock; geeft uitsluitend directe merges naar bestaande overblijvende leden.
- Pipeline: `state, _ = prepare_assembly(inp)`, `consolidate`, `inp.merges = outcome.merges`, daarna bestaande `_titles` en assemblage. Dezelfde inp wordt hergebruikt; geen LLM in synchrone assemble. Nieuwe rapportregels aansluiten zonder bestaande documentrapportage te verliezen.

**Acceptance:**

- Promise: alleen als groepvoorstel, lidkeuze en paarbeslissing akkoord zijn, worden dezelfde actoren samengevoegd; keep_apart en handmatige overrides winnen. Ongewijzigde herhaling vraagt niets opnieuw.
- Evidence: R18/R19/R22/R23-tests en de lokale ketenproef hieronder; source: `chunkhound/code_mapper/c4/pipeline.py` en `chunkhound/code_mapper/c4/curation.py`.
- Judged by: tests — deterministische uitvoering van goedgekeurde regels; semantische kwaliteit van de geconfigureerde utility-LLM wordt apart door gebruiker beoordeeld in run 6.

- [ ] **Step 1: Rode consolidatiecontracttests in `test_decisions.py`.**
  - `test_r18_r19_only_same_merges_into_existing_survivor`: personen agents/AI assistant en externen Google/Google Gemini; voorstel per soort, bestaand survivor gekozen, same/different/unsure geparametriseerd. Assert alleen same samengevoegd, naam van survivor blijft, relaties/citaten/tellers/status volgen, referenties blijven, geen merges in lock. Singleton- en leeg groepsantwoord zijn geldig en veroorzaken geen lid-/paarvraag. Neem minstens één actor uit codebewijs op, zodat consolidatie niet per ongeluk alleen documentelementen behandelt.
  - `test_group_answers_retry_then_fall_back`: onbekend id, gemengde soorten, dubbel lid binnen/over groepen, survivor buiten groep. Assert afwijzing → één retry → geen samenvoeging, geen fallback in cache. Geldig leeg groepsantwoord wordt wel gecachet. Paarbeslissingen gebruiken de runnerfoutgevallen uit Taak 2.
  - `test_r22_keep_apart_blocks_direct_and_shared_target_merges`: omgekeerd paar werkt ook; tweeledengroep vervalt vóór survivor; in grotere groep met verboden paar survivor/other blijft other apart, met twee niet-survivors blijft hoogste echte id apart. Geen transitive pairinferentie; n-1 vragen tegenover survivor. Onbekend, container of niet meer aanwezig id: `C4-overrides: keep_apart ignored for <a>, <b> (<reden>)`; geldige blokkade ook rapporteren.
  - `test_oversized_group_does_not_call_provider`: één soort boven effective_target → geen group-call voor die soort, geen merges en rapportregel; andere soort werkt wel. In meerdere survivor/pair-bundels blijven retries onafhankelijk en requests binnen budget.
- [ ] **Step 2: Rode keten-/cachetests.**
  - `test_r23_consolidation_reuses_and_invalidates_per_kind`: dezelfde invoer → 0 decide/consolidate-calls en gelijke kaart; nieuw person-element → alleen person-group opnieuw, external-group hit. Nieuwe survivor-keuze invalideert alleen afhankelijke pairs. Verander bundelindeling/volgorde: bestaand survivorantwoord wijst nog naar hetzelfde echte lid. Wijzig utility-effort → alle zes vraagsoorten opnieuw; ruwe document-lock blijft herbruikbaar.
  - `test_r23_partial_failure_preserves_cached_decisions`: warm enkele items, wijzig andere, laat uitsluitend nieuwe aanvragen tweemaal falen; oude beslissingen blijven zichtbaar, nieuwe vallen terug en worden volgende run opnieuw gevraagd. Lege cache + alle zes vragen defect → kaart gelijk aan de keten zonder nieuwe stappen, met fallbackmeldingen; niet vergelijken op tijdelijke rapport-/callmetadata.
  - `test_r23_trial_consolidates_only_cached_answers`: warme group/survivor/pair-hits mogen uitvoeren, miss valt terug; geen writes/touches/prune/calls, trial zichtbaar.
  - In `test_pipeline.py`: `test_decision_report_names_changes_and_replays` toont OpenCode CLI met rijbron, ruis weg, agents → AI assistant en Google → Google Gemini bij scripted antwoorden; report noemt namen; herhaling en trial houden raw-document-lock en geven 0 nieuwe stepcalls. Behoud bestaande model/evidence/contract/replay-tests, geen wijzigingen aan AutoDoc.
- [ ] **Step 3: Rood draaien.** `uv run --no-sync pytest tests/code_mapper/c4/test_decisions.py tests/code_mapper/c4/test_pipeline.py -q -p no:cacheprovider` — nieuwe consolidatiegevallen falen.
- [ ] **Step 4: Implementeren.** Drie prompts met `C4 step: consolidate` en respectievelijk `C4 question: c4_group`, `c4_survivor`, `c4_pair`; vaste criteria uit §4 en dezelfde Items-JSON-envelop. Group apart via utility; set per soort één cache-item, versie prompt/schema/validator, geen gedeeltelijk groepsantwoord bewaren. Bronpayload gebruikt documentcitaat of pakket + eerste referentie bestand:regel; niet de hele repo. Houd mapping korte↔echte id's buiten de semantische cachekey; cachehervalidatie controleert actuele ids/lidmaatschap met dezelfde vraagvalidator, zonder fallback te bewaren.
- [ ] **Step 5: keep_apart en integratie.** Normaliseer paren symmetrisch, valideer tegen pre-curation personen/externen. Filter verboden tweegroep vóór survivor; pas na same-beslissingen de deterministische gedeeld-doelregel toe op echte id's. Verzamel namen/tellingen/waarom-apart; voeg `C4 consolidation:` en `C4 decisions:` aan rapport toe. Registreer fallback via `draft.steps`; prune group/pair/survivor bij een niet-fatale afgeronde niet-trial run, ook als afzonderlijke items fallback kregen. Conftest krijgt `c4_group`-default `{"groups": []}`; survivor/pair-antwoorden alleen expliciet waar het scenario ze nodig heeft, geen sentinel-success.
- [ ] **Step 6: Groen en lokale runtimeproef.** Dezelfde deelrun en Project Commands. Maak in de genegeerde SDD-workspace een wegwerpscript met een echt tijdelijk mini-repo, Markdown-providerstabel en de bestaande ScriptedLLM op de providergrens; voer `analyze_c4`/`finish_c4` werkelijk uit, zonder een pytest-testfunctie aan te roepen. Toon contractelementen, rijcitaat, samengevoegde relaties, raw-lockinhoud en stepcalls; herhaal, toon 0 decide/consolidate-calls; voeg keep_apart toe en toon beide personen terug. Geen netwerk/provider of AutoDoc-generatie. Bewaar stdout als bewijs, verwijder script en tijdelijke repo, werk changelog bij.
- [ ] **Step 7: Commit.** Stage uitsluitend de Files; `feat(c4): consolidate actors with cached group and pair decisions`.

## Run 6: afzonderlijke praktijkacceptatie, niet vooraf goedgekeurd (§12)

Na taskreviews en eindreview biedt de coordinator run 6 aan; dit plan verleent er geen toestemming voor. Vraag apart toestemming voor **de provider-/AutoDoc-run** en voor **het tijdelijk weghalen van de run-5-drop/merge-regels**. Bewaar de bestaande overrides en cache; gebruik de reservekopie `.scratch/omap-a5/map.lock.after-run5-with-overrides.json` als referentie, niet als stilzwijgende reset.

Na toestemming: nieuwe map naar `.scratch/omap-a6/map`, tweede ongewijzigde map naar `.scratch/omap-a6/map2`, AutoDoc alleen op map2 naar `.scratch/omap-a6/site`, daarna site-build. Leg exacte commando's, HEAD, providerconfig zonder secrets, logpaden, contractuitkomsten en calltellingen vast in het besluitenlog. Browsercontrole alleen na toestemming voor de zichtbare site; geen stil gebruik van een eigen gebruikers-tab.

Acceptatie blijft exact spec §12: OpenCode CLI met citaat uit `configuration.md:497-509`; agents/AI assistant één persoon; google → google-gemini zonder lockmerge; astro/https-endpoint/fireworks/ai-agent weg zonder drop; tweede run 0 decide/consolidate; AutoDoc en build slagen. Controleer ook de echte architectuur-/detailpagina's en hun bronverwijzingen in de gebouwde site, niet alleen exitcodes. Een model dat anders beslist is een echte mislukte acceptatie, geen reden om extra namenlijsten, hardcoded antwoorden of lockregels toe te voegen.

## Dekkings- en reviewkaart

| Spec / model          | Taak / bewijs                                                                                                                 |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| §1–§2, R17/R20        | Taak 2 elementcontrole; Taak 4 lege-cache-fallback en AI-agentpersoon                                                         |
| §3.1, R21             | Taak 3 tabellen, bronregels, zichtbare celtekst, uses en dedup na controle; Taak 2 raw lock                                   |
| §3.2–§5, R18/R19/R19a | Taak 4 groepen/survivor/pair; Taak 1 pure assemblage; Strategy-runner Taak 2                                                  |
| §6, R23               | Taak 2 cache/corruptie/versies/retries/trial, Taak 3 gewijzigde rij, Taak 4 per soort/effort/gedeeltelijke storing            |
| §7, R22               | Taak 1 lock/schema/omzetten/conflicten; Taak 4 keep_apart                                                                     |
| §8, §11               | Taak 2 en 4 rapportnamen/fallback; alle taken Project Commands en runtimebewijs                                               |
| §9–§10                | Alle ontwerpklassen staan in Classes en Interfaces; bestaande modelklassen worden in Taak 1/4 geconsumeerd, niet herontworpen |
| §12                   | Afzonderlijke run-6-poort hierboven; geen claim van praktijkacceptatie zonder die run                                         |
| §13                   | Global Constraints; geen stemmen, keep of diensten-uit-lopende-tekst                                                          |

Alle R17–R23-uitvoeringsregels zijn aan tests gekoppeld. De semantische juistheid van R17/R15 wordt niet bewezen door scripted antwoorden: die kwaliteit hoort bij run 6. Budgetschattingen uit spec §8 zijn geen benchmarkbelofte; geen tokenmeting/telemetrie toegevoegd. Na alle reviews volgt gebruikersacceptatie en `finishing-a-development-branch`; niet automatisch integreren, worktrees verwijderen of pushen.
