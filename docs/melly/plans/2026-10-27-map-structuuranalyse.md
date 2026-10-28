# `chunkhound map` levert de C4-structuur — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `chunkhound map` schrijft naast de topics-Markdown een C4-model en bewijs (`<safe_scope>_c4_model.json`, `<safe_scope>_c4_evidence.json`) en onthoudt indeling en identiteit in `<target_dir>/.chunkhound/map.lock.json`.

**Architecture:** Nieuw subpakket `chunkhound/code_mapper/c4/` (spec §5). Fase 1 (statische analyse, groepen, `classify`, `merge`, `titles`) draait parallel aan de bestaande topicstroom; fase 2 (`documented`, identiteit, dekking, `summaries`) gebruikt de topics. Het commando schrijft pas als alles gelukt is: Markdown, dan bewijs + model, dan lockbestand. Deterministische groepen komen uit gekopieerde CodeBoarding-code (MIT, `13adc4a0`); elke taalmodelstap gaat via `complete_structured_typed`.

**Tech Stack:** Python `>=3.10,<3.15`, pydantic 2.13.4, jsonschema 4.25.1 (al dependency, `pyproject.toml:44`), tree-sitter 0.25.2 met de grammatica's uit `pyproject.toml`, pytest 8.4.2 (`asyncio_mode = "auto"`), ruff 0.13.3, mypy 1.18.2.

**Spec:** [docs/melly/specs/2026-10-27-map-structuuranalyse-design.md](../specs/2026-10-27-map-structuuranalyse-design.md) · Model: [docs/melly/models/map-structuuranalyse.md](../models/map-structuuranalyse.md) · Besluitenlog: [docs/melly/decisions/2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md)

## Project Commands

```bash
uv run ruff format chunkhound
uv run ruff check chunkhound
uv run mypy chunkhound
uv run pytest tests/code_mapper -v
uv run pytest tests/test_smoke.py -v -n auto
```

## Global Constraints

- Python `>=3.10,<3.15` (`pyproject.toml:18`): geen `type X = ...`-statements, geen PEP 695-generics; gebruik `typing.TypeAlias`.
- Geen nieuwe dependencies (rij 20). Toegestaan: wat `pyproject.toml` al noemt (pydantic, jsonschema, tree-sitter-*, tomli onder 3.11).
- Nooit `print()` in `chunkhound/mcp_server/`; logging via `loguru.logger` zoals de rest van `chunkhound/code_mapper/`.
- Id-voorvoegsels Nederlands: `systeem:`, `container:`, `opslag:`, `extern:`, `persoon:`, `component:`; relatie-id `<van-id>-><naar-id>`. JSON-veldnamen Engels (spec §9, §10; rij 37).
- Normalisatie van termen: `slugify_kebab(term, ascii_only=True)` (`chunkhound/utils/text.py:10`).
- Markers exact: `fallback`, `trial`, `disputed`, `undescribed`, `imports_only`, `provisional`, `not_merged`, `not_classified`.
- Terugvaltitels exact: `importeert`, `roept aan`, `erft van`; melding exact: `C4: K elementen via terugval (niet opgeslagen)` (spec §6, §8). Taalmodeltitels en -labels in dezelfde taal (Nederlands) `[INFERENCE]` uit de vaste terugvaltitels.
- Gekopieerde CodeBoarding-bestanden beginnen met: `# Copied from CodeBoarding (https://github.com/CodeBoarding/CodeBoarding) commit 13adc4a0, MIT License, Copyright (c) 2025 CodeBoarding. See LICENSE in this directory.` plus één regel per aanpassing.
- Lockbestand: gesorteerde sleutels, relatieve paden met `/`, geen tijdstempels, schrijven via tijdelijk bestand + `os.replace`; nooit terugval- of proefuitkomsten (R12).
- Elke taalmodelaanroep via `LLMProvider.complete_structured_typed` (`chunkhound/interfaces/llm_provider.py:293`), binnen één semafoor van grootte `args.jobs or 4` (`chunkhound/code_mapper/service.py:122` gebruikt standaard `min(4, …)`).
- Prompts als pakketbestanden in `chunkhound/code_mapper/prompts/c4_<stap>.md` (al meegeleverd via `pyproject.toml:169`); eerste regel `C4 step: <stap>` (testdispatch).
- Tests volgen TESTING_PHILOSOPHY (`AGENTS.md`): contracten, geen helpers of mocks testen.

## Review Focus

1. **Scope zonder enig manifest of zonder git** (losse map, `NO_GIT_HEAD`): verwacht één container `provisional`, `run.renames = false`, geen crash → `test_scope_without_manifest_or_git` in Task 6 en `test_rename_detection_without_git` in Task 11.
2. **Bestand dat tree-sitter niet kan parsen of niet-UTF-8 is**: verwacht dat het bestand alleen via imports meetelt of overgeslagen wordt, de run gaat door → `test_unparsable_file_does_not_abort` in Task 5.
3. **Handgeschreven lockbestand met ongeldige JSON of onbekend `version`**: verwacht `LockfileError` met het pad (het commando maakt daar exitcode 1 van, Task 14), lockbestand niet overschreven → `test_corrupt_lockfile_is_reported_not_overwritten` in Task 3.
4. **Scope is een submap** (`map chunkhound/code_mapper`): verwacht lockbestand-sectie onder dat scopelabel, andere secties ongemoeid → `test_lock_sections_are_independent_per_scope` in Task 3.
5. **Taalmodel noemt een groep die niet bestaat of noemt er een twee keer**: verwacht afkeuring als tijdelijke fout en daarna terugval, nooit een half geplaatste groep → `test_merge_rejects_invalid_placement` in Task 9.

---

### Task 1: CodeBoarding `names/` kopiëren (deterministische groepen)

**Files:**
- Create: `chunkhound/code_mapper/c4/__init__.py` (leeg), `chunkhound/code_mapper/c4/codeboarding/__init__.py`, `chunkhound/code_mapper/c4/codeboarding/LICENSE` (letterlijk CodeBoarding `LICENSE`)
- Create: `chunkhound/code_mapper/c4/codeboarding/names/{__init__,ids,tokens,spec,inventory,frontier,replay,draft}.py`
- Modify: `pyproject.toml:165-175` (include `chunkhound/code_mapper/c4/codeboarding/LICENSE`), `pyproject.toml:214-218` (per-file-ignore `E501` voor `chunkhound/code_mapper/c4/codeboarding/**`, met commentaar "verbatim MIT copy; rewrapping would diverge from upstream")
- Test: `tests/code_mapper/c4/codeboarding/names/{__init__,conftest,test_tokens,test_spec,test_frontier,test_replay,test_draft,test_inventory}.py`

**Classes:** `Group` (bron: `TreeSpec`/`Partition`)

**Read:** spec §5 (rij `codeboarding/`) en §7 "Groepen"; model §2 `Group`; bron `/home/disorder/orca/workspaces/chunkhound/autodoc-c4-design/.scratch/codeboarding/static_analyzer/clustering/names/` (alle 8 bestanden), `.../infra/clustering_ids.py:1-25`, `.../static_analyzer/config.py:153`, `.../docs/design/name-tree.md` §2–§4, `.../tests/static_analyzer/names/`, `.../LICENSE`.

**Tools:**
- `uv run pytest tests/code_mapper/c4/codeboarding -v` — na kopiëren, bewijst dat het gedrag meekwam.
- Project Commands (ruff, mypy) — na de wijziging.

**Interfaces:**
- Produces (`chunkhound.code_mapper.c4.codeboarding.names`): `Unit(unit_id: str, language: str, names: tuple[str, ...], position: tuple[str, ...], key: tuple[str, ...], project: tuple[str, ...] | None = None)`; `TreeSpec` met `to_dict()`/`from_dict(raw)`; `ScopeSpec`; `ComponentRule`; `Partition`; `draft_tree(units, grouper, max_depth, *, machinery=(), links=None) -> TreeSpec`; `draft_scope(...)`; `replay(units, scope, role_words) -> Partition`; `role_words_for(machinery) -> frozenset[str]`; `AffinityGrouper`, `KinshipGrouper`; `Links = Mapping[tuple[str, str], int]`; `ROOT_SCOPE_ID = "root"`.

**Acceptance:**
- Promise: de groepslogica van CodeBoarding draait binnen ChunkHound zonder CodeBoarding-pakketten en met MIT-kop.
- Evidence: gekopieerde tests `test_tokens`, `test_spec`, `test_frontier`, `test_replay`, `test_draft`, `test_inventory` slagen; `grep -L "Copied from CodeBoarding" chunkhound/code_mapper/c4/codeboarding/**/*.py` geeft niets; ruff en mypy schoon.
- Judged by: tests — gedrag van de bron is al door hun tests vastgelegd.

- [ ] **Step 1: Kopieer de tests** uit `tests/static_analyzer/names/` met imports omgezet naar `chunkhound.code_mapper.c4.codeboarding.names`; `conftest.py` zonder `graph_from_layout` (CallGraph valt weg); `test_end_to_end.py` en de `units_from_graph(s)`-tests in `test_inventory.py` niet kopiëren (die functies komen niet mee). Run: `uv run pytest tests/code_mapper/c4/codeboarding -v` → FAIL (module ontbreekt).
- [ ] **Step 2: Kopieer de broncode** met deze aanpassingen, elk als kopregel vermeld: `ids.py` krijgt `ScopeId: TypeAlias = str`, `ComponentId: TypeAlias = str`, `ROOT_SCOPE_ID`, `CodeBoardingClusterIds` uit `infra/clustering_ids.py`; `ClusteringConfig.QUALIFIED_NAME_DELIMITER` wordt module-constante `QUALIFIED_NAME_DELIMITER = "."` in `tokens.py`; `inventory.py` houdt `PROJECT_MANIFESTS`, `Unit`, `Trie`, `TrieNode`, `_project_root`, `_is_project_root`, zonder `units_from_graph(s)` en zonder `CallGraph`/`normalize_repo_path`. Code verder ongewijzigd; type-annotaties toevoegen waar mypy (`disallow_untyped_defs`) dat eist.
- [ ] **Step 3: Run** `uv run pytest tests/code_mapper/c4/codeboarding -v` → PASS; Project Commands ruff + mypy → schoon.
- [ ] **Step 4: Commit** `feat(c4): kopieer CodeBoarding names/ voor deterministische groepen`.

### Task 2: CodeBoarding `source_inspector` en overervings-terugval kopiëren

**Files:**
- Create: `chunkhound/code_mapper/c4/codeboarding/{source_inspector,config,models,hierarchy_fallback}.py`
- Test: `tests/code_mapper/c4/codeboarding/test_source_inspector.py`, `tests/code_mapper/c4/codeboarding/test_hierarchy_fallback.py`

**Classes:** — (technisch; levert aan `Reference`)

**Read:** spec §7 "Aanroepen en overerving"; bron `.../static_analyzer/engine/source_inspector.py` (geheel), `.../static_analyzer/engine/hierarchy_builder.py:198-266`, `.../static_analyzer/engine/models.py:36-60`, `.../static_analyzer/config.py:10-160`, `.../tests/static_analyzer/test_source_inspector.py`, `.../tests/static_analyzer/test_hierarchy_builder.py`.

**Tools:**
- `uv run pytest tests/code_mapper/c4/codeboarding -v` — na kopiëren.

**Interfaces:**
- Produces: `SourceInspector(tree_node_budget: int = 500_000)` met `find_call_sites(file_path: Path) -> list[CallSite]`, `identifier_at(...) -> str | None`, `find_type_bases(file_path: Path) -> list[tuple[str, list[str]]]`, `get_source_line(file_path: Path, line: int) -> str | None`; `CallSite(file: str, line: int, column: int)` (1-based); `infer_bases_from_line(line: str) -> list[str]` in `hierarchy_fallback.py` (Python `class A(B, C):` zonder `metaclass=`, PHP `extends`/`implements`, logica van `_infer_hierarchy_from_source`).

**Acceptance:**
- Promise: aanroepen en overerving in Python, TS/JS/TSX/JSX en PHP worden zonder taalserver uit de broncode gelezen.
- Evidence: gekopieerde tests voor Python, JavaScript, TypeScript, TSX en PHP slagen; `test_hierarchy_fallback` dekt `class Dog(Animal):`, `class Duck(Animal, SwimmingMixin):`, `class A(metaclass=M):` → `[]`, `class Dog extends Animal implements Speakable`.
- Judged by: tests — overgenomen gedrag.

- [ ] **Step 1: Kopieer tests**: uit `test_source_inspector.py` alleen tests voor Python, JS, TS, TSX, PHP en taalonafhankelijke tests; `test_hierarchy_fallback.py` nieuw met de vier voorbeelden hierboven, asserties uit `test_hierarchy_builder.py` voor die gevallen. Run → FAIL.
- [ ] **Step 2: Kopieer** `source_inspector.py`; verwijder Kotlin (`infra.tool_registry.kotlin_language` vereist tree-sitter-language-pack ≥1.0, buiten `<1.0.0` in `pyproject.toml:51`) en de Kotlin-takken; `config.py` alleen `Language`, `NodeType`, `LANGUAGE_EXTENSIONS` voor de resterende talen; `models.py` alleen `CallSite`. `hierarchy_fallback.py` = regexlogica van `hierarchy_builder.py:198-243` als vrije functie, zonder LSP, `SymbolTable` of `CallGraph`.
- [ ] **Step 3: Run** tests → PASS; ruff + mypy schoon.
- [ ] **Step 4: Commit** `feat(c4): kopieer CodeBoarding source_inspector en overervings-terugval`.

### Task 3: Model, schema's, schrijver en lockbestand

**Files:**
- Create: `chunkhound/code_mapper/c4/model.py`, `chunkhound/code_mapper/c4/writer.py`, `chunkhound/code_mapper/c4/lockfile.py`, `chunkhound/code_mapper/c4/schemas/{c4_model,c4_evidence,map_lock}.schema.json`, `scripts/generate_c4_schemas.py`
- Modify: `pyproject.toml:165-175` (include `chunkhound/code_mapper/c4/schemas/*.json`)
- Test: `tests/code_mapper/c4/test_output_contract.py`, `tests/code_mapper/c4/test_lockfile.py`

**Classes:** `C4Model`, `C4Evidence`, `RunInfo`, `Element`, `Relation`, `MergedArrow`, `Citation`, `Reference`, `HistoryEdge`, `ScopeLock`

**Read:** spec §1 invariant 3–4, §6 uitvoer, §10 (geheel); model §2, §3; `chunkhound/utils/text.py:4-16`; `chunkhound/code_mapper/writer.py:26-95` (stijl).

**Tools:**
- docs-mcp `fetch_url https://docs.pydantic.dev/2.13/concepts/json_schema/` — vóór `model_json_schema()` en `by_alias`-gebruik.
- `uv run python scripts/generate_c4_schemas.py` — na wijziging aan `model.py`.
- `uv run pytest tests/code_mapper/c4/test_output_contract.py tests/code_mapper/c4/test_lockfile.py -v`.

**Interfaces:**
- Produces (`model.py`, Pydantic v2, `model_config = ConfigDict(populate_by_name=True, extra="forbid")`):
  - Literals: `ElementKind = Literal["system","container","storage","component","external","person"]`, `Status = Literal["found","documented"]`, `ReferenceKind = Literal["import","call","inherit"]`, `ReferenceStatus = Literal["counts","type_only","unused"]`, `SourceKind = Literal["code","configuration","documentation","topic"]`, `HistoryKind = Literal["continuation","split","merge","new","removed"]`, `RunKind = Literal["full","trial"]`, `Marker` (8 waarden), `CoverageStatus = Literal["covered","undescribed","not_computed","none"]`.
  - `RunInfo(id: str, kind: RunKind, schema_version: int, head_sha: str, scope: str, fallback_count: int, renames: bool)`; `Coverage(status, topics: list[str])`; `Element(id, kind, name, description: str | None, status, parent: str | None, markers: list[Marker], coverage: Coverage)`; `Relation(id, from_id (alias "from"), to_id (alias "to"), title, status, reference_counts: dict[ReferenceKind, int], markers)`; `MergedArrow(id, from_id, to_id, view: str, label, underlying: list[str], markers)`; `HistoryEdge(from_id, to_id, kind: HistoryKind)`; `C4Model(run, elements, relations, merged, history)`.
  - `Reference(relation: str | None, from_file (alias "from"), line: int, to: str, kind: ReferenceKind, status: ReferenceStatus)` — `to` is een bestandspad of `package:<root>`; `Citation(target: str | None, file, start_line, end_line, source: SourceKind, verified: bool)`; `C4Evidence(schema_version, run_id, references, citations, element_files: dict[str, list[str]])`.
  - Lockbestand: `LockedComponent(name, description: str | None, container: str, groups: list[str], files: list[str])`, `LockedRelation(title, fingerprint: str)`, `LockedClassification(value: str, votes: list[str | None], markers: list[Marker])`, `LockedDocumented(hashes: dict[str, str], elements: list[dict], relations: list[dict])`, `Overrides(classifications: dict[str,str] = {}, placements: dict[str,str] = {}, names: dict[str,str] = {}, descriptions: dict[str,str] = {}, titles: dict[str,str] = {}, labels: dict[str,str] = {})`, `ScopeLock(base_sha, system, containers: dict[str,str], tree_spec: dict[str, dict], components: dict[str, LockedComponent], tombstones: dict[str, str], relations: dict[str, LockedRelation], classifications: dict[str, LockedClassification], documented: LockedDocumented | None, summaries: dict[str, str], overrides: Overrides)`, `MapLock(version: int = 1, scopes: dict[str, ScopeLock])`.
  - `SCHEMA_VERSION = 1`; `class C4PairMismatchError(ValueError)`; `load_c4_pair(model_path: Path, evidence_path: Path) -> tuple[C4Model, C4Evidence]`.
- Produces (`writer.py`): `compute_run_id(model: C4Model, evidence: C4Evidence) -> str`; `write_c4_pair(*, out_dir: Path, scope_label: str, model: C4Model, evidence: C4Evidence) -> tuple[Path, Path]` (zet `run.id`/`run_id`, schrijft bewijs dan model, elk via tijdelijk bestand + `os.replace`).
- Produces (`lockfile.py`): `LOCK_RELATIVE_PATH = Path(".chunkhound/map.lock.json")`; `class LockfileError(RuntimeError)`; `read_scope_lock(target_dir: Path, scope_label: str) -> ScopeLock | None`; `write_scope_lock(target_dir: Path, scope_label: str, lock: ScopeLock) -> Path` (andere scopes en de `overrides` op schijf blijven staan).

**Acceptance:**
- Promise: model en bewijs zijn altijd een paar met dezelfde `run.id`, valideren tegen de meegeleverde schema's, en het lockbestand is stabiel en per scope.
- Evidence: `test_output_validates_against_schema` (dit deel: geconstrueerde uitvoer valideert met `jsonschema` tegen de meegeleverde bestanden; meegeleverde schema's == `model_json_schema(by_alias=True)`; `load_c4_pair()` weigert een paar met verschillende `run.id`); `test_lock_is_byte_stable` (twee keer schrijven zelfde bytes, gesorteerde sleutels, geen tijdstempel); `test_lock_sections_are_independent_per_scope`; `test_corrupt_lockfile_is_reported_not_overwritten`; `test_override_section_is_never_rewritten` (R11: `write_scope_lock` met andere `overrides` laat die op schijf staan). source: docs-mcp `fetch_url https://docs.pydantic.dev/2.13/concepts/json_schema/`.
- Judged by: tests — formaatcontract.

- [ ] **Step 1: Schrijf de falende tests**, kern:

```python
def test_output_validates_against_schema(tmp_path):
    model, evidence = sample_pair()  # klein systeem: 1 container, 2 componenten, 1 relatie
    model_path, evidence_path = write_c4_pair(out_dir=tmp_path, scope_label="/", model=model, evidence=evidence)
    assert model_path.name == "root_c4_model.json" and evidence_path.name == "root_c4_evidence.json"
    for path, schema in ((model_path, "c4_model"), (evidence_path, "c4_evidence")):
        jsonschema.validate(json.loads(path.read_text()), shipped_schema(schema))
    m, e = load_c4_pair(model_path, evidence_path)
    assert m.run.id == e.run_id
    evidence_path.write_text(evidence_path.read_text().replace(e.run_id, "0" * 64))
    with pytest.raises(C4PairMismatchError, match="chunkhound map"):
        load_c4_pair(model_path, evidence_path)
```

Run: `uv run pytest tests/code_mapper/c4/test_output_contract.py tests/code_mapper/c4/test_lockfile.py -v` → FAIL.
- [ ] **Step 2: Implementeer `model.py`**. JSON altijd met `by_alias=True`. `C4PairMismatchError`-tekst: `"C4 model and evidence come from different runs; run \`chunkhound map\` again"`.
- [ ] **Step 3: Implementeer `writer.py`**: `run.id` = `sha256(canonical(model zonder run.id) + b"\n" + canonical(evidence zonder run_id))`, `canonical` = `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()`. Bestandsnamen via `safe_scope_label` (`chunkhound/utils/text.py:4`). Uitvoer `indent=2`, `sort_keys=True`, slot-newline.
- [ ] **Step 4: Implementeer `lockfile.py`** en `scripts/generate_c4_schemas.py` (schrijft de drie schema's uit `model_json_schema(by_alias=True)`, `indent=2`, `sort_keys=True`); draai het script.
- [ ] **Step 5: Run** tests → PASS; Project Commands → schoon.
- [ ] **Step 6: Commit** `feat(c4): model, schema's, schrijver en lockbestand`.

### Task 4: Testfixture en gescripte taalmodelprovider

**Files:**
- Create: `tests/code_mapper/c4/__init__.py`, `tests/code_mapper/c4/conftest.py`, `tests/code_mapper/c4/fixture_repo/**`

**Classes:** — (testinfrastructuur)

**Read:** spec §11 eerste alinea; `tests/fixtures/fake_providers.py:20-200`; `tests/integration/code_mapper_scope_helpers.py:120-150` (patroon `LLMManager._create_provider`).

**Tools:** `uv run pytest tests/code_mapper/c4 -v` — fixtures laden zonder fout.

**Interfaces:**
- Produces (fixtures in `conftest.py`):
  - `fixture_repo(tmp_path) -> Path`: kopie van `fixture_repo/` met `git init`, één commit. Inhoud: `pyproject.toml` (`[project] name = "shop"`, `[project.scripts] shop = "shop.cli:main"`, dependency `requests`), `shop/{__init__,cli,orders,payments,storage}.py` met import, aanroep met en zonder binding, overerving, `if TYPE_CHECKING:`-import, ongebruikte import, re-export in `__init__.py` (`__all__`), een veld `data_dir: Path`; `web/package.json` (`"name": "web"`, `"bin"`), `web/src/{index,api}.ts` met `import type` en een gewone import; `admin/composer.json` (`"name": "acme/admin"`, `"bin"`), `admin/src/{Admin,Base}.php` met `extends`; `Dockerfile` met `VOLUME /data`; `templates/package.json` met `"name": "{{PACKAGE_NAME}}"`; `README.md` met de zin "Een beheerder gebruikt de webwinkel via Stripe." op regel 3.
  - `ScriptedLLM(FakeLLMProvider)`: `__init__(self, answers: Mapping[str, Callable[[str], dict] | dict])`; `complete_structured` leest `C4 step: <stap>` uit de prompt, telt `calls[stap]`, geeft het antwoord terug; een antwoord dat een `Exception` is wordt geraised.
  - `c4_llm_manager(monkeypatch, scripted: ScriptedLLM) -> LLMManager`: patcht `LLMManager._create_provider` zodat utility en synthese `scripted` zijn.
  - `default_answers() -> dict`: geldige antwoorden voor alle vijf stappen op de fixture.

**Acceptance:**
- Promise: alle C4-contracttests draaien op één echte mini-repo zonder netwerk.
- Evidence: `uv run pytest tests/code_mapper/c4 -v` verzamelt zonder fout.
- Judged by: tests — infrastructuur, geen eigen gedrag.

- [ ] **Step 1: Maak fixture en conftest** zoals hierboven.
- [ ] **Step 2: Run** `uv run pytest tests/code_mapper/c4 -v` → bestaande tests PASS, geen collectiefout.
- [ ] **Step 3: Commit** `test(c4): fixture-repo en gescripte taalmodelprovider`.

### Task 5: Statische verwijzingen (`references.py`)

**Files:**
- Create: `chunkhound/code_mapper/c4/references.py`, `chunkhound/code_mapper/c4/files.py`
- Test: `tests/code_mapper/c4/test_references.py`

**Classes:** `Reference`

**Read:** spec §7 (geheel); model §1 R1, R7, R8; `chunkhound/code_mapper/scope.py:8-70`; `chunkhound/services/research/shared/import_context.py:28-110`; `chunkhound/services/research/shared/import_resolver.py:38-145`; `chunkhound/core/detection/language_detector.py:29`; Task 2 Interfaces.

**Tools:** `uv run pytest tests/code_mapper/c4/test_references.py -v`.

**Interfaces:**
- Consumes: `SourceInspector`, `infer_bases_from_line` (Task 2); `Reference`, `ReferenceKind`, `ReferenceStatus` (Task 3).
- Produces:
  - `files.py`: `list_scope_files(*, scope_path: Path, project_root: Path, config: Config | None) -> list[str]` — roept `collect_scope_files` aan met `HydeConfig(max_scope_files=0, …)` (geen plafond, R7) en de indexing-excludes uit `config`.
  - `references.py`: `@dataclass(frozen=True) class ReferenceScan: references: list[Reference]; imports_only_files: frozenset[str]; external_sites: dict[str, list[tuple[str, int]]]` (pakketwortel → importplekken); `async def scan_references(*, project_root: Path, files: Sequence[str]) -> ReferenceScan`; `bound_names(language: Language, import_text: str) -> list[str]`; `package_root(language: Language, import_text: str) -> str | None` (Python eerste segment, niet in `sys.stdlib_module_names`; TS/JS `@scope/naam` of `naam`, niet relatief; PHP eerste twee namespace-segmenten).

**Acceptance:**
- Promise: een pijl ontstaat alleen uit een echte, gebruikte verwijzing; alles staat volledig in het bewijs.
- Evidence: `test_static_reference_rules` (R1, R7, R8): gebruikte import → `counts`; `TYPE_CHECKING`-import en `import type` → `type_only`; ongebruikte import → `unused`; re-export in `__init__.py`/`__all__` → `counts`; aanroep met import-binding → `call` naar het doelbestand; aanroep zonder binding → geen record; `class X(Base)` met gebonden `Base` → `inherit`; extern → `to == "package:requests"`; Go-bestand → alleen `import`, in `imports_only_files`. `test_unparsable_file_does_not_abort`.
- Judged by: user — domeinregels R1, R7, R8.

- [ ] **Step 1: Schrijf `test_static_reference_rules`** met per geval één assert op `(from_file, line, to, kind, status)` uit de fixture, plus `assert len(scan.references) == <aantal regels in fixture>` (R7, onafgekapt). Voeg `test_unparsable_file_does_not_abort` toe (bestand met ongeldige bytes en kapotte syntax). Run → FAIL.
- [ ] **Step 2: Implementeer** `files.py` en `references.py`. Taal via `detect_language`; imports via `ImportContextService`/`ImportResolverService` met `ParserFactory`. Als de service voor TS/JS/TSX/JSX geen imports teruggeeft, leest `references.py` de importnodes zelf uit dezelfde AST met oorspronkelijke bronposities; `import type` blijft bewijs. Gedeelde parsers/services en `mapping.resolve_import_paths` blijven ongewijzigd (gebruikersbesluit 2026-10-28). Aanroepen via `SourceInspector.find_call_sites` + `identifier_at`, doel = bestand waaraan de naam via `bound_names` gebonden is; overerving via `find_type_bases` (TS/JS/PHP) en `infer_bases_from_line` (Python). Ongebruikt = gebonden naam komt buiten de importregel niet als woord voor. Parse- of decodefout → bestand alleen in `imports_only_files` als imports lukten, anders overslaan met `logger.debug`. CPU-werk in `asyncio.to_thread`.
- [ ] **Step 3: Run** tests → PASS; ruff + mypy schoon.
- [ ] **Step 4: Commit** `feat(c4): statische verwijzingen met filters`.

### Task 6: Containers, opslag en systeem (`runtime.py`)

**Files:**
- Create: `chunkhound/code_mapper/c4/runtime.py`
- Test: `tests/code_mapper/c4/test_runtime.py`, `tests/code_mapper/c4/test_identity.py` (begint `test_component_identity_majority` met de containergevallen; Task 11 breidt dezelfde test uit)

**Classes:** `RuntimeUnit`

**Read:** spec §7 "Containers", "Opslag"; §9 "Id's", "Botsing bij een container-id"; model §1 R5; `chunkhound/parsers/mappings/toml.py:18-31` (tomllib/tomli-patroon).

**Tools:** `uv run pytest tests/code_mapper/c4/test_runtime.py -v`.

**Interfaces:**
- Consumes: `Citation` (Task 3).
- Produces: `@dataclass(frozen=True) class RuntimeUnit: id: str; name: str; manifest: str; root: str; storage: bool; markers: tuple[Marker, ...]; citations: tuple[Citation, ...]`; `@dataclass(frozen=True) class ManifestCandidate: manifest: str; name: str; line: int; reason: str` (manifest zonder standaard-startpunt → `classify`); `@dataclass(frozen=True) class StorageCandidate: key: str; file: str; line: int; evidence: str`; `@dataclass(frozen=True) class DependencyDecl: name: str; manifest: str; line: int`; `@dataclass class RuntimeScan: system_id: str; system_name: str; containers: list[RuntimeUnit]; uncertain: list[ManifestCandidate]; storage: list[StorageCandidate]; dependencies: list[DependencyDecl]; container_of: dict[str, str]`; `scan_runtime(*, project_root: Path, scope_path: Path, files: Sequence[str], locked_containers: Mapping[str, str], tombstones: Mapping[str, str], accepted: Mapping[str, bool] = {}) -> RuntimeScan` (`accepted`: uitkomst van `classify` voor `uncertain`).
- Container-id's (rij 40): `assign_container_ids(names_by_manifest: Mapping[str, str], locked: Mapping[str, str], tombstones: Mapping[str, str]) -> dict[str, str]` in `runtime.py`.

**Acceptance:**
- Promise: containers volgen runtime-grenzen, sjablonen tellen niet, en id's blijven stabiel bij naamgenoten.
- Evidence: `test_container_boundaries` (R5): fixture → `container:shop`, `container:web`, `container:acme-admin`, geen container voor `templates/package.json`; elk bestand in `container_of` bij de dichtstbijzijnde containermanifest-map; `Dockerfile`-`VOLUME /data` en `data_dir: Path` in `storage`; elke container heeft een `configuration`-citaat op de manifestregel. `test_component_identity_majority` (containerdeel, rij 40): twee manifesten met `"name": "app"` zonder lock → `container:frontend-app` en `container:backend-app`; met lock `{"frontend/package.json": "container:app"}` → bestaand id blijft, nieuwkomer `container:backend-app`; verdwenen manifestpad → tombstone. `test_scope_without_manifest_or_git`: één container met marker `provisional`, `system_id = "systeem:" + mapnaam`.
- Judged by: user — R5 en identiteit.

- [ ] **Step 1: Schrijf de drie tests.** Run → FAIL.
- [ ] **Step 2: Implementeer** `scan_runtime`: manifesten = bestanden met naam `pyproject.toml`, `package.json`, `composer.json`, `Cargo.toml`, `Dockerfile` (de formaten die spec §7 noemt); container als `[project.scripts]`, `bin`, `[[bin]]`/`src/main.rs` of Dockerfile; naam met `{{`, `}}`, `{%` of `${` → geen container; manifest met naam maar zonder startveld → `uncertain` (container alleen als `accepted[manifest]`); systeem-id uit het manifest in de scope-root, anders mapnaam; regelnummers door de sleutelregel in de tekst te zoeken.
- [ ] **Step 3: Run** → PASS; ruff + mypy.
- [ ] **Step 4: Commit** `feat(c4): containers, opslagkandidaten en systeem-id`.

### Task 7: Groepen (`grouping.py`)

**Files:**
- Create: `chunkhound/code_mapper/c4/grouping.py`
- Test: `tests/code_mapper/c4/test_grouping.py`

**Classes:** `Group`

**Read:** spec §7 "Groepen"; model §1 R2; Task 1 Interfaces; `.../docs/design/name-tree.md` §4 (incrementele run); `chunkhound/parsers/universal_parser.py:134` (`parse_file`), `chunkhound/parsers/parser_factory.py:740`.

**Tools:** `uv run pytest tests/code_mapper/c4/test_grouping.py -v`.

**Interfaces:**
- Consumes: `Unit`, `TreeSpec`, `draft_tree`, `draft_scope`, `replay`, `AffinityGrouper`, `KinshipGrouper`, `role_words_for` (Task 1); `ReferenceScan` (Task 5); `RuntimeScan.container_of` (Task 6).
- Produces: `@dataclass(frozen=True) class Group: id: str; container: str; name: str; prefix: str; files: tuple[str, ...]`; `@dataclass class GroupingResult: tree_specs: dict[str, TreeSpec]; groups: list[Group]; new_group_ids: frozenset[str]; group_membership: dict[str, dict[str, str]]`; `build_groups(*, project_root: Path, files: Sequence[str], container_of: Mapping[str, str], container_roots: Mapping[str, str], references: Sequence[Reference], stored: Mapping[str, dict], stored_membership: Mapping[str, Mapping[str, str]]) -> GroupingResult`.
- Group-id = `<container-id>/<ComponentRule.component_id>`. `container_roots` komt rechtstreeks uit `RuntimeUnit.root` (projectrelatief), nooit afgeleid uit bestandsouders of opnieuw ontdekte manifests. Eén `Unit` per bestand, `names` = `chunk.symbol` uit ChunkHounds parser (lege tuple bij parsefout), positie/key relatief aan die container-root. `group_membership` bewaart per container projectrelatieve bestandspaden met `/` → lokale `ComponentRule.component_id`; `Group.files` gebruikt dezelfde projectrelatieve paden. Koppelingen: tellende verwijzingen tussen verschillende bestanden van dezelfde container.
- Eerste run: `draft_tree(units, AffinityGrouper(), max_depth=1, links=links)`. Herhaalrun: opgeslagen root-scope replayen en bekende bestandslidmaatschappen behouden, ook bij term-/fallbackplaatsing. Gebruik `Partition.new_scopes` én werkelijk `unplaced` bestanden; vergelijk kandidaatposities met de opgeslagen bestanden om nieuwe mappen van bekende fallbackresten te onderscheiden. Nieuwe bestanden onder gevestigde prefixen blijven in hun groep. Nieuwe mappen krijgen prefix-only regels zonder termen, zodat bekende bestanden niet opnieuw stemmen; overige niet-geplaatste bestanden via `draft_scope` met `KinshipGrouper`. Nieuwe id's via `ScopeSpec.next_id`, vermeld in `new_group_ids`; sla actuele `group_membership` naast ongewijzigde TreeSpec-dictionaries op.

**Acceptance:**
- Promise: dezelfde code geeft dezelfde groepen, en bekende bestanden worden bij een herhaalrun zonder taalmodel teruggeplaatst.
- Evidence: `test_groups_are_deterministic_and_replay` (R2): twee eerste runs → identieke `groups` en `tree_specs[...].to_dict()`; elk bestand in precies één groep; met `stored` uit run 1 en één nieuw bestand onder een bekende prefix → zelfde groep, `new_group_ids` leeg; nieuw bestand in een nieuwe map → nieuwe groep in `new_group_ids`.
- Extra regressies: root-fallback en termplaatsing van bekende bestanden blijven stabiel; een nieuwe map wordt toch een nieuwe groep; tweede replay daarvan heeft dezelfde plaatsing en geen nieuwe id's. Expliciete container-root blijft gelijk wanneer de gemeenschappelijke bestandsouder verandert. JSON-lock round-trip bewaart de volledige membership, ook voor groepen rechtstreeks onder de container.
- Judged by: tests — determinisme; groepskwaliteit beoordeelt de gebruiker in Task 15.

- [ ] **Step 1: Schrijf de test.** Run → FAIL.
- [ ] **Step 2: Implementeer `build_groups`.**
- [ ] **Step 3: Run** → PASS; ruff + mypy.
- [ ] **Step 4: Commit** `feat(c4): deterministische groepen met replay`.

### Task 8: Taalmodelkoppeling en `classify`

**Files:**
- Create: `chunkhound/code_mapper/c4/llm.py`, `chunkhound/code_mapper/c4/classify.py`, `chunkhound/code_mapper/prompts/c4_classify.md`
- Test: `tests/code_mapper/c4/test_classify.py`

**Classes:** `LlmSteps` (deels: `classify`)

**Read:** spec §8 (geheel); model §1 R6, R11, R12; `chunkhound/interfaces/llm_provider.py:186-340`; `chunkhound/llm_manager.py:313-340`; `chunkhound/code_mapper/service.py:83-120`; `chunkhound/code_mapper/hyde.py:14-29` (promptladen).

**Tools:** `uv run pytest tests/code_mapper/c4/test_classify.py -v`.

**Interfaces:**
- Consumes: `ScopeLock`, `LockedClassification`, `Overrides` (Task 3); `RuntimeScan` (Task 6); `ReferenceScan.external_sites` (Task 5).
- Produces (`llm.py`):
  - `class TransientStepError(RuntimeError)`; `class AnswerRejectedError(TransientStepError)`.
  - `class C4Llm`: `__init__(self, llm_manager: LLMManager | None, *, concurrency: int, trial: bool)`; property `trial: bool` (ook waar zonder manager); `async def call(self, step: str, response_model: type[T], prompt: str, *, provider: Literal["utility", "synthesis"]) -> T` — fout waarvoor `_is_retryable_poi_error` waar is → `TransientStepError`; andere fout gaat door; telt `calls`. Elke stap kijkt eerst naar `llm.trial`: dan geen aanroep en geen `defer`, maar de deterministische uitkomst uit de terugvaltabel met marker `trial` in plaats van `fallback` (telt niet in `fallback_count`). `call` in `trial` is een programmeerfout (`RuntimeError`).
  - `class RetryQueue`: `defer(key: str, attempt: Callable[[], Awaitable[T]], fallback: Callable[[], T], apply: Callable[[T, bool], None]) -> None`; `async def drain(self) -> int` (één herpoging per item, daarna `fallback` met `apply(result, True)`; geeft aantal terugvallen).
  - `load_c4_prompt(step: str) -> str`.
- Produces (`classify.py`): `@dataclass(frozen=True) class ClassifyItem: key: str; question: Literal["dependency", "container", "storage"]; facts: dict[str, Any]`; `@dataclass(frozen=True) class Classification: value: str; votes: tuple[str | None, ...]; markers: tuple[Marker, ...]; fallback: bool`; `tally(votes: Sequence[str | None], *, default: str) -> tuple[str, tuple[Marker, ...]]`; `async def classify(items: Sequence[ClassifyItem], *, llm: C4Llm, lock: ScopeLock | None, retries: RetryQueue, seed: int = 0) -> dict[str, Classification]`. Waarden: dependency `library|external_system|storage_driver` (standaard `library`), container en storage `yes|no` (standaard `no`).

**Acceptance:**
- Promise: een dependency krijgt haar soort uit drie stemmen, een handmatige correctie wint altijd, en bekende uitkomsten kosten geen aanroep.
- Evidence: `test_dependency_vote_tally` (R6): `["storage_driver"]*3` → soort zonder marker; `["library","library","storage_driver"]` → `library` + `disputed`; `["library","external_system","storage_driver"]` → `library` + `disputed`; `["library", None, "external_system"]` (één ronde mislukt) → `library` + `disputed`. `test_override_wins` (R11): `overrides.classifications = {"requests": "storage_driver"}` → 0 aanroepen, waarde `storage_driver`. `test_locked_classification_skips_call`: item in `lock.classifications` → 0 aanroepen. `test_classify_trial_makes_no_calls` (R12): `trial=True` → 0 aanroepen, alles `library`/`no` met marker `trial`, `fallback=False`.
- Judged by: user — domeinregels R6, R11.

- [ ] **Step 1: Schrijf de tests.** Run → FAIL.
- [ ] **Step 2: Implementeer `llm.py`** en `classify.py`: één gebundelde prompt per ronde met alle nieuwe items, volgorde per ronde geschud met `random.Random(seed + ronde)`; drie rondes parallel; antwoordcontrole: elke sleutel precies één keer, waarde binnen de vaste soorten, anders `AnswerRejectedError`. Mislukte ronde telt als `None`; mislukken alle drie, dan `retries.defer`, met terugval `library`/`no` + `not_classified` + `fallback`.
- [ ] **Step 3: Run** → PASS; ruff + mypy.
- [ ] **Step 4: Commit** `feat(c4): taalmodelkoppeling en classify met stemming`.

### Task 9: `merge` en `titles`

**Files:**
- Create: `chunkhound/code_mapper/c4/merge.py`, `chunkhound/code_mapper/prompts/c4_merge.md`, `chunkhound/code_mapper/prompts/c4_titles.md`
- Test: `tests/code_mapper/c4/test_merge.py`

**Classes:** `LlmSteps` (`merge`, `titles`), `Group`

**Read:** spec §8 rijen `merge`, `titles`, "Hergebruik", "Antwoordcontrole", terugvaltabel; model §1 R2; Task 7 en 8 Interfaces.

**Tools:** `uv run pytest tests/code_mapper/c4/test_merge.py -v`.

**Interfaces:**
- Consumes: `Group`, `GroupingResult` (Task 7); `C4Llm`, `RetryQueue`, `AnswerRejectedError` (Task 8); `LockedComponent`, `LockedRelation` (Task 3).
- Produces: `@dataclass(frozen=True) class ProposedComponent: key: str; name: str; description: str | None; groups: tuple[str, ...]; markers: tuple[Marker, ...]`; `@dataclass class MergeResult: components: list[ProposedComponent]; direct_groups: list[str]; fallback: bool`; `relation_fingerprint(from_key: str, to_key: str, refs: Iterable[tuple[ReferenceKind, str]]) -> str` (sha256 over componentpaar + gesorteerde set `(soort, doelbestand)`); `fallback_title(kinds: Iterable[ReferenceKind]) -> str`; `check_merge_answer(answer: MergeAnswer, groups: Sequence[Group], container: str) -> None`; `async def merge_container(*, container: RuntimeUnit, groups: Sequence[Group], group_links: Mapping[tuple[str, str], Counter[ReferenceKind]], existing: Mapping[str, LockedComponent], placements: Mapping[str, str], llm: C4Llm, retries: RetryQueue) -> MergeResult`; `async def title_relations(*, container: str, pending: Mapping[str, Counter[ReferenceKind]], llm: C4Llm, retries: RetryQueue) -> dict[str, str]` (vingerafdruk → titel).
- `merge` stuurt alleen niet-geclaimde groepen plus bestaande componenten (naam, groepen); `overrides.placements` (groep → component-id) worden vóór de aanroep toegepast en niet aan het taalmodel gegeven. Titels die `merge` levert gaan niet nog eens naar `titles`.
- Ruling P (taak 9): `MergeResult` bevat ook `titles: dict[tuple[str, str], str]`. Nieuwe `ProposedComponent.key` is een opaak, deterministisch lokaal voorstel-id uit container + gesorteerde groeps-id's, geen definitief element-id; bestaande componenten houden hun lock-id. Titelparen gebruiken voorstelkeys of het container-id voor rechtstreeks geplaatste groepen. Antwoord-endpoints zijn `group:<exact groeps-id>`, `component:<exact bestaande key>` of letterlijk `container`; de implementatie normaliseert die via de actuele plaatsing en weigert onbekende, dubbele, zelf- of niet door positieve `group_links` ondersteunde paren. Een antwoordcomponent met de unieke exacte naam van een bestaande component voegt nieuwe groepen toe met behoud van diens key, naam en omschrijving; ambigue namen worden afgekeurd.

**Acceptance:**
- Promise: componenten zijn hele groepen binnen één container; bij een slecht of mislukt antwoord krijgt elke groep een gemarkeerd eigen component.
- Evidence: `test_merge_rejects_invalid_placement` (R2): antwoord met onbekende groep, met een groep twee keer, of met een groep uit een andere container → `AnswerRejectedError`; groep rechtstreeks onder de container (`direct_groups`) → geldig, geen extra component. `test_merge_fallback_marks_components` (R12): twee keer `TimeoutError` → per groep een component, naam uit prefix, `description is None`, markers `fallback`, `not_merged`, `provisional`. `test_fallback_titles`: `{"import"}` → `importeert`; `{"call","import"}` → `roept aan`; `{"inherit"}` → `erft van` (sterkste soort: overerving > aanroep > import).
- Judged by: user — R2.

- [ ] **Step 1: Schrijf de tests.** Run → FAIL.
- [ ] **Step 2: Implementeer `merge.py`.** Antwoordmodel `MergeAnswer(components: list[{name, description, groups}], direct: list[str], titles: list[{from, to, title}])`.
- [ ] **Step 3: Run** → PASS; ruff + mypy.
- [ ] **Step 4: Commit** `feat(c4): samenvoegen tot componenten en relatietitels`.

### Task 10: Elementen uit documentatie (`documented.py`)

**Files:**
- Create: `chunkhound/code_mapper/c4/documented.py`, `chunkhound/code_mapper/prompts/c4_documented.md`
- Test: `tests/code_mapper/c4/test_documented.py`

**Classes:** `LlmSteps` (`documented`), `Citation`

**Read:** spec §8 rij `documented`; §9 "Documentatierelaties"; model §1 R4, R10; `chunkhound/core/types/common.py:197` (`Language.MARKDOWN`); `chunkhound/code_mapper/service.py:46-58` (`poi_sections`, `metadata.sources.files`).

**Tools:** `uv run pytest tests/code_mapper/c4/test_documented.py -v`.

**Interfaces:**
- Consumes: `C4Llm`, `RetryQueue` (Task 8); `LockedDocumented` (Task 3).
- Produces: `@dataclass(frozen=True) class TopicSources: topic: str; files: tuple[str, ...]`; `doc_files_for(project_root: Path, scope_path: Path, topics: Sequence[TopicSources]) -> list[str]` (root-`README*` van de scope + geciteerde bestanden met `detect_language == Language.MARKDOWN`); `verify_quote(project_root: Path, file: str, start_line: int, end_line: int, quote: str) -> bool`; `@dataclass class DocumentedOutcome: elements: list[DocElement]; relations: list[DocRelation]; hashes: dict[str, str]; fallback: bool`; `DocElement(kind: Literal["person","external","container","component"], term: str, citation: Citation)`; `DocRelation(from_term: str, to_term: str, title: str, citation: Citation)`; `async def extract_documented(*, project_root: Path, doc_files: Sequence[str], locked: LockedDocumented | None, llm: C4Llm, retries: RetryQueue) -> DocumentedOutcome`.

**Acceptance:**
- Promise: personen en externe systemen uit documentatie verschijnen alleen met een letterlijk citaat; ongewijzigde documentatie kost geen aanroep.
- Evidence: `test_documented_quote_must_exist` (R10): citaat "Webdashboard" op `README.md:3` → afgekeurd, element niet in uitkomst, en een antwoord met alleen afgekeurde citaten telt als `AnswerRejectedError`; citaat "Een beheerder gebruikt de webwinkel via Stripe." → `persoon:` -term `beheerder` met `verified=True`, `source="documentation"`. `test_documented_reuses_on_same_hashes`: zelfde hashes in `locked` → 0 aanroepen, zelfde uitkomst; terugval zonder lock → lege uitkomst, `fallback=True`.
- Judged by: user — R10.

- [ ] **Step 1: Schrijf de tests.** Run → FAIL.
- [ ] **Step 2: Implementeer** `documented.py`: hash = sha256 van de bestandsbytes; `verify_quote` vergelijkt na het samenvoegen van witruimte; citaat moet binnen `start_line..end_line` staan. Afgekeurde items vallen weg; blijft er niets over terwijl het antwoord items had → `AnswerRejectedError`. Terugval: `locked`-uitkomst als die er is, anders leeg.
- [ ] **Step 3: Run** → PASS; ruff + mypy.
- [ ] **Step 4: Commit** `feat(c4): elementen en relaties uit documentatie met citaatcontrole`.

### Task 11: Identiteit (`identity.py`)

**Files:**
- Create: `chunkhound/code_mapper/c4/identity.py`
- Test: `tests/code_mapper/c4/test_identity.py`

**Classes:** `HistoryEdge`, `Element` (id's)

**Read:** spec §9 "Normalisatie", "Id's", "Botsing bij een nieuw component-id", "R3"; model §1 R3, R4; `chunkhound/utils/git_safe.py:80` (`run_git`); `chunkhound/code_mapper/orchestrator.py:37-47`.

**Tools:** `uv run pytest tests/code_mapper/c4/test_identity.py -v`.

**Interfaces:**
- Consumes: `ProposedComponent` (Task 9); `LockedComponent` (Task 3).
- Produces: `PREFIXES: Mapping[ElementKind, str]` (`system→"systeem:"`, `container→"container:"`, `storage→"opslag:"`, `external→"extern:"`, `person→"persoon:"`, `component→"component:"`); `element_id(kind: ElementKind, term: str) -> str`; `detect_renames(project_root: Path, base_sha: str) -> dict[str, str] | None` (`git diff -M --name-status <base_sha> HEAD`; `None` zonder git of bij onbekende sha); `@dataclass class IdentityResult: ids: dict[str, str]; history: list[HistoryEdge]; tombstones: dict[str, str]`; `assign_component_ids(*, previous: Mapping[str, frozenset[str]], current: Mapping[str, tuple[str, frozenset[str]]], renames: Mapping[str, str], taken_found: frozenset[str], documented_without_files: frozenset[str], tombstones: Mapping[str, str]) -> IdentityResult` (`current`: sleutel → (naam, bestanden)).

**Acceptance:**
- Promise: een component houdt zijn id zolang de meerderheid van zijn bestanden blijft; een opgeheven id komt nooit terug.
- Evidence: `test_component_identity_majority` (R3, R4; spec-voorbeelden; breidt de test uit Task 6 uit): (a) A 10 bestanden, B = 8 daarvan + 2 nieuw → B erft A, rand `continuation`; (b) A 10 → B 5 + C 5 → beide nieuw, A tombstone, randen `split`; (b′) A 10 → B 6 + C 4 → B erft A, C nieuw (`split`); rename `shop/orders.py → shop/order_book.py` telt als zelfde bestand; nieuw component `Orders` terwijl `component:orders` tombstone is → `component:orders-2`; nieuw component met naam van een _gedocumenteerd_ element zonder bestanden → neemt dat id over. `test_rename_detection_without_git` → `None`.
- Judged by: user — R3, R4.

- [ ] **Step 1: Schrijf de tests.** Run → FAIL.
- [ ] **Step 2: Implementeer** met R3 als `2*|A∩B| > |A| and 2*|A∩B| > |B|` over bestanden die in beide runs bestaan (na renames); geschiedenisranden bij overlap ≥10% aan één kant: één opvolger die erft → `continuation`; meerdere opvolgers → `split`; meerdere voorgangers → `merge`; geen voorganger → `new`; geen opvolger → `removed` + tombstone.
- [ ] **Step 3: Run** → PASS; ruff + mypy.
- [ ] **Step 4: Commit** `feat(c4): identiteit over runs met tombstones`.

### Task 12: Samenstellen, dekking en samengevoegde pijlen

**Files:**
- Create: `chunkhound/code_mapper/c4/assemble.py`, `chunkhound/code_mapper/c4/topic_coverage.py`, `chunkhound/code_mapper/c4/summaries.py`, `chunkhound/code_mapper/prompts/c4_summaries.md`
- Test: `tests/code_mapper/c4/test_assemble.py`, `tests/code_mapper/c4/test_summaries.py`

**Classes:** `Element`, `Relation`, `MergedArrow`, `Citation`, `C4Model`, `C4Evidence`, `LlmSteps` (`summaries`)

**Read:** spec §9 "Status", "Documentatierelaties", "Dekking", "Samengevoegde pijlen"; §10 tabel; model §1 R1, R9; C4-log rij 12, 13, 21, 22, 25, 27, 28, 29 (`/home/disorder/orca/workspaces/chunkhound/autodoc-c4-design/docs/melly/decisions/2026-10-27-autodoc-c4-map.md`); Task 3, 5, 6, 8–11 Interfaces.

**Tools:** `uv run pytest tests/code_mapper/c4/test_assemble.py tests/code_mapper/c4/test_summaries.py -v`.

**Interfaces:**
- Produces:
  - `assemble.py`: `@dataclass class AssemblyInput` (velden: `runtime: RuntimeScan`, `references: ReferenceScan`, `groups: GroupingResult`, `components: dict[str, tuple[ProposedComponent, str]]` (sleutel → (voorstel, id)), `direct_groups: dict[str, list[str]]`, `classifications: dict[str, Classification]`, `documented: DocumentedOutcome`, `titles: dict[str, str]`, `overrides: Overrides`); `assemble(inp: AssemblyInput) -> tuple[list[Element], list[Relation], C4Evidence]` (zonder `run_id`).
  - `topic_coverage.py`: `compute_coverage(*, element_files: Mapping[str, Sequence[str]], direct_files: Mapping[str, Sequence[str]], topics: Sequence[TopicSources] | None) -> dict[str, Coverage]`.
  - `summaries.py`: `derive_views(elements: Sequence[Element], relations: Sequence[Relation]) -> list[MergedArrow]` (label leeg); `summary_key(underlying: Iterable[tuple[str, str]]) -> str`; `fallback_label(titles: Sequence[str]) -> str` (gesorteerde unieke titels met `"; "`; boven 60 tekens: eerste titel + ` (+N)`, afgekapt op 60); `async def label_arrows(arrows: list[MergedArrow], *, titles_by_relation: Mapping[str, str], locked: Mapping[str, str], overrides: Mapping[str, str], llm: C4Llm, retries: RetryQueue) -> list[MergedArrow]`.

**Acceptance:**
- Promise: elk element draagt zijn bronnen en status, documentatie zet geen ongeverifieerde interne pijl op de kaart, dekking volgt gedeelde geciteerde bestanden, en pijllabels zijn kort.
- Evidence: `test_status_follows_sources` (R9): component met code-bron + README-citaat → `found`; persoon alleen uit README → `documented`; container heeft een `configuration`-citaat op zijn manifestregel; ingedeelde dependency heeft citaten op importplekken. `test_documentation_relation_rules` (R1): documentatierelatie tussen twee _aangetroffen_ componenten zonder tellende verwijzing → niet in `relations`, wel `Citation(verified=False)`; documentatierelatie persoon → container → op de kaart met status `documented`. `test_coverage_via_shared_cited_files` (C4-log rij 12, 13): component zonder topic → `undescribed`; bestand rechtstreeks onder container → alleen dekking voor die container; `topics=None` → `not_computed`; _gedocumenteerd_ element zonder bestanden → `none`. `test_merged_arrow_labels`: één onderliggende titel → overgenomen, 0 aanroepen; twee titels → aanroep; antwoord > 60 tekens → `AnswerRejectedError`; label in `locked` met zelfde `summary_key` → 0 aanroepen; `fallback_label` ≤ 60 tekens.
- Judged by: user — R1, R9.

- [ ] **Step 1: Schrijf de tests.** Run → FAIL.
- [ ] **Step 2: Implementeer `assemble.py`**: één relatie per geordend paar elementen; `Reference.relation` = id van die relatie of `None` (type-only, ongebruikt, binnen één element); bibliotheken vallen van de kaart, externe systemen en opslagdrivers worden `extern:`/`opslag:`-elementen met `package:`-verwijzingen; overrides `names`, `descriptions`, `titles` (sleutel element- of relatie-id) toegepast.
- [ ] **Step 3: Implementeer `topic_coverage.py` en `summaries.py`**: views `context` (systeem, personen, externen), `containers`, `components:<container-id>`; pijl-id `<view>:<van-id>-><naar-id>`.
- [ ] **Step 4: Run** → PASS; ruff + mypy.
- [ ] **Step 5: Commit** `feat(c4): samenstellen, dekking en samengevoegde pijlen`.

### Task 13: C4-runvolgorde (`pipeline.py`)

**Files:**
- Create: `chunkhound/code_mapper/c4/pipeline.py`
- Test: `tests/code_mapper/c4/test_pipeline.py`

**Classes:** `C4Options`, `RunInfo`, `ScopeLock`, `LlmSteps`

**Read:** spec §5 "Volgorde", §6, §8 "Fouten", §10 lockbestand; model §5 sequencediagram; model §1 R12; Interfaces van Task 3–12.

**Tools:** `uv run pytest tests/code_mapper/c4/test_pipeline.py -v`.

**Interfaces:**
- Produces: `@dataclass(frozen=True) class C4Options: c4: bool; markdown: bool; trial: bool`; `@dataclass class C4Draft` (fase-1-uitkomst); `@dataclass class C4Build: model: C4Model; evidence: C4Evidence; lock: ScopeLock | None; fallback_count: int` (`lock is None` bij `trial`); `async def analyze_c4(*, project_root: Path, scope_path: Path, scope_label: str, config: Config | None, llm: C4Llm, lock: ScopeLock | None, retries: RetryQueue) -> C4Draft` (bestanden, verwijzingen, runtime, `classify`, groepen, `merge`, `titles`); `async def finish_c4(*, draft: C4Draft, topics: Sequence[TopicSources] | None, llm: C4Llm, lock: ScopeLock | None, retries: RetryQueue, head_sha: str, kind: RunKind) -> C4Build` (`documented`, identiteit, samenstellen, dekking, `summaries`, `retries.drain()`, `RunInfo`, nieuwe `ScopeLock` zonder terugvalitems, `overrides` overgenomen uit `lock`).
- `C4Build.lock` bevat geen item met marker `fallback` of `trial` (R12); `base_sha` = `head_sha`; `run.renames` = `detect_renames(...) is not None`.
- `analyze_c4` geeft `container_roots={unit.id: unit.root for unit in runtime.containers}`, `stored=lock.tree_spec` en `stored_membership=lock.group_membership` aan `build_groups` (beide `{}` zonder lock). `C4Draft` draagt de `GroupingResult`; `finish_c4` schrijft `GroupingResult.group_membership` naar de verplichte `ScopeLock.group_membership` naast `{id: tree.to_dict()}` in `tree_spec`. Deze membership omvat ook groepen rechtstreeks onder een container, onafhankelijk van `lock.components`; geen LLM voor ongewijzigde groepen.
- Ruling P: `C4Draft` bewaart de veranderlijke `MergeResult`-objecten tot na `RetryQueue.drain()`, inclusief `titles` per lokaal voorstelkey-paar. Taak 11/13 vertaalt die keys via identiteit naar definitieve element-id's, hergebruikt deze titels zonder `titles`-aanroep voor hetzelfde paar en berekent daarna de relatiefingerprint met definitieve keys en de verwijzingen. `title_relations` behoudt het geplande `dict[str, str]` (fingerprint → titel), dat na een tijdelijke fout pas bij drain gevuld wordt; fallback-/trialmarkers en uitsluiten van de titelcache zijn verantwoordelijkheid van de pipeline, niet van die kale dictionary.

**Acceptance:**
- Promise: een tijdelijke storing levert een gemarkeerde maar volledige kaart op die niet onthouden wordt; een herhaalrun op ongewijzigde code kost niets en geeft exact dezelfde uitvoer.
- Evidence: `test_llm_failure_contract` (R12; deel pipeline): `merge` faalt twee keer met `TimeoutError` → `fallback_count > 0`, componenten met `fallback`, `C4Build.lock.components` leeg voor die container; `ValueError("bad config")` in `classify` → exceptie komt door. `test_rerun_unchanged_zero_calls_stable_output` (deel pipeline): run 2 met `lock` van run 1 → `scripted.calls` leeg, `model`, `evidence` en `lock` gelijk aan run 1. `test_trial_run_uses_lock_only`: `trial=True` met lock → 0 aanroepen, `run.kind == "trial"`, `lock is None`, coverage `not_computed`.
- Judged by: user — R12 en kosten.

- [ ] **Step 1: Schrijf de tests** op `fixture_repo` met `ScriptedLLM`. Run → FAIL.
- [ ] **Step 2: Implementeer `pipeline.py`** volgens model §5; `fallback_count` = aantal elementen met marker `fallback`.
- [ ] **Step 3: Run** → PASS; ruff + mypy.
- [ ] **Step 4: Commit** `feat(c4): runvolgorde met herpogingen na de rest`.

### Task 14: CLI-vlaggen en commando

**Files:**
- Modify: `chunkhound/api/cli/parsers/code_mapper_parser.py:55-80` (`--c4/--no-c4`, `--markdown/--no-markdown`, `BooleanOptionalAction`, standaard `True`, zelfde terugval als `--combined` zonder `BooleanOptionalAction`)
- Modify: `chunkhound/api/cli/commands/code_mapper.py:89-372`
- Test: `tests/code_mapper/c4/test_cli_contract.py`

**Classes:** `C4Options`

**Read:** spec §1 invarianten, §6 (geheel); `chunkhound/api/cli/commands/code_mapper.py` (geheel); `chunkhound/api/cli/parsers/code_mapper_parser.py`; `tests/operations/test_code_mapper_config_root.py:1-70` (commandotestpatroon); `chunkhound/autodoc/index_loader.py:17-80`; Task 3, 8, 10, 13 Interfaces.

**Tools:** `uv run pytest tests/code_mapper -v`; `uv run pytest tests/operations -k code_mapper -v` (bestaande commandotests blijven groen).

**Interfaces:**
- Consumes: `analyze_c4`, `finish_c4`, `C4Options` (Task 13); `C4Llm`, `RetryQueue` (Task 8); `TopicSources` (Task 10); `write_c4_pair` (Task 3); `read_scope_lock`, `write_scope_lock`, `LockfileError` (Task 3).
- Flow: optiecontrole (`--no-c4 --no-markdown`, `--combined --no-markdown` → `formatter.error` + `sys.exit(2)`, vóór elk ander werk) → lockbestand lezen (`LockfileError` → exit 1) → `--plan`: overview alleen als `markdown`, C4 als proef zonder `LLMManager` als `not markdown` → volledige run: `asyncio.gather(run_code_mapper_pipeline(...), analyze_c4(...))` → `TopicSources` uit `poi_sections_indexed` (topicnaam = bestandsnaam uit `build_topic_artifacts`, bestanden uit `metadata.sources.files`) → `finish_c4` → schrijven: Markdown (als `markdown`, ongewijzigde code), dan `write_c4_pair`, dan `write_scope_lock` als `kind == "full"` → melding `C4: K elementen via terugval (niet opgeslagen)` als `K > 0` → `logger.info(f"C4 LLM calls: {llm.calls}")`. Niet-tijdelijke fout in de C4-tak → `formatter.error` + `sys.exit(1)`, niets geschreven.

**Acceptance:**
- Promise: `--no-c4` verandert niets aan wat `map` vandaag doet; foute vlagcombinaties stoppen meteen; `--plan --no-markdown` werkt zonder database en zonder aanroepen; AutoDoc ziet alleen topics.
- Evidence: `test_no_c4_output_matches_upstream` (invariant 1): met gepatchte `run_code_mapper_pipeline` en `--no-c4` zijn de bestanden in `--out` byte-gelijk aan `write_code_mapper_outputs(...)` met dezelfde invoer, er is geen `*_c4_*.json` en geen lockbestand, en `scan_references` (gepatcht om te falen) wordt niet aangeroepen. `test_conflicting_output_flags_exit_2`: beide combinaties → `SystemExit.code == 2`, `run_code_mapper_pipeline` niet aangeroepen. `test_plan_no_markdown_zero_calls_no_db`: `verify_database_exists` en `_create_code_mapper_llm_manager` gepatcht om te falen → C4-paar geschreven, `run.kind == "trial"`, lockbestand byte-gelijk aan vooraf. `test_autodoc_loads_only_topics` (invariant 2): na een volledige run geeft `load_topics(out, parse_index_file(find_index_file(out)))` precies de topicbestanden, geen ontbrekende. `test_llm_failure_contract` (commandodeel): niet-tijdelijke fout → exit 1, `--out` leeg, lockbestand ongewijzigd. `test_rerun_unchanged_zero_calls_stable_output` (commandodeel): tweede commando-run → 0 C4-aanroepen, model, bewijs en lockbestand byte-gelijk. `test_output_validates_against_schema` (commandodeel): uitvoer van een volledige run valideert en elk id in het bewijs bestaat in het model.
- Judged by: user — zichtbaar CLI-gedrag.

- [ ] **Step 1: Schrijf de tests**, patroon `tests/operations/test_code_mapper_config_root.py:11-70`, met `c4_llm_manager` en `fixture_repo`. Run → FAIL.
- [ ] **Step 2: Parser**: twee vlaggen met `help`-tekst; `dest` `c4` en `markdown`.
- [ ] **Step 3: Commando** volgens de flow hierboven; bestaande code voor Markdown blijft ongewijzigd behalve dat schrijven na `finish_c4` gebeurt.
- [ ] **Step 4: Run** `uv run pytest tests/code_mapper -v` en `uv run pytest tests/operations -k code_mapper -v` → PASS; ruff + mypy.
- [ ] **Step 5: Commit** `feat(c4): map schrijft C4-model en bewijs; vlaggen --no-c4 en --no-markdown`.

### Task 15: Documentatie en smoke op deze repo

**Files:**
- Modify: `CHANGELOG.md:9` (`## [Unreleased]` → `### Added`: C4-uitvoer van `map`, vlaggen, lockbestand en `.gitignore`-advies `.chunkhound/*` + `!.chunkhound/map.lock.json`)
- Modify: `chunkhound/api/cli/parsers/code_mapper_parser.py` (alleen `help`/`epilog` als Task 14 dat nog mist)

**Classes:** —

**Read:** spec §6, §10 laatste alinea, §11 laatste alinea, §12; `CHANGELOG.md:1-25`.

**Tools:**
- `uv run pytest tests/test_smoke.py -v -n auto` — verplicht vóór commit (`AGENTS.md`).
- `uv run pytest tests/ -v` — volledige suite vóór de PR (`AGENTS.md`).
- `uv run chunkhound map . --out .scratch/c4-smoke --low --verbose` twee keer, in de execution-worktree met haar eigen `.chunkhound/db` en een echte provider uit de gebruikersconfig. Ontbreekt de index of provider: rapporteer `missing: <wat>`; de coördinator vraagt de gebruiker.

**Acceptance:**
- Promise: de gebruiker ziet op ChunkHound zelf een bruikbare eerste kaart en een tweede run zonder kosten.
- Evidence: smoke-rapport met `C4 LLM calls` en duur van run 1, `C4 LLM calls: 0` in run 2, `diff` van beide modelbestanden leeg, en de lijst componenten per container; `test_smoke.py` en volledige suite groen.
- Judged by: user — groepskwaliteit en kosten zijn een oordeel (spec §12 rij 21, 22).

- [ ] **Step 1: Schrijf de changelog-regels.**
- [ ] **Step 2: Run** smoke- en volledige suite → PASS.
- [ ] **Step 3: Draai** de twee smoke-runs; leg aanroepen, duur en componentenlijst vast in het rapport.
- [ ] **Step 4: Commit** `docs(c4): changelog voor map C4-uitvoer`.

---

## Model coverage

| Ontwerpklasse | Task |
|---|---|
| `C4Options` | 13, 14 |
| `Reference` | 3, 5 |
| `Group` | 1, 7, 9 |
| `RuntimeUnit` | 6 |
| `Element`, `Relation`, `MergedArrow`, `Citation` | 3, 12 |
| `RunInfo`, `C4Model`, `C4Evidence` | 3, 13 |
| `ScopeLock` | 3, 13 |
| `HistoryEdge` | 3, 11 |
| `LlmSteps` | 8 (`classify`), 9 (`merge`, `titles`), 10 (`documented`), 12 (`summaries`), 13 |

Technische toevoegingen buiten het diagram: `files.py` (bestandslijst), `llm.py` (`C4Llm`, `RetryQueue`), `assemble.py` (model samenstellen), `pipeline.py` (de "c4-tak" uit model §5).

| Regel | Test |
|---|---|
| R1 | `test_static_reference_rules`, `test_documentation_relation_rules` |
| R2 | `test_groups_are_deterministic_and_replay`, `test_merge_rejects_invalid_placement` |
| R3 | `test_component_identity_majority` |
| R4 | `test_component_identity_majority`, `test_documented_quote_must_exist` (`persoon:`-id) |
| R5 | `test_container_boundaries` |
| R6 | `test_dependency_vote_tally` |
| R7 | `test_static_reference_rules` (aantal records), `test_status_follows_sources` |
| R8 | `test_static_reference_rules` |
| R9 | `test_status_follows_sources` |
| R10 | `test_documented_quote_must_exist` |
| R11 | `test_override_wins`, `test_override_section_is_never_rewritten` |
| R12 | `test_llm_failure_contract`, `test_classify_trial_makes_no_calls`, `test_trial_run_uses_lock_only`, `test_plan_no_markdown_zero_calls_no_db` |
