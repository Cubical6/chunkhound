# O-MAP deel A: C4-kaart voor AutoDoc — Implementation Plan

> **For agentic workers:** voer dit plan taak voor taak uit. Stappen gebruiken checkbox-syntax (`- [ ]`). Een taak is pas af als de tests, ruff en mypy van die taak slagen. Wijkt de code af van de spec, stop dan en leg het voor; verzin geen eigen keuze.

**Goal:** een volledige `chunkhound map` schrijft een contract dat AutoDoc zonder waarschuwing laadt, op basis van schone bronnen en één bouwsteen per map, met echte componenten in de hoofdcontainer.

**Architecture:**
- Filters in `c4/files.py` en `c4/documented.py`, met de nieuwe configuratiesectie `c4`.
- `c4/grouping.py` wordt een pure afleiding uit paden; `codeboarding/names/` vervalt.
- `c4/merge.py` krijgt compacte invoer, herstel van gedeeltelijke antwoorden, en geen verzonnen componenten.
- Nieuw: `c4/contract.py`, een pure vertaling van het interne paar naar contract versie 1, gebouwd in `finish_c4` omdat alleen daar de topics bekend zijn.
- AutoDoc: alleen `likec4_ids.py`.

**Tech Stack:** Python `>=3.10,<3.15`, pydantic 2, pytest (`asyncio_mode = "auto"`), ruff, mypy. Geen nieuwe dependencies.

**Spec:** [docs/melly/specs/2026-11-03-omap-producent-design.md](../specs/2026-11-03-omap-producent-design.md) · Besluitenlog: [2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md)

**Nulmeting (planreview, 2026-11-04):** `tests/code_mapper/c4` + `tests/services/extraction`: 459 passed. Smoke: 14 passed. `tests/autodoc/test_architecture_generation.py:245` (`test_missing_model_is_warning_not_cli_failure`) faalt al zonder wijziging met "No ChunkHound project found". Taak 0 (2026-11-04): `tests/autodoc` 116 passed en die ene fout; `tests/code_mapper tests/services/extraction tests/config`: 587 passed, 1 skipped.

## Project Commands

```bash
uv run pytest tests/code_mapper tests/services/extraction tests/config -q -n auto   # per taak
uv run pytest tests/autodoc -q -n auto                                               # Taak 9 en later
uv run pytest tests/test_smoke.py -v -n auto                                         # verplicht vóór een commit
uv run ruff check <gewijzigde bestanden>                                             # de repo heeft elders al fouten
uv run mypy chunkhound/code_mapper chunkhound/core/config chunkhound/autodoc/architecture chunkhound/api/cli/commands/code_mapper.py
uv run scripts/generate_c4_schemas.py                                                # na wijziging van c4/model.py
```

**Volledige suite (Taak 13):** `TMPDIR` op schijf, maar niet onder `~/.cache`: dat laat discoverytests falen, en `/tmp` is te klein (16 GB tmpfs, de suite gebruikt ~17 GB). Eigen map daarna opruimen. De shell is zsh: geen woordsplitsing op `$F`, en gebruik `'---'` in plaats van `echo ======`.

## Global Constraints

- **Geen providerrun.** Tests gebruiken de bestaande nep aan de providergrens (`tests/code_mapper/c4/conftest.py`). `chunkhound map` met een echte provider vraagt aparte goedkeuring.
- **Geen push.** Committen alleen zoals goedgekeurd bij de start van de uitvoering.
- **Niet aanraken:** `chunkhound research`, de index, `collect_scope_files`, topics, de fork, en AutoDoc behalve `likec4_ids.py`.
- **Testfilosofie (`AGENTS.md`):** contracttests op wat een gebruiker of de consument merkt; geen tests op privéhelpers of op de vorm van verzoeken. Breid bestaande tests uit waar die het contract al dekken.
- **`AGENTS.md`** niet wijzigen.
- **Git-status:** `.superpowers/design/c4-shared-extraction-claude-handoff.md` is niet van dit plan en blijft ongestaged.
- **Lokale `.chunkhound/map.lock.json`:** niet verwijderen. Dat hoort bij de acceptatie met provider, met aparte goedkeuring.
- **Deel B:** niet vooruitlopen. Geen processen, plaatsing, kopieën of `shared_id`.

## Review Focus

1. Volgorde: elke taak levert een groene suite op, ook al werkt de hele keten pas na Taak 11.
2. §4.4 en §4.5 van de spec tegen `merge_container`, `RetryQueue`, `_identify` en `_build_lock`.
3. Invariant 5: tweede run zonder merge-aanroep, ook met `--out` in de repository.
4. Bestaande tests die wijzigen: alleen als de spec het gedrag wijzigt.

---

### Task 0: Nulmeting en remote-config

- [ ] **Step 1:** `uv run pytest tests/autodoc -q -n auto`. Noteer het resultaat bij de nulmeting.
- [ ] **Step 2:** Bevestig de uitkomst van de planreview: `c4` als `BaseModel` raakt de terminal delta gate niet, en `REFUSED_PATHS` (`core/config/remote/pipeline.py:54–61`) is een verbodslijst. Een `BaseSettings` zou `_NESTED_BASESETTINGS_ENV_PREFIXES` nodig hebben, dus gebruik `BaseModel`.

### Task 1: Configuratie en bronselectie (spec §3.1–§3.3)

**Files:** nieuw `chunkhound/core/config/c4_config.py` (patroon: `mcp_config.py:35`); `core/config/config.py`, `c4/files.py`, `c4/documented.py`, `c4/pipeline.py`, `api/cli/commands/code_mapper.py`; tests in `tests/code_mapper/c4/test_cli_contract.py` en `test_documented.py`.

- [x] **Step 1: Rode tests.**
  - `test_test_code_is_not_a_c4_source`: bestanden in testmappen en met testnamen ontbreken in het model, ook hun manifesten. `exclude_test_code: false` zet ze terug.
  - `test_c4_exclude_applies_to_code_and_documentation`.
  - `test_scope_inside_tests_keeps_its_files`.
  - `test_map_does_not_read_its_own_output`: maak in de uitvoermap `<scope>_…`, `hyde_plan_arch_<scope>.md` en `hyde_scope_prompt_ops_<scope>.md`; alle drie vallen weg.
  - `test_hyde_still_sees_excluded_files`: `collect_scope_files` geeft ze nog steeds.
  - `test_changelog_and_hidden_directories_are_no_documentation_source`.
- [x] **Step 2:** `C4Config(BaseModel)` met `exclude: list[str] = []` en `exclude_test_code: bool = True`, als veld `Config.c4` met standaardwaarde. Geen omgevingsvariabelen of CLI-opties.
- [x] **Step 3:** Nieuwe functie `select_scope_files(...) -> ScopeSelection` met `files` en de tellingen voor het rapport. `list_scope_files` blijft bestaan met `own_output: tuple[Path, str] | None = None` en geeft `.files` terug, zodat `test_references.py:114` en `test_pipeline.py:79` werken. Filtervolgorde: testregels op paddelen onder de scope, `c4.exclude` op het relatieve pad met `compile_pattern` uit `utils/file_patterns.py`, eigen uitvoer.
- [x] **Step 4:** `analyze_c4` (`c4/pipeline.py:282`) krijgt `own_output`. De opdracht kent de uitvoermap al: ontbrekende `--out` stopt bij `commands/code_mapper.py:266–270`, en `_C4Run.out_dir` staat op `:283`, vóór de analyse.
- [x] **Step 5:** `doc_files_for(project_root, scope_path, topics, config)` met de regels uit §3.2. `finish_c4` krijgt `config: Config | None = None` (`test_pipeline.py:95` roept het zonder aan); `None` betekent de standaard-`C4Config`.
- [x] **Step 6:** Tests, ruff en mypy.

### Task 2: Systeemnaam, `cdylib` en dezelfde naam (spec §3.4)

**Files:** `c4/runtime.py`, `c4/assemble.py`; tests in `test_runtime.py`, `test_assemble.py`.

- [x] **Step 1: Rode tests.**
  - `test_system_name_prefers_selected_root_container`, met `Cargo.toml` en `pyproject.toml` in de wortel.
  - De twee terugvalstappen: eerste manifest, daarna de mapnaam.
  - `test_cdylib_beside_another_manifest_is_no_candidate`: geen `uncertain`, ook niet bij `accepted[Cargo.toml]`. Afhankelijkheden blijven meetellen.
  - `test_documented_relation_with_shared_name_links_to_container`.
- [x] **Step 2:** In `scan_runtime` de naam bepalen ná `selected`. `_manifest` leest `crate-type`; een `cdylib` in een map met nog een manifest gaat niet in `selected` of `uncertain`.
- [x] **Step 3:** In `documented_relations`: bevat een term precies het systeem en één container, kies de container.
- [x] **Step 4:** Tests, ruff en mypy.

### Task 3: Bouwsteen per map en lockversie 4 (spec §4.1, §6)

**Files:** `c4/grouping.py`, `c4/model.py`, `c4/lockfile.py`, `c4/pipeline.py` (`:33`, `:122`, `:197`, `:208–216`, `:219`, `:327`, `:444`, `:548–551`), `c4/assemble.py` (`:8`, `:133`, `:159`), `c4/merge.py` (alleen de naam in `_default_merge`), `c4/schemas/`; verwijder `c4/codeboarding/names/` en `tests/code_mapper/c4/codeboarding/names/`; tests in `test_grouping.py`, `test_lockfile.py` (`:81`), `test_pipeline.py` (`:282`, `:317`, `:588`), `test_merge.py`, `test_assemble.py`.

Dit is de grootste enkele taak, en de bestaande tests wijzigen hier het meest. Herschrijf ze; laat geen oude en nieuwe versie naast elkaar staan.

- [x] **Step 1: Rode tests.**
  - `test_each_directory_is_one_group`: alleen directe bestanden, wortel als `.`, naam van de wortel is de containernaam.
  - `test_new_file_in_known_directory_needs_no_merge_call`.
  - `test_new_directory_needs_one_merge_call`, ook onder een geclaimde map.
  - `test_v3_lock_gives_clear_message`: ook zonder object of versie.
  - Herschrijf `test_groups_are_deterministic_and_replay` en `test_explicit_root_survives_changed_file_parent_ancestry`. Verwijder `test_known_term_and_fallback_members_stay_while_new_directory_is_grouped` en `test_unplaced_and_unparseable_files_are_not_dropped`, want zonder parsen is er geen plaatsingsstap meer.
- [x] **Step 2:** `build_groups(*, files, container_of, container_roots, container_names) -> list[Group]`. Verwijder `GroupingResult` en parsen.
- [x] **Step 3:** `SCHEMA_VERSION = 4`; `tree_spec` en `group_membership` uit `ScopeLock`; `draft.grouping` wordt een lijst groepen.
- [x] **Step 4:** `_read_lock` controleert de versie vóór de validatie (§6).
- [x] **Step 5:** `_default_merge` gebruikt `group.name` als naam. Het blijft voorlopig ook bij een echte terugval gelden; dat wijzigt Taak 4.
- [x] **Step 6:** Verwijder `names/`. Behoud `source_inspector`, `hierarchy_fallback`, `models`, `config`, `LICENSE` en bestandskoppen. Controleer `pyproject.toml:170`, `references.py:14`.
- [x] **Step 7:** Schema's regenereren; tests, ruff en mypy.

### Task 4: Mislukte of onvolledige merge-stap (spec §4.5)

Komt vóór de nieuwe invoer, omdat de tests dan op de bestaande prompt kunnen draaien.

**Files:** `c4/merge.py`, `c4/pipeline.py`, `c4/assemble.py`; tests in `test_pipeline.py` (`:256`, `:373`), `test_merge.py` (`:86`).

- [x] **Step 1: Rode tests,** op de pipeline-route met de nep. Breid `test_pipeline.py:373` uit waar het kan:
  - `test_failed_merge_invents_no_components`; herschrijf `test_merge.py:86` en `test_pipeline.py:256`.
  - `test_failed_merge_is_retried_next_run`.
  - `test_failed_merge_keeps_locked_component_with_vanished_directory`: geen tombstone, geen `removed`-rand, id behouden.
  - `test_failed_merge_does_not_carry_inherited_or_living_components`: de volgende run mag niet falen op `merge.py:125–126`.
  - `test_failed_merge_keeps_base_sha`.
  - `test_other_container_is_still_locked`.
  - `test_failed_merge_warns`: `fallback_count` en de waarschuwing.
  - `test_failure_then_rename_keeps_component_id`.
- [x] **Step 2:** `MergeResult` krijgt `pending_groups: list[str]` en `failure_reason: str | None`. `_default_merge` wordt alleen voor de proefrun gebruikt; de terugval geeft `known`, lege `direct_groups`, `fallback=True` en de niet-geplaatste bouwstenen.
- [x] **Step 3:** Assemble zet `fallback` op het container-element, niet op `unit.markers`.
- [x] **Step 4:** `_identify` verwijdert voor de voorwaarden uit §4.5 de tombstone en de `removed`-rand. `_build_lock` zet het oude `LockedComponent` terug en houdt `base_sha` bij een terugval.
- [x] **Step 5:** Tests, ruff en mypy.

### Task 5: Compacte merge-invoer en prompt (spec §4.2, §4.3)

**Files:** `c4/merge.py` (`:266–275`), `c4/pipeline.py` (`:236–248`), `c4/llm.py`, prompt `code_mapper/prompts/c4_merge.md`; tests in `test_merge.py` (`:203–204`), `test_pipeline.py` (`:41`, `:407`, `:417`), `test_cli_contract.py` (`:109`). Deze tests lezen nu `name`, `links` of `container` uit de prompt en moeten mee veranderen.

- [x] **Step 1: Rode tests.**
  - `test_merge_aliases_round_trip_to_real_ids`: plaatsingen en titels met `G<n>` en `E<n>` komen terug als echte id's.
  - `test_oversized_prompt_makes_no_call_and_reports`: past de prompt ook zonder `symbols` niet, dan geen aanroep.
  - `test_new_group_can_join_existing_component`: bij een latere run koppelt het antwoord een nieuwe map aan `E<n>`.
- [x] **Step 2:** `merge_container` krijgt `project_root` en de verwijzingen per bestand. Bouw de invoer volgens §4.2 met aliassen en `file_links`, inclusief `E<n>`. Laat koppelingen naar `direct_groups` en andere containers weg. `_merge_titles` blijft de volledige koppelingen gebruiken.
- [x] **Step 3:** `symbols` volgens §4.2; alleen voor wachtende bouwstenen; niet te parsen geeft een lege lijst.
- [x] **Step 4:** `C4Llm.call` geeft `max_completion_tokens` door volgens §4.3. Budgetcontrole met `fits()` en `input_limit("synthesis")`.
- [x] **Step 5:** Prompt: C4-definitie, runtimeregel, `description` gevraagd, zin over koppelingen aanpassen, eindpunten met aliassen.
- [x] **Step 6:** Tests, ruff en mypy.

### Task 6: Antwoord verwerken en herkansen (spec §4.3, §4.4)

**Files:** `c4/merge.py`, `c4/llm.py` (`_REJECTION_RULES`, `:31`); tests in `test_merge.py` (`:51`, `:58`, `:215`, `:374`), `test_pipeline.py`.

- [x] **Step 1: Rode tests,** alle via `merge_container`, niet op `normalize_merge_answer` zelf:
  - `test_partial_answer_is_repaired_and_leftovers_retry_narrowly`: dekt onbekende groep, herhaalde plaatsing, dezelfde naam, ongeldige titelrij en de tellingen.
  - `test_ambiguous_existing_name_makes_its_groups_leftover`.
  - `test_answer_placing_nothing_is_rejected_and_retried_once`.
  - `test_truncated_answer_does_not_end_the_run`.
  - `test_input_refusal_goes_to_fallback_without_retry`.
  - `test_at_most_two_merge_calls_per_container`.
- [x] **Step 2:** `normalize_merge_answer` vervangt `check_merge_answer` en geeft plaatsingen, `leftover` en tellingen terug. Pas `_propose_components` en `_merge_titles` aan volgens §4.4; `merge.py:220` staat nu geen `proposal:`-eindpunten toe, en de smalle herkansing heeft die als `E<n>` nodig.
- [x] **Step 3:** In `attempt`: gebruik `translate_call_error` (`services/extraction/errors.py:78`). `UnreadableAnswerError` wordt `AnswerRejectedError`; `ProviderInputRefusedError` gaat direct naar de terugval. Voeg de nieuwe regelnaam toe aan `_REJECTION_RULES`.
- [x] **Step 4:** Herkansing via `RetryQueue` volgens de tabel in §4.4. De terugval geeft het tot dan toe geplaatste resultaat terug. Titels samenvoegen; bij hetzelfde paar wint de eerste.
- [x] **Step 5:** `MergeResult` krijgt de tellingen voor het rapport. `_known_components` geeft overrides voor onbekende groepen terug (`merge.py:143` negeert ze nu stil).
- [x] **Step 6:** Tests, ruff en mypy.

### Task 7: Technologie en omschrijvingen (spec §5)

**Files:** `c4/runtime.py`, `c4/model.py`, `c4/assemble.py`, `c4/schemas/`; tests in `test_output_contract.py`, `test_runtime.py`, `test_summaries.py` (`:18`), `test_merge.py` (`:21`), `test_assemble.py` (`:43`).

- [x] **Step 1: Rode tests.** Tabel uit §5: container per manifest, `cdylib` naast `pyproject.toml` geeft `Python, Rust`, component op talen, opslag uit een afhankelijkheid tegenover opslag uit configuratie; omschrijving uit het manifest voor systeem en container; omschrijving van een component uit het merge-antwoord.
- [x] **Step 2:** `Element.technology: str = ""`. `RuntimeUnit` en `RuntimeScan` krijgen omschrijving en technologie als velden met een standaardwaarde, omdat tests ze positioneel bouwen.
- [x] **Step 3:** Schema's regenereren; tests, ruff en mypy.

### Task 8: Contractvertaling (spec §7, §8)

**Files:** nieuw `c4/contract.py`; `c4/pipeline.py`; nieuwe test `tests/code_mapper/c4/test_contract.py`; `tests/autodoc` alleen lezen.

- [ ] **Step 1: Rode tests.**
  - `test_contract_loads_without_warnings`: op de fixture-uitvoer door de echte `ModelLoader`.
  - Vertaling: soorten, status, ouders, technologie, omschrijvingen, stabiele en unieke bron-id's over twee keer bouwen.
  - Weglaten: component zonder container, relatie naar weggelaten element, element zonder bron ontbreken en worden geteld; het paar behoudt ze.
  - Directe bestanden: een container bevat de bestanden van zijn component niet; een topic dat alleen componentbestanden citeert, dekt de container niet direct.
  - Labels: twee titels geven een label, één niet; te lang of weggelaten onderliggend geeft geen label.
- [ ] **Step 2:** Pure functie `build_contract(model, evidence, topics, repository_of) -> tuple[Contract, ContractCounts]`, met een eigen getypeerde vorm en geen import uit `chunkhound/autodoc`, behalve in de test. `TopicSources.topic` is al de artefactnaam (`commands/code_mapper.py:220–228`).
- [ ] **Step 3:** Weglaatregels in de volgorde van §8; lijsten gesorteerd volgens §7.4.
- [ ] **Step 4:** `repositories` krijgt alvast rijen met `NO_GIT_HEAD` en `remote_url: null`, want de loader vereist ze (`loader.py:142–151`, `:186`). Taak 9 vult ze.
- [ ] **Step 5:** `finish_c4` bouwt het contract buiten de proefrun en geeft het mee als `C4Build.contract`.
- [ ] **Step 6:** Tests, ruff en mypy.

### Task 9: Repositories en bronlinks (spec §9)

**Files:** `c4/contract.py`; tests in `test_contract.py`.

- [ ] **Step 1: Rode tests,** op echte tijdelijke Git-repository's, met `update-ref` voor `refs/remotes/origin/main`:
  - commit op `origin` geeft de URL;
  - niet gepusht, gewijzigd en niet-gevolgd geven `null` met reden, die het aantal en het eerste pad noemt, ook met spaties, niet-ASCII en na een hernoeming;
  - geen Git-map geeft `NO_GIT_HEAD`;
  - indexroot als submap en een ongeldige geneste `.git` geven `null`;
  - geneste repository krijgt een eigen regel, en haar bronnen verwijzen daarnaar;
  - `HEAD` van `.` gewijzigd tijdens de run geeft `null`;
  - tokens verdwijnen bij `https`, `http`, `ssh` en `gebruiker@host:pad`; `git@` en `ssh://git@` blijven.
- [ ] **Step 2:** Pad → repository als invoer van `build_contract`; daarna Git-gegevens via `run_git`, zonder netwerk. Een fout is nooit fataal.
- [ ] **Step 3:** Tests, ruff en mypy.

### Task 10: Publicatie en namen (spec §2)

**Files:** `c4/writer.py`, `api/cli/commands/code_mapper.py`, `api/cli/parsers/code_mapper_parser.py`; tests in `test_output_contract.py`, `test_cli_contract.py` (`:151`, `:231`).

- [ ] **Step 1: Rode tests.** Breid `test_cli_contract.py:151, 231` uit waar die het contract al dekken:
  - `test_full_run_writes_contract_and_map_pair`; de oude bewijsnaam is weg.
  - `test_trial_writes_no_contract_and_keeps_existing`.
  - `test_no_c4_output_is_byte_identical`.
  - `test_fallback_and_no_markdown_write_loadable_contract`.
- [ ] **Step 2:** Publicatievolgorde: paar, contract, lockbestand, opruimen. `_C4Run.write` schrijft `C4Build.contract`.
- [ ] **Step 3:** Helptekst; tests, ruff en mypy.

### Task 11: Rapport en stabiliteit (spec §10, invariant 5)

**Files:** `c4/pipeline.py`, `api/cli/commands/code_mapper.py`; tests in `test_cli_contract.py`.

- [ ] **Step 1: Rode tests.**
  - `test_second_run_makes_no_merge_call_and_identical_contract`, met `--out` buiten en binnen de repository. De test maakt ook de `hyde_*`-bestanden aan, omdat de testnep geen echte research doet (`test_cli_contract.py:88`).
  - `test_report_lines`: de regels uit §10, inclusief de override voor een onbekende groep.
  - `test_end_to_end_contract_links_topics_to_pages`: fixture-run gevolgd door de AutoDoc-invoer.
- [ ] **Step 2:** Rapportregels in `C4Build.report_extra`, zonder wijziging van exitcodes, met de tellingen uit Taak 1, 6 en 8.
- [ ] **Step 3:** Tests, ruff en mypy.

### Task 12: AutoDoc-naamfix (spec §11)

**Files:** `chunkhound/autodoc/architecture/likec4_ids.py`; test in `tests/autodoc/`.

- [ ] **Step 1: Rode test (altijd):** een kind met de naam van een wortelelement krijgt een andere id; id's zonder botsing blijven gelijk.
- [ ] **Step 2:** `LikeC4IdAllocator` wijst eerst id's toe aan wortelelementen en reserveert die voor alle geneste elementen. Een prototype staat lokaal in `.scratch/c4-processes-research/prototype.diff`; die map wordt niet door Git gevolgd en is geen vereiste.
- [ ] **Step 3: Forktest:** installeer het meegeleverde archief in een tijdelijke map, en draai `likec4 validate` en `likec4 build` op de schrijveruitvoer van een systeem en container met dezelfde naam, en van een kind met de naam van een extern systeem of persoon. Zonder Node wordt de test overgeslagen.
- [ ] **Step 4:** `uv run pytest tests/autodoc -q -n auto`, ruff en mypy.

### Task 13: Documenten en eindverificatie (spec §14, §15)

- [ ] **Step 1:** `docs/melly/specs/2026-10-27-map-structuuranalyse-design.md` r. 26, 50, 61, 83, 97, 120, 146–147, 153; `docs/melly/models/map-structuuranalyse.md` r. 269; AutoDoc-spec r. 23, 25 en een nieuwe rij in het AutoDoc-besluitenlog; `site/src/pages/docs/cli-reference.md:356–358`; `site/src/pages/docs/changelog.md:25`; `CHANGELOG.md`.
- [ ] **Step 2:** Lokaal `.chunkhound.json` met de sectie `c4`, niet gevolgd door Git. Controleer met `select_scope_files` zonder provider dat `docs/melly/**` en `.superpowers/**` wegvallen.
- [ ] **Step 3:** Ruff op de gewijzigde bestanden, mypy, smoke tests, en de volledige suite met de `TMPDIR`-regel. Vergelijk fouten met de nulmeting en draai elke nieuwe fout los.
- [ ] **Step 4:** Rapporteer aan de gebruiker. De acceptatie met provider uit spec §15 vraagt aparte goedkeuring en een verwijderd lockbestand. Niet zelf uitvoeren.

## Model coverage

| Spec | Taak |
|---|---|
| §2 Bestanden | 10 |
| §3.1–§3.3 Bronnen en instelling | 1, 13 |
| §3.4 Systeemnaam | 2 |
| §4.1 Bouwstenen | 3 |
| §4.2, §4.3 Invoer en grenzen | 5, 6 |
| §4.4 Antwoord verwerken | 6 |
| §4.5 Mislukte merge | 4 |
| §5 Technologie en omschrijvingen | 7 |
| §6 Lockbestand | 3, 4 |
| §7, §8 Vertaling en weglaten | 8 |
| §9 Bronlinks | 9 |
| §10 Runs en rapport | 10, 11 |
| §11 Naamfix | 12 |
| §14 Documenten | 13 |
| §15 Testlijst | elke taak; einde-tot-einde in 11, fork in 12 |
| §16 Remote-config | 0 |
