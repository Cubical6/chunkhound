# Gedeelde extractielaag en C4-aansluiting — Implementation Plan

> **For agentic workers:** voer dit plan taak voor taak uit. Stappen gebruiken checkbox-syntax (`- [ ]`). Een taak is pas af als de tests, ruff en mypy groen zijn. Committen mag alleen met uitdrukkelijke toestemming van de gebruiker; rij 86 en 87 keuren geen commit goed.

**Goal:** `extract_documented` verwerkt de geselecteerde documentatie in begrensde bundels, via een gedeelde extractielaag zonder domeinkennis. Geldige bundeluitkomsten blijven bewaard als de run later fataal faalt. Na een kleine wijziging worden alleen de geraakte bundels opnieuw aangeroepen. Geen enkele aanvraag via de laag gaat boven de opgegeven invoerlimiet.

**Architecture:**
- Nieuw pakket `chunkhound/services/extraction/` (spec §3). Het importeert niets uit `code_mapper` of `services/research`.
- C4 levert:
  - het extractiedoel `documented`;
  - een adapter die de foutsoorten van C4 vertaalt naar die van de laag;
  - de terugval per fragment;
  - de lockregels en het rapport (spec §8).
- Research valt buiten dit plan; daarvoor komt eerst een addendum (spec §9).

**Fasering (spec §11):**
- Taken 1–4 vormen spec-fase 1, de gedeelde laag.
- Taken 5–7 vormen spec-fase 2, de C4-aansluiting.
- Na Taak 4 rapporteert de uitvoerder de tussenstand aan de gebruiker. Dat is geen goedkeuringsmoment.

**Tech Stack:** Python `>=3.10,<3.15`, pydantic 2, jsonschema, pytest (`asyncio_mode = "auto"`), ruff, mypy. Geen nieuwe dependencies.

**Spec:** [docs/melly/specs/2026-11-01-gedeelde-extractielaag-design.md](../specs/2026-11-01-gedeelde-extractielaag-design.md) · Besluitenlog: [docs/melly/decisions/2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md), rij 71–87 · Vorig plan: [2026-10-27-map-structuuranalyse.md](2026-10-27-map-structuuranalyse.md)

**Nulmeting (planreview, 2026-11-01):** `uv run pytest tests/code_mapper/c4 -q -n auto` → 410 passed.

## Project Commands

```bash
uv run ruff format chunkhound
uv run ruff check chunkhound
uv run mypy chunkhound
uv run pytest tests/services/extraction tests/code_mapper/c4 -v
uv run pytest tests/test_smoke.py -v -n auto     # verplicht vóór elke commit
uv run pytest tests/ -v                          # verplicht vóór een push naar een PR
```

## Global Constraints

- **Python:** `>=3.10,<3.15`. Geen `type X = ...` en geen PEP 695-generics; gebruik `TypeAlias` en `TypeVar`. Geen forward references tussen aanhalingstekens, tenzij dat nodig is.
- **Dependencies en logging:** geen nieuwe dependencies. Loggen gaat via `loguru.logger`, nooit via `print()`.
- **Fase 1 verandert geen providers, geen `_is_retryable_poi_error`, geen research en geen andere C4-stappen** (spec invariant 7). Buiten het nieuwe pakket en C4 `documented` is alleen dit toegestaan:
  - `LLMConfig`: twee velden, plus doorgeven aan de rolconfiguratie (Task 2);
  - `LLMManager.role_config` (Task 2);
  - `C4Llm`: een optionele `max_completion_tokens` op `call`, plus `provider_identity`, `input_limit` en `estimate_tokens` (Task 5);
  - `StepReport.record` (Task 5);
  - tellingen in `assemble` (Task 6);
  - rapportregels in `code_mapper.py` (Task 6);
  - de nieuwe limietvelden weglaten uit `_input_fingerprint` (Task 2).
- **De cache is wegwerpbaar.** Elke uitkomst gaat door `goal.validate` of `goal.recheck`.
- **Schrijven** gebeurt alleen via de eigen writer van de laag: tijdelijk bestand `.<sleutel>.<random>.tmp`, flush, `os.fsync`, `os.replace`. De bestaande `writer._write_json_atomic` wordt niet hergebruikt, want die doet geen fsync. In proefmodus wordt niets geschreven en worden geen wijzigingstijden bijgewerkt.
- **Het lockformaat blijft byte-gelijk.** Terugvalmarkeringen komen niet in `DocElement` of `DocRelation` te staan (zie Task 5).
- **Startwaarden als benoemde constanten** in `chunkhound/services/extraction/budget.py` (rij 84, spec §6.1):
  - `DEFAULT_TARGET_CHARS = 150_000`
  - `DEFAULT_MAX_INPUT_CHARS = 400_000`
  - `KNOWN_MAX_INPUT_CHARS = {"codex-cli": 1_048_576}`
  - `TOKEN_SAFETY = 1.2`
  - `CHARS_PER_TOKEN_ESTIMATE = 4`, gelijk aan `estimate_tokens` (`chunkhound/utils/token_utils.py:85–93`)
  - `FRAGMENT_DIVISOR = 4`
  - `ENVELOPE_MARGIN_CHARS = 2_000`
- **Uitvoerlimiet** van `documented`: `max(2_048, min(16_384, ceil(bundle_chars / 10)))`.
- **Opruimen** (in `store.py`): `PRUNE_UNUSED_DAYS = 30`, `PRUNE_TMP_DAYS = 1`.
- **Exacte rapportteksten, Nederlands.** De bestaande regel `C4 documented: …` blijft één regel met dezelfde opbouw. Er komen nieuwe regels bij met een **eigen voorvoegsel**:
  - `C4 documented-bundels: {r} hergebruikt, {n} nieuw, {s} gesplitst, {f} teruggevallen; fragmenten {fv} gedekt, {ff} teruggevallen`
  - `C4 documentatierelaties niet gekoppeld: {a} geen treffer, {b} meerdere treffers, {c} niet toegestaan`
- **Foutmelding bij invoerweigering:** `Invoer geweigerd door provider {provider}: aanvraag {chars} tekens, opgegeven grens {limit} tekens. Pas de invoerlimiet aan.`
- **Herkenning van invoerweigering:** de marker `input_too_large` is in deze fase **de volledige lijst** (spec §6.4); andere providers hebben geen bekende marker. Waar Codex de melding precies uitgeeft, is niet vastgesteld. Komt ze in stderr, dan wordt de fout `codex exec failed (exit N): …` (`codex_cli_provider.py:670`) en volgt herkenning. Komt ze alleen in de JSONL op stdout, dan wordt het `Invalid JSON in structured output` en dus onleesbaar. Halveren verkleint de aanvraag dan alsnog. Leg dit vast als bekende onzekerheid.
- **Testen volgens AGENTS.md:**
  - De nep zit aan de providergrens: een `LLMProvider` waarvan `complete_structured` ruwe dicts teruggeeft of echte foutteksten van providers opwerpt.
  - Er komt een gedeelde nep `ScriptedStructuredLLM` in `tests/fixtures/scripted_structured.py`: callable per prompt, telt aanroepen, legt prompts vast.
  - De bestaande C4-`ScriptedLLM` blijft bestaan.
  - Tests die de volgorde van aanroepen gebruiken, draaien met `concurrency=1`.

## Review Focus

1. **Terugval zonder lock-items:** eerste run zonder lock, één fragment faalt blijvend → in het lockbestand geldt `documented is None` en `transition is None`. Het model wordt volgens de bestaande regels gewoon geschreven, met de markering `fallback` → `test_fallback_fragment_without_lock_items_blocks_lock` (Task 5).
2. **Invoerweigering is fataal en niet tijdelijk**, ook als ze verpakt is in een tekst die `_is_retryable_poi_error` als tijdelijk herkent → `test_input_refusal_is_fatal_configuration_error` (Task 4).
3. **Halveren behoudt geldige delen:** een niet-JSON-antwoord op een bundel van 4 fragmenten laat de run niet fataal falen → `test_unreadable_answer_bisects_and_keeps_valid_parts` (Task 4).
4. **Hergebruik met verschoven regels:** de bundels van de secties ná een invoeging komen uit de cache (`from_cache=True`), met citaten die één regel verschoven zijn → `test_insert_at_top_reuses_and_shifts_citations` (Task 5).
5. **Het bestaande CLI-rapportcontract blijft gelden:** `test_llm_failure_contract` in `test_cli_contract.py` blijft ongewijzigd groen. Er is precies één regel met `C4 documented:`, en bij afkeuring staat `afgekeurd` twee keer in die regel, met `terugval`.

---

### Task 1: Bronversies en fragmenten

**Files:**
- Create: `chunkhound/services/extraction/__init__.py`, `sources.py`, `fragments.py`
- Test: `tests/services/extraction/__init__.py`, `tests/services/extraction/test_fragments.py`

**Read:** spec §2 en §4; `chunkhound/code_mapper/c4/documented.py:88–135` (`_project_file`, `verify_quote`); `chunkhound/core/detection.py` (`detect_language`).

**Interfaces (Produces):**
- `@dataclass(frozen=True) class SourceVersion: path: str; sha256: str; lines: tuple[str, ...]`. De hash wordt berekend over de bytes; regels via `str.splitlines()`.
- `read_source(project_root: Path, path: str, *, strict: bool) -> SourceVersion`. Een pad buiten het project, een pad dat geen bestand is, of (bij `strict`) geen UTF-8 → `SourceError`.
- `@dataclass(frozen=True) class FragmentIdentity: path: str; text_sha256: str; context_sha256: str; fragmentation_version: int`.
- `@dataclass(frozen=True) class Fragment: source: SourceVersion; start_line: int; end_line: int; heading_path: tuple[str, ...]`, met de property `text` en de methoden `identity() -> FragmentIdentity` en `render(fid: str, numbering: Literal["relative", "absolute"]) -> str`. De kopregel is `=== {fid} · {path}` plus `' › '.join(heading_path)`; elke regel wordt `{n}| {tekst}`.
- `fragment_document(source, *, max_chars: int, markdown: bool) -> list[Fragment]`, exact volgens spec §4. Grootte = `len(render(...))` met de breedste notatie. Is één regel te groot, dan volgt `FragmentTooLargeError(path, line)`.
- `fragment_ranges(source, ranges: Sequence[tuple[int, int]], *, max_chars: int) -> list[Fragment]`. Bij overlap volgt `ValueError`.
- `FRAGMENTATION_VERSION = 1`.

**Acceptance:**
- Promise: elke regel valt in precies één fragment, en geen enkel fragment is in weergegeven vorm groter dan `max_chars` (spec invariant 1).
- Evidence:
  - `test_every_line_in_exactly_one_fragment`: front matter, een niet-afgesloten fence met `# geen kopje`, geneste kopjes en een te grote sectie. De bereiken vormen samen precies 1..n, zonder overlap, en elke `render` is ≤ `max_chars`.
  - `test_unsplittable_line_is_reported_with_location`: een fout met pad en regelnummer.
  - `test_non_markdown_readme_ignores_hash_lines`: in `README.rst` zijn regels met `####` geen kopjesgrens.

- [ ] **Step 1:** Tests. Run → FAIL.
- [ ] **Step 2:** Implementeer.
- [ ] **Step 3:** Run → PASS; ruff en mypy.

### Task 2: Invoerlimiet, budget en configuratie

**Files:**
- Create: `chunkhound/services/extraction/budget.py`
- Modify:
  - `chunkhound/core/config/llm_config.py`:
    - de velden `utility_max_input_chars: int | None` en `utility_max_input_tokens: int | None` (`gt=0`), naast `utility_model`;
    - beide velden in `load_from_env` (`llm_config.py:1483–1550`), met env-namen `CHUNKHOUND_LLM_UTILITY_MAX_INPUT_CHARS` en `CHUNKHOUND_LLM_UTILITY_MAX_INPUT_TOKENS`;
    - in `get_provider_config_for_role("utility")` als `max_input_chars` en `max_input_tokens` (alleen als ze gezet zijn).
  - `chunkhound/llm_manager.py`: publieke `role_config(role: Literal["utility", "synthesis"]) -> Mapping[str, Any]`, een kopie van `_utility_config` of `_synthesis_config`.
  - `chunkhound/code_mapper/c4/pipeline.py:254–258`: `_input_fingerprint` laat beide nieuwe velden weg uit `config.model_dump`, zodat bestaande locks hun geschiedenis behouden.
- Test: `tests/services/extraction/test_budget.py`; een fingerprinttest in `tests/code_mapper/c4/test_pipeline.py`

**Read:** spec §6.1–6.2; `llm_config.py:206–300,926–976,1483–1550`; `chunkhound/core/config/config.py:500–515`; `chunkhound/providers/llm/base_cli_provider.py:420–431`; `chunkhound/utils/token_utils.py:85–93`.

**Interfaces (Produces):**
- `@dataclass(frozen=True) class InputLimit: max_chars: int; max_tokens: int | None`
- `resolve_input_limit(role_config: Mapping[str, Any]) -> InputLimit`: eerst `max_input_chars` uit de rolconfiguratie, dan `KNOWN_MAX_INPUT_CHARS[provider]`, anders de standaard.
- `effective_target(limit) -> int`: het minimum van `DEFAULT_TARGET_CHARS`, `limit.max_chars - ENVELOPE_MARGIN_CHARS` en, als er een tokenlimiet is, `floor(limit.max_tokens / TOKEN_SAFETY) * CHARS_PER_TOKEN_ESTIMATE - ENVELOPE_MARGIN_CHARS`.
- `max_fragment_chars(target) -> int`, gelijk aan `target // FRAGMENT_DIVISOR`.
- `measure_request(instructions: str, schema: dict[str, Any], rendered: Sequence[str]) -> int`, als bovengrens volgens spec §6.2.
- `fits(prompt: str, schema: dict[str, Any], limit: InputLimit, estimate_tokens: Callable[[str], int]) -> bool`.

**Acceptance:**
- Promise:
  - een geconfigureerde limiet heeft voorrang;
  - de doelgrootte blijft binnen de teken- én tokenlimiet;
  - de upgrade reset de geschiedenis in bestaande locks niet.
- Evidence:
  - `test_input_limit_override_from_config`: via `Config` met `CHUNKHOUND_LLM_UTILITY_MAX_INPUT_CHARS=50000` en provider `codex-cli` geldt `max_chars == 50_000` en `effective_target == 48_000`. Zonder override: 1.048.576. Bij een onbekende provider: 400.000. Met `max_input_tokens=10_000` geldt `effective_target ≤ 31_332`.
  - `test_new_limit_fields_do_not_change_input_fingerprint`: dezelfde fingerprint met en zonder de nieuwe velden.

- [ ] **Step 1:** Tests. Run → FAIL.
- [ ] **Step 2:** Implementeer.
- [ ] **Step 3:** Run → PASS; ruff en mypy; `uv run pytest tests -k "llm_config or config" -v` blijft groen.

### Task 3: Bestandsopslag

**Files:**
- Create: `chunkhound/services/extraction/store.py`
- Test: geen eigen testbestand. Het gedrag wordt bewezen via `run_extraction` (Task 4) en C4 (Task 5), volgens de testfilosofie.

**Read:** spec §7.

**Interfaces (Produces):**
- `@dataclass(frozen=True) class ProviderIdentity: provider: str; model: str; reasoning_effort: str | None; base_url: str | None`
- `bundle_key(*, goal: str, goal_version: str, provider: ProviderIdentity, max_completion_tokens: int, members: Sequence[FragmentIdentity]) -> str`. Dit is een sha256 over canonieke JSON (`sort_keys=True, separators=(",", ":"), ensure_ascii=False`), inclusief `FORMAT_VERSION = 1` en `NOTATION_VERSION = 1`.
- `@dataclass(frozen=True) class StoredBundle: key: str; key_parts: dict[str, Any]; members: tuple[FragmentIdentity, ...]; parts: dict[int, dict[str, Any]]`
- `class ExtractionStore`:
  - `__init__(root: Path, goal: str, *, read_only: bool)`
  - `candidates() -> Iterator[StoredBundle]`. Leest alleen `*.json`. Onleesbare bestanden, een onbekend formaat, of een sleutel die niet uit `key_parts` volgt, worden gelogd en overgeslagen.
  - `put(bundle) -> None`. Atomair, met fsync. Een no-op bij `read_only`.
  - `touch(key) -> None`. Een no-op bij `read_only`.
  - `prune(now: float) -> None`. Een no-op bij `read_only`.

- [ ] **Step 1:** Implementeer. Run ruff en mypy.

### Task 4: Runner, foutindeling, halveren en provideradapter

**Files:**
- Create: `chunkhound/services/extraction/errors.py`, `bundles.py`, `runner.py`, `provider_call.py`
- Create (test): `tests/fixtures/scripted_structured.py`, `tests/services/extraction/test_runner.py`. Het testdoel is minimaal: elk fragment geeft `{"lines": <aantal regels>}`, en de validator controleert dat aantal tegen het fragment.

**Read:** spec §3, §5 en §6.3–6.4; `chunkhound/code_mapper/service.py:95–119`; `chunkhound/providers/llm/base_cli_provider.py:396–465`; `chunkhound/providers/llm/codex_cli_provider.py:195–216,660–675`; `chunkhound/providers/llm/anthropic_llm_provider.py:935–946`; `chunkhound/utils/json_extraction.py:76–107`; `chunkhound/interfaces/llm_provider.py:293–340`.

**Interfaces (Produces):**
- `errors.py`:
  - `InputRejectedError(provider, chars, limit)`, fataal, met de exacte Nederlandse melding;
  - `UnreadableAnswerError`;
  - `TransientCallError`;
  - `INPUT_REJECTED_MARKERS = ("input_too_large",)`;
  - `UNREADABLE_MARKERS = ("invalid json in structured output", "structured output truncated", "llm response truncated")`;
  - `has_marker(exc, markers) -> bool`, dat de hele keten via `__cause__`/`__context__` afloopt.
- `class StructuredCall(Protocol)`, met:
  - `async def __call__(self, prompt: str, response_model: type[BaseModel], max_completion_tokens: int) -> BaseModel`, dat alleen `InputRejectedError`, `UnreadableAnswerError`, `TransientCallError` of een fatale fout werpt;
  - `def estimate_tokens(self, text: str) -> int`.
- `provider_call.py`: `ProviderStructuredCall(provider: LLMProvider, *, provider_name: str, is_transient: Callable[[BaseException], bool])`. De volgorde van indeling is:
  1. invoermarker → `InputRejectedError`;
  2. `json.JSONDecodeError`, `pydantic.ValidationError` of `jsonschema.ValidationError` in de keten, of een onleesbaarheidsmarker → `UnreadableAnswerError`;
  3. `is_transient` → `TransientCallError`;
  4. anders opnieuw opwerpen.

  Deze adapter is bedoeld voor research (later). C4 krijgt een eigen adapter in Task 5.
- `class ExtractionGoal(Protocol[PartT])`, volgens spec §3, met:
  - `version` als vaste sha256 over instructies, `part_model().model_json_schema()` en `VALIDATOR_VERSION`;
  - `validate`/`recheck`, die `PartT | Rejected(rule: str)` teruggeven; `rule` is een vaste tekst van de toepassing.
- Het antwoordmodel staat **per doel vast**: `{"fragments": [{"id": str, "part": part_model}]}`, één keer gebouwd met `pydantic.create_model`.
- `bundles.py`:
  - `select_reusable(...)`: multiset-matching, deterministische keuze (de meeste nog niet gedekte leden, daarna de laagste sleutel), vertaling van regels en daarna `recheck`;
  - `pack(fragments, target, measure) -> list[list[Fragment]]`;
  - `split_to_fit(bundle, target, measure)`, dat aangeleverde bundels vóór verzending halveert.
- `runner.py`: `async def run_extraction(goal, fragments, *, call, provider, limit, store, concurrency: int, bundles=None, order_hint=None, on_attempt=None) -> ExtractionResult[PartT]`.
  - `on_attempt(AttemptRecord(bundle_key, outcome: Literal["accepted", "rejected", "unreadable", "transient"], rule: str | None))` wordt na elke aanroep aangeroepen.
  - `ExtractionResult` bevat `parts: dict[int, Valid | Failed]` (index in `fragments`), `failed_bundles: dict[str, tuple[int, ...]]` (bundelsleutel → indexen van de fragmenten die daarin mislukten) en `counts`.
  - Gedrag:
    - eerst hergebruiken, dan inpakken;
    - een semafoor van `concurrency`;
    - controle tegen het budget vóór verzending (te groot = `AssertionError`, een programmeerfout);
    - halveren bij onleesbaar;
    - per fragment `validate`;
    - geldige leden direct `put`;
    - bij een fatale fout worden lopende taken geannuleerd en wordt de fout opnieuw opgeworpen;
    - `store.prune` wordt **niet** door de runner aangeroepen.

**Acceptance:**
- Promise:
  - geen aanvraag boven de limiet;
  - halveren behoudt geldige delen;
  - invoerweigering is fataal;
  - opgeslagen bundels overleven een fatale fout en worden hergebruikt;
  - een beschadigde cache is een gemiste treffer;
  - aangeleverde bundels worden nooit ingekort.
- Evidence (nep: `ScriptedStructuredLLM` via `ProviderStructuredCall`, `concurrency=1`):
  - `test_requests_never_exceed_limit`: geparametriseerd met `max_chars` = 1.048.576 en = 60.000, over een bronset van 941.516 bytes in `tmp_path`. Elke ontvangen prompt plus `json.dumps(schema, indent=2)` blijft ≤ de limiet, en elke regel is gedekt.
  - `test_input_refusal_is_fatal_configuration_error`: geparametriseerd met `RuntimeError("codex exec failed (exit 1): … input_too_large … actual_chars: 1100748, max_chars: 1048576")` en `RuntimeError("LLM structured completion failed: input_too_large")`. Beide geven `InputRejectedError` met grootte en grens. Voor de tweede tekst geeft `_is_retryable_poi_error` `True`, wat de volgorde van indeling bewijst.
  - `test_unreadable_answer_bisects_and_keeps_valid_parts`: de eerste aanroep over 4 fragmenten werpt `RuntimeError("Invalid JSON in structured output: …")`. Daarna volgen geldige antwoorden: 4× `Valid`, `counts.split ≥ 1`, geen uitzondering.
  - `test_valid_bundles_survive_fatal_error_and_are_reused`: een fatale `ValueError` bij de tweede aanroep. Na de run staat bundel 1 in de opslag. Run 2 roept bundel 1 niet aan.
  - `test_corrupt_cache_is_a_miss_and_changes_only_cost`: een afgekapt JSON-bestand en een bestand met een vervalste sleutel. De run slaagt, met dezelfde delen als zonder cache (deterministische nep).
  - `test_supplied_oversized_bundle_is_split_not_truncated`: een aangeleverde bundel boven de doelgrootte wordt verdeeld over ≥ 2 aanroepen, en elke fragmenttekst staat volledig in een prompt.

- [ ] **Step 1:** Maak de nep en schrijf de tests. Run → FAIL.
- [ ] **Step 2:** Implementeer.
- [ ] **Step 3:** Run → PASS; ruff en mypy. Rapporteer de tussenstand aan de gebruiker.

### Task 5: C4 `documented` op de laag

**Files:**
- Modify:
  - `chunkhound/code_mapper/c4/documented.py`
  - `chunkhound/code_mapper/c4/llm.py`:
    - `call(..., max_completion_tokens: int | None = None)`, doorgegeven aan `complete_structured_typed` als het gezet is;
    - `provider_identity(role)` en `input_limit(role)` via `LLMManager.role_config`;
    - `estimate_tokens(text)` via de utilityprovider;
    - `StepReport.record(outcome: str)`;
    - nieuwe afkeuringsregels in `_REJECTION_RULES`: `"every fragment id must occur exactly once"` en `"citation outside its fragment"`.
  - `chunkhound/code_mapper/c4/pipeline.py`: `finish_c4` sluit `order_hint` aan op `topics`, voert de terugval per fragment uit, registreert `draft.steps.fallbacks` en roept na de drain `store.prune` aan, maar alleen buiten proefmodus. De `fallback`-markering op elementen gebruikt `fallback_citations`.
  - `chunkhound/code_mapper/prompts/c4_documented.md`: de eerste regel blijft `C4 step: documented`. De instructies gaan over fragmenten met id's en regelnummers per fragment, zonder `file`.
  - `tests/code_mapper/c4/conftest.py`: de helper `documented_answer(per_fragment: Callable[[str, list[str]], dict] | dict) -> Callable[[str], dict]`. Die leest de `=== F<n> · <pad>`-koppen en de regels uit de prompt en geeft per id een deel terug. `default_answers()["documented"]` wordt `documented_answer(...)` met dezelfde termen als nu.
  - `tests/code_mapper/c4/test_documented.py`, `test_pipeline.py` (r. 125 en 144), `test_cli_contract.py` (r. 261–266) en `test_assemble.py` (r. 83–91): aangepast aan de vorm per fragment en aan de standaardwaarden van de nieuwe velden. Hun belofte blijft gelijk.

**Read:**
- spec §8;
- `documented.py` in zijn geheel;
- `llm.py` in zijn geheel;
- `pipeline.py:75–100,485–505,520–560,569–623`;
- `assemble.py:239–300`;
- `tests/code_mapper/c4/conftest.py`;
- `test_documented.py`;
- `test_cli_contract.py:240–300`.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `DocumentedOutcome(elements, relations, hashes, fallback: bool, fallback_fragments: frozenset[tuple[str, int, int]] = frozenset(), fallback_citations: frozenset[tuple[str, int, int]] = frozenset(), counts: ExtractionCounts | None = None)`.
    - De volgorde van de vier bestaande velden blijft gelijk, zodat positionele constructie blijft werken.
    - `fallback` is waar als `fallback_fragments` niet leeg is.
    - `DocElement` en `DocRelation` veranderen **niet**.
  - `_DocumentedGoal` implementeert `ExtractionGoal`, met `line_numbering="relative"`. `validate` en `recheck` volgen de regels van `check_documented_answer`, beperkt tot de eigen fragmentregels, met de regelteksten hierboven.
  - **`_C4Call`, de adapter rond `C4Llm.call`**, vertaalt:
    - invoermarker → `InputRejectedError`;
    - `AnswerRejectedError` → `UnreadableAnswerError`;
    - de overige `TransientStepError` → `TransientCallError`;
    - een onleesbaarheidsmarker in de keten → `UnreadableAnswerError`;
    - anders: opnieuw opwerpen.

    Dit volgt de foutindeling van spec §6.4, maar op de uitvoer van `C4Llm.call`. De adapter importeert `_is_retryable_poi_error` niet, want `C4Llm.call` heeft al ingedeeld.
  - **`on_attempt`** zet elke aanroep om naar `report.record(...)`, met exact de bestaande teksten: `geaccepteerd`, `afgekeurd (<regel>)` en `tijdelijke fout`. Er is één `StepReport` voor de hele stap, met dezelfde reden als nu (`documented.py:251–262`).
  - **Herstel.** Voor elke bundel in `failed_bundles` volgt `retries.defer(f"documented:{key}", attempt, fallback, apply, report=report)`:
    - `attempt` draait `run_extraction` over de mislukte fragmenten van die bundel en voegt geldige delen meteen samen in het resultaat;
    - mislukt er daarna nog een fragment, dan werpt `attempt` `AnswerRejectedError` (bij `rejected` of `unreadable`) of `TransientStepError`;
    - `fallback()` geeft de terugval per fragment voor de resterende fragmenten (spec §8.6) en vult `fallback_fragments` en `fallback_citations`;
    - zo blijven `drain()`, `mark_fallback` en het bestaande rapport kloppen.
  - **Ontdubbelen** over fragmenten heen, op de sleutels uit spec §8.7.
  - **Opslag** in `project_root / ".chunkhound/extraction"`, met `read_only=llm.trial`. `ProviderIdentity` en `InputLimit` komen uit `llm.provider_identity("utility")` en `llm.input_limit("utility")`. `concurrency` is de concurrency van `C4Llm`.

**Acceptance:**
- Promise:
  - volledige dekking;
  - terugval per fragment zonder onterechte lockopslag;
  - incrementeel hergebruik met correcte regelnummers;
  - hervatten na een fatale fout zonder publicatie;
  - proefmodus schrijft niets;
  - het bestaande rapportcontract blijft gelden.
- Evidence:
  - `test_documented_covers_every_line_or_marks_fallback`: één fragment faalt blijvend. Dat fragment staat in `fallback_fragments`; alle andere regels hebben een geldige uitkomst.
  - `test_fallback_fragment_without_lock_items_blocks_lock` (Review Focus 1).
  - `test_insert_at_top_reuses_and_shifts_citations` (Review Focus 4). Fixture: `docs/arch.md` met 12 secties van ongeveer 1.500 tekens, en `max_input_chars=20_000` in de rolconfiguratie, wat ≥ 3 bundels geeft. Voeg een regel in bovenaan sectie 1. Bundels zonder sectie 1 komen uit de cache, en hun citaten wijzen naar regel +1.
  - `test_cached_outcome_with_stale_quote_is_not_reused`: vervals na run 1 een citaat in het opgeslagen JSON-bestand. In run 2 faalt `recheck`, wordt het fragment opnieuw aangeroepen en staat het vervalste citaat nergens.
  - `test_trial_makes_no_calls_and_no_cache_writes` (Review Focus 5 van de spec): geen aanroepen, geen nieuwe bestanden, ongewijzigde `st_mtime_ns`.
  - `test_duplicate_items_across_fragments_are_merged_once`.
  - `test_resume_after_fatal_error_publishes_nothing` (CLI): 3 documenten in ≥ 2 bundels, een fatale fout bij de tweede bundel, `concurrency=1`. Exitcode 1. Lockbytes en uitvoermap blijven ongewijzigd, en de cache bevat bundel 1. Run 2 roept bundel 1 niet aan.
  - `test_old_cache_entries_are_pruned_only_after_non_trial_run`: een bestand met een wijzigingstijd van 31 dagen geleden blijft staan na een proefrun en is weg na een gewone run.
  - Bestaande tests blijven inhoudelijk gelijk, waaronder `test_documented_quote_must_exist`, `test_documented_reuses_on_same_hashes`, `test_documented_fallback_after_retry` (`drain() == 1`, `llm.calls == 2`), `test_documented_retry_can_recover`, `test_documented_trial_and_no_documents_make_no_calls`, `test_documented_cannot_cite_unprovided_or_outside_files` en `test_llm_failure_contract`.

- [ ] **Step 1:** Pas de conftest-helper en de bestaande tests aan, en schrijf de nieuwe tests. Run → FAIL.
- [ ] **Step 2:** Implementeer `llm.py`, `documented.py`, de prompt en `pipeline.py`.
- [ ] **Step 3:** Run `uv run pytest tests/code_mapper -v -n auto` → PASS; ruff en mypy.

### Task 6: Rapportage

**Files:**
- Modify:
  - `chunkhound/code_mapper/c4/assemble.py`: tellingen per reden op `_Assembly`. Er komt een dataclass `UnlinkedCounts(no_match: int, ambiguous: int, not_allowed: int)`, die als vierde tupelelement van `assemble(...)` wordt teruggegeven. `C4Evidence` en het JSON-schema veranderen niet. Pas alle aanroepers aan (`grep -rn "assemble(" chunkhound tests`).
  - `chunkhound/code_mapper/c4/pipeline.py`: `C4Build.report_extra: list[str] = field(default_factory=list)`, met de twee nieuwe regels.
  - `chunkhound/api/cli/commands/code_mapper.py:193`: na `report_lines()` volgt `for line in self.build.report_extra: formatter.info(line)`.
- Test: `tests/code_mapper/c4/test_assemble.py`, `tests/code_mapper/c4/test_cli_contract.py`

**Read:** spec §8.8; `assemble.py:265–300`; `pipeline.py:118–126`; `code_mapper.py:176–196`.

**Acceptance:**
- Promise: de gebruiker ziet de bundeltellingen, en per reden waarom documentatierelaties niet gekoppeld zijn. Het koppelgedrag verandert niet, en de bestaande regel `C4 documented:` blijft uniek.
- Evidence:
  - `test_unlinked_documented_relations_are_counted_by_reason`: drie relaties (onbekende term, ambigue term, intern zonder statische verwijzing) → 1/1/1. De citaten zijn ongewijzigd `verified=False`.
  - `test_cli_reports_documented_bundles`: beide exacte regels staan in de uitvoer. `test_llm_failure_contract` blijft ongewijzigd groen.

- [ ] **Step 1:** Tests. Run → FAIL.
- [ ] **Step 2:** Implementeer.
- [ ] **Step 3:** Run → PASS; ruff en mypy.

### Task 7: Eindverificatie

**Files:** geen productcode.

- [ ] **Step 1:** `uv run ruff check chunkhound` en `uv run mypy chunkhound` zijn schoon.
- [ ] **Step 2:** `uv run pytest tests/test_smoke.py -v -n auto` → PASS.
- [ ] **Step 3:** `uv run pytest tests/ -v` → PASS. Controleer met `git diff --stat -- chunkhound/services/research chunkhound/providers chunkhound/code_mapper/service.py` dat er geen wijzigingen zijn (spec invariant 7).
- [ ] **Step 4:** Rapporteer aan de gebruiker: gewijzigde bestanden, testuitkomsten, open punten en de bekende onzekerheid over de Codex-marker. **Geen commit, push, maprun of providerrun** zonder aparte toestemming.

## Model coverage

| Specsectie | Taak |
|---|---|
| §2 begrippen, §4 fragmentering | 1 |
| §6.1–6.2 limiet en budget, invariant 7 (fingerprint) | 2 |
| §7 opslag | 3 (bewezen in 4 en 5) |
| §5 bundels en hergebruik, §6.3–6.4 halveren en foutindeling | 4 |
| §8.1–8.7 C4-doorstroom, terugval, ontdubbelen, lock, opruimen | 5 |
| §8.8 rapport | 6 |
| §10 tests 1–11 | 1: test 1 · 4: tests 5–7 · 5: tests 1–4, 8, 9 · 6: test 10 · 7: test 11 |
| §9 research | buiten dit plan (eerst een addendum) |
