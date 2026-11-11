# PLAN: LLM-provider `pi-cli` (pi / pi-bolt als kaal model)

- **Status:** goedgekeurd 2026-11-11. Geeft geen toestemming voor een push of voor een providerrun buiten fase 4.
- **Aanleiding:** metingen van 2026-11-11 (zie Context). `codex exec` stuurt bij elke aanroep ~14,5k tokens harness-overhead mee; pi stuurt dezelfde prompt met 51 tokens overhead en is per aanroep 2-4 s sneller.

## Goal

ChunkHound krijgt een nieuwe LLM-provider `pi-cli`. Die roept de pi-CLI (`pi`, `pi-bolt` of een compatibele build) aan als kaal model: zonder tools, MCP, extensies, contextbestanden of sessie.

Gebruikers met een abonnement dat pi ondersteunt (bijvoorbeeld `openai-codex`) kunnen daarmee `code_research`, `map` en `autodoc` draaien zonder de vaste systeemprompt van Codex of Claude Code te betalen. Bestaande providers veranderen niet.

## Context

- **Repo / worktree:** `/home/disorder/Projects/Github/chunkhound/.claude/worktrees/pi-cli-provider`
- **Branch:** `feat/pi-cli-provider`, basis lokale `main` op `b37ec31e`. Lokale `main` staat 69 commits vóór `origin/main`; baseer niets op `origin/main`.
- **Projectregels:** lees `AGENTS.md`, met name TESTING_PHILOSOPHY. Schrijf alleen contracttests; nep alleen op de echte externe grens (het `pi`-subprocess).

### Metingen (2026-11-11, model `openai-codex/gpt-6-luna`, thinking low)

| Harness | Triviale prompt | Input-tokens |
|---|---|---|
| `codex exec` (argv zoals ChunkHound) | 4,7-12,1 s | 14.579 (11.520 cached) |
| `pi-bolt -p --mode json`, isolatievlaggen | 1,3-1,6 s | 51 |

Bij echte ChunkHound-prompts (775 B / 17 KB / 162 KB) duurde Codex 4,6 / 6,3-9,2 / 9,5-10,8 s en pi-bolt 2,0 / 4,4-5,6 / 6,1-7,4 s. Eén `chunkhound research`-run met `codex-cli` deed 29 aanroepen in 275 s wall-time.

### Bestaande seams

- **Basisklasse:** `chunkhound/providers/llm/base_cli_provider.py`.
  - `BaseCLIProvider._run_cli_command` (r. 284) is de enige abstracte uitvoerstap. `complete`, `complete_structured`, de lege-uitvoercheck en de usage-schattingen komen uit de basis.
  - Helpers: `resolve_cli_binary(name, env_var=...)` (r. 37), `build_cli_argv` (r. 177) en `terminate_cli_process` (r. 209).
- **Referentie-implementatie:** `chunkhound/providers/llm/opencode_cli_provider.py`. Die heeft ook NDJSON-uitvoer, een `provider/model`-modelformaat en een reasoning effort.
- **Registratie** (zie fase 2 voor de exacte regels):
  - `chunkhound/core/config/llm_config.py`
  - `chunkhound/llm_manager.py` (r. 36-43 registry, r. 139-143 reasoning effort)
  - `chunkhound/providers/llm/__init__.py`

### Vastgesteld gedrag van pi 1.4.0 / Pi-Bolt 1.0.8

- **Prompt via stdin werkt** (`pi -p` leest stdin). Gebruik geen argv voor de prompt: Linux staat maximaal 128 KB per argument toe en ChunkHound-prompts worden tot ~162 KB.
- **`--append-system-prompt <pad>` leest het bestand.** Getest: de inhoud wordt systeeminstructie.
- **`--system-prompt <tekst>` vervangt de standaard coding-prompt van pi.**
- **Er is geen vlag voor maximaal aantal output-tokens.** `max_completion_tokens` kan niet worden doorgegeven.
- **`--mode json` schrijft NDJSON-events.** Het antwoord staat in het laatste event met `type == "message_end"` en `message.role == "assistant"`:
  ```json
  {"type":"message_end","message":{"role":"assistant",
    "content":[{"type":"text","text":"BANANA","textSignature":"..."}],
    "provider":"openai-codex","model":"gpt-6-luna",
    "usage":{"input":53,"output":6,"cacheRead":0,"cacheWrite":0,"reasoning":0,"totalTokens":59},
    "stopReason":"stop"}}
  ```
  Volledige volgorde: `session`, `agent_start`, `turn_start`, `message_start`/`message_end` voor system en user, `message_start` (assistant), `message_update` × n, `message_end` (assistant), `turn_end`, `agent_end` (`{messages, willRetry}`), `agent_settled`. Content kan ook blokken van ander type bevatten (bijvoorbeeld thinking); neem alleen `type == "text"`.
- **Een API-fout geeft exit 0.** De fout staat alleen in de JSON:
  ```json
  {"type":"message_end","message":{"role":"assistant","content":[],
    "stopReason":"error","errorMessage":"Codex error: The 'does-not-exist' model is not supported when using Codex with a ChatGPT account."}}
  ```
- **Een onbekende provider geeft exit 1**, stderr `Error: Model "nosuchprovider/x" not found. Use --list-models to see available models.` en geen NDJSON.
- **Volledige argv van de meting:**
  ```
  pi -p --mode json --model <provider/id> [--thinking <level>]
     --no-tools --no-mcp --no-extensions --no-skills --no-prompt-templates
     --no-themes --no-context-files --no-session --no-approve --offline
     --system-prompt <basistekst> [--append-system-prompt <tmp>/system.md]
  ```

### Besluiten

1. **Naam en binary.**
   - De providernaam is `pi-cli`.
   - De binary komt uit `CHUNKHOUND_PI_BIN` (pad of naam op PATH), anders `pi`.
   - Voor pi-bolt zet de gebruiker `CHUNKHOUND_PI_BIN=pi-bolt`. Een andere build (bijvoorbeeld octet) werkt op dezelfde manier, mits de vlaggen hierboven gelijk zijn.
2. **Model.**
   - Het model is verplicht en heeft het formaat `provider/id` (bijvoorbeeld `openai-codex/gpt-6-luna`).
   - Er is geen standaardmodel; de defaults zijn `("", "")`, net als bij `opencode-cli`.
   - Een leeg segment of een ontbrekende `/` geeft een `ConfigurationError` bij het laden van de config.
3. **Reasoning effort.**
   - `reasoning_effort` (`minimal|low|medium|high|xhigh`) gaat als `--thinking <level>` mee.
   - Zonder effort geen `--thinking`.
   - `pi-cli` komt in `REASONING_EFFORT_PROVIDERS`.
4. **Systeemprompt.**
   - `--system-prompt` krijgt een vaste neutrale basistekst (constante in de provider, bijvoorbeeld `"You are a precise assistant. Follow the instructions exactly."`).
   - De systeemtekst van ChunkHound gaat via een tijdelijk bestand en `--append-system-prompt <pad>`.
   - De user-prompt gaat via stdin. Gebruik `_merge_prompts` niet.
5. **Isolatie.**
   - Altijd alle `--no-*`-vlaggen hierboven, plus `--no-approve` en `--offline`.
   - Het subprocess draait met een per-aanroep tijdelijke map als `cwd`. Die map bevat ook het systeemprompt-bestand en wordt in `finally` opgeruimd.
6. **Fouten.** Gebruik eerst de exit-code en daarna de JSON.
   - exit ≠ 0 → `RuntimeError` met de laatste ~20 regels stderr.
   - exit 0 met `stopReason` in `{"error","aborted"}` → `RuntimeError` met `errorMessage`.
   - exit 0 zonder assistant-`message_end` → `RuntimeError` ("no assistant message").
   - `stopReason == "length"` → geef de tekst terug en log een waarschuwing.
   - Regels die geen JSON zijn worden overgeslagen.
7. **Retries en time-out.**
   - pi probeert zelf al opnieuw (`willRetry`). De provider herhaalt alleen bij een time-out en bij een `errorMessage` die op een tijdelijke fout wijst: `429`, `rate limit`, `overloaded`, `timeout`, `5xx`.
   - Maximaal `max_retries` pogingen in totaal. Model-, auth- en configfouten falen direct.
   - Bij een time-out stopt `terminate_cli_process` het proces.
8. **`max_completion_tokens` wordt genegeerd**, omdat pi er geen vlag voor heeft. Log dat één keer op debug-niveau, niet per aanroep.
9. **Usage.** Gebruik voorlopig de schattingen uit de basisklasse. Echte usage uit de JSON doorgeven valt buiten scope (zie Open punten).
10. **Beschikbaarheid.** `health_check` of beschikbaarheid gaat via `<bin> --version`, zoals bij `codex-cli`.

## Constraints (voor elke fase)

- Wijzig alleen de bestanden die in de fase staan, tenzij het strikt nodig is. Noem een extra bestand in het rapport.
- Niet committen, niet pushen en geen andere fasen beginnen.
- Geen echte LLM-calls en geen netwerk, behalve in fase 3 en alleen als de gebruiker dat expliciet aanzet (opt-in integratietest). Unit-tests gebruiken een nep-`pi` op de subprocess-grens.
- Geen `print()` in providercode; gebruik `loguru`. Typ annotaties zonder forward-reference-quotes.
- Bestaande providers en hun tests blijven ongewijzigd en groen.
- Houd de context klein:
  - zoek met `rg` en lees alleen relevante regelbereiken;
  - draai gerichte tests met `-q --tb=short` en pipe lange uitvoer door `| tail -n 40`;
  - draai niet de volledige testsuite, dat doet Claude.

## Final report format (elke fase)

Maximaal ~15 regels:
1. Gewijzigde bestanden (één regel per bestand, met korte reden)
2. Gedraaide tests, met resultaten
3. Afwijkingen van het plan en open punten

---

## Phase 1: provider `PiCLIProvider` met contracttests
- [x] Done
- **Depends on:** none
- **Model:** `openai-codex/gpt-6.1-sol` / `medium`
- **Goal:** een zelfstandige providerklasse die `pi` aanroept volgens besluiten 1-10, met contracttests. Nog niet geregistreerd in config of manager.
- **Files:**
  - `chunkhound/providers/llm/pi_cli_provider.py` (nieuw)
  - `tests/unit/llm/test_pi_cli_provider.py` (nieuw)
  - eventueel `tests/fixtures/pi_cli/*.jsonl` (nieuw)
- **Steps:**
  1. Lees `base_cli_provider.py` (r. 37-60, 177-260, 256-543) en het skelet van `opencode_cli_provider.py` (`__init__`, `_validate_model_format`, `_build_cmd`, `_run_single_attempt`, NDJSON-parsing). Lees één bestaand testbestand (`tests/unit/llm/test_opencode_cli_provider.py`, alleen de opzet en twee tests) voor het nep-subprocess-patroon.
  2. Schrijf `PiCLIProvider(BaseCLIProvider)`:
     - `__init__(api_key=None, model="", base_url=None, timeout=DEFAULT_LLM_TIMEOUT, max_retries=3, reasoning_effort=None)` valideert model en effort;
     - `_get_provider_name()` geeft `"pi-cli"`;
     - een pure `_build_argv(...)`, `_run_cli_command(...)` volgens besluiten 4-8, en een NDJSON-parser.
  3. Maak NDJSON-fixtures op basis van de voorbeelden in Context: succes, `stopReason:error`, `stopReason:length`, geen assistant-bericht, en succes met regels die geen JSON zijn.
  4. Schrijf contracttests. Nep alleen het subprocess, ofwel een uitvoerbaar nep-`pi`-script via `CHUNKHOUND_PI_BIN`, ofwel het bestaande mock-patroon. Het nep-proces legt argv, stdin en cwd vast voor de asserties. Tests:
     - `test_pi_cli_returns_final_assistant_text`
     - `test_pi_cli_runs_isolated`: argv bevat alle `--no-*`-vlaggen, `--no-approve` en `--offline`; cwd is niet de projectmap; het bestand achter `--append-system-prompt` bevat precies de system-tekst; de user-prompt komt via stdin en staat niet in argv
     - `test_pi_cli_error_stop_reason_raises` (exit 0 + `stopReason:error` → `RuntimeError` met `errorMessage`)
     - `test_pi_cli_nonzero_exit_raises_with_stderr`
     - `test_pi_cli_timeout_terminates_process`
     - `test_pi_cli_forwards_reasoning_effort_as_thinking` (en zonder effort geen `--thinking`)
     - `test_pi_cli_rejects_model_without_provider_segment`
     - `test_pi_cli_retries_transient_error_then_succeeds` (eerst een 429-fout, daarna succes; een modelfout wordt niet herhaald)
- **Acceptance criteria:**
  - Alle tests hierboven slagen. Een test die op Windows niet kan draaien (nep-script) wordt met een reden overgeslagen.
  - `uv run mypy chunkhound/providers/llm/pi_cli_provider.py` en `uv run ruff check chunkhound/providers/llm/pi_cli_provider.py` zijn schoon.
  - Na elke aanroep, ook na een fout of time-out, staat er geen tijdelijke map meer.
- **Verify:** `uv run pytest tests/unit/llm/test_pi_cli_provider.py -q --tb=short | tail -n 40`
- **Notes:**
  - Kopieer niet de Windows-`.cmd`-logica van Codex. `build_cli_argv` regelt dat al.
  - Geen echte `pi`-aanroep in tests.
  - Implementeer geen echte usage-parsing (besluit 9).

## Phase 2: registratie in config, manager en CLI
- [ ] Done
- **Depends on:** Phase 1
- **Model:** `openai-codex/gpt-6.1-terra` / `medium`
- **Goal:** `pi-cli` is overal te kiezen waar `opencode-cli` te kiezen is (config, env, CLI-vlaggen, rollen utility/synthesis/map-hyde/autodoc-cleanup) en de manager maakt een `PiCLIProvider` aan.
- **Files:**
  - `chunkhound/core/config/llm_config.py`
  - `chunkhound/llm_manager.py`
  - `chunkhound/providers/llm/__init__.py`
  - `tests/unit/test_llm_config_per_role.py`
  - `tests/unit/test_llm_manager_registry.py`
- **Steps:** in `llm_config.py` (zoek met `rg -n "opencode" chunkhound/core/config/llm_config.py`):
  1. Voeg `"pi-cli"` toe aan `REASONING_EFFORT_PROVIDERS` (r. 40), `NO_KEY_PROVIDERS` (r. 126), `LLMProviderLiteral` (r. 133), `CLI_PROVIDER_CHOICES` (r. ~175) en de set in `_provider_requires_api_key` (r. ~1196).
  2. Voeg aan de default-modellen een tak `elif provider == "pi-cli": return ("", "")` toe (r. ~1043), vóór `assert_never`.
  3. Breid de modelvalidatie uit (`_validate_opencode_model_formats`, r. 693) of voeg een zuster-validatie toe, zodat `pi-cli` per rol een `provider/id` eist. Gebruik eigen foutteksten met `pi-cli`.
  4. Werk de helpteksten bij die providers voor reasoning effort opsommen (r. 318-333 en r. ~1336).
  5. Voeg in `llm_manager.py` en `__init__.py` `"pi-cli": PiCLIProvider` toe aan de registry. Reasoning effort loopt al via `REASONING_EFFORT_PROVIDERS`.
  6. Tests:
     - `test_pi_cli_needs_no_api_key_but_requires_model`
     - `test_pi_cli_reasoning_effort_reaches_provider`
     - manager-registry: `{"provider": "pi-cli", "model": "openai-codex/gpt-6-luna"}` geeft een `PiCLIProvider`
     - CLI: `--llm-provider pi-cli` wordt geaccepteerd
- **Acceptance criteria:**
  - `uv run mypy chunkhound` is schoon. Dat bewaakt `assert_never`-exhaustiviteit.
  - `uv run ruff check chunkhound` is schoon.
  - De bestaande config- en registry-tests blijven groen.
- **Verify:** `uv run pytest tests/unit/test_llm_config_per_role.py tests/unit/test_llm_manager_registry.py tests/unit/llm/test_pi_cli_provider.py tests/autodoc/test_autodoc_cleanup_llm_config.py -q --tb=short | tail -n 40 && uv run mypy chunkhound 2>&1 | tail -n 5`
- **Notes:**
  - Controleer met `rg -n '"codex-cli"' chunkhound` of er nog een providerlijst is die hierboven ontbreekt. Neem die mee en noem hem in het rapport.
  - `tests/code_mapper/**` noemt `opencode-cli` alleen als testdata; niet aanpassen.

## Phase 3: documentatie en opt-in integratietest
- [ ] Done
- **Depends on:** Phase 2
- **Model:** `openai-codex/gpt-6.1-terra` / `low`
- **Goal:** gebruikers vinden `pi-cli` in de docs en de configurator, en er is één integratietest tegen een echte `pi`, die standaard wordt overgeslagen.
- **Files:**
  - `site/src/pages/docs/configuration.md`
  - `site/src/components/configurator-data.ts`
  - `site/src/scripts/configurator.ts` (alleen als de mapping daar nodig is)
  - `tests/integration/test_pi_cli_provider_integration.py` (nieuw)
- **Steps:**
  1. In `configuration.md`:
     - voeg een rij voor `pi-cli` toe aan de providertabel (r. ~498, naast Codex CLI);
     - voeg een korte sectie toe met: wat de provider doet (kaal model, geen tools), het verplichte `provider/id`-model, `CHUNKHOUND_PI_BIN` (bijvoorbeeld `pi-bolt`), de mapping van `reasoning_effort` naar `--thinking`, en dat `max_completion_tokens` wordt genegeerd;
     - geef één configvoorbeeld in JSON.
  2. Voeg een `pi-cli`-optie toe aan `configurator-data.ts` naar het patroon van `opencode-cli` (r. ~313).
  3. Integratietest:
     - wordt overgeslagen tenzij `CHUNKHOUND_TEST_PI_MODEL` gezet is en de binary (via `CHUNKHOUND_PI_BIN` of `pi`) gevonden wordt;
     - één `complete()` met een vaste instructie ("Reply with exactly: OK") en assert op `OK`.
- **Acceptance criteria:**
  - Zonder `CHUNKHOUND_TEST_PI_MODEL` wordt de integratietest overgeslagen (`-rs` toont de reden).
  - De site bouwt, als dat lokaal kan.
- **Verify:** `uv run pytest tests/integration/test_pi_cli_provider_integration.py -q -rs --tb=short | tail -n 20`, en zo mogelijk `cd site && npm run build 2>&1 | tail -n 20`
- **Notes:** draai de integratietest niet zelf met een echt model. Dat doet Claude in fase 4.

## Phase 4: meting en vergelijking (Claude, niet pi-bolt)
- [ ] Done
- **Depends on:** Phase 3
- **Goal:** bevestigen dat de winst uit de Context ook binnen ChunkHound optreedt, en dat de antwoordkwaliteit vergelijkbaar is.
- **Steps:**
  1. Vraag de gebruiker akkoord voor de providerruns. Die gebruiken abonnementsquota.
  2. Draai de opt-in integratietest met `CHUNKHOUND_PI_BIN=pi-bolt CHUNKHOUND_TEST_PI_MODEL=openai-codex/gpt-6-luna`.
  3. Draai dezelfde `chunkhound research`-vraag als op 2026-11-11 tegen een kopie van de DB (`--db <kopie>`; de live DB is gelockt door de MCP-server), eenmaal met `codex-cli` en eenmaal met `pi-cli`. Gebruik bij beide `gpt-6-luna`/low.
  4. Vergelijk wall-time, aantal aanroepen en de inhoud van beide rapporten (dekking van dezelfde bestanden en conclusies).
- **Acceptance criteria:**
  - `pi-cli` is minstens 20% sneller dan `codex-cli`.
  - Het rapport noemt dezelfde kernbestanden en conclusies.
  - De uitkomst staat in de Progress log.

---

## Niet in scope / open punten

- **Prompt-caching.** pi-bolt liet bij een herhaalde identieke prompt `cacheRead=0` zien. Uitzoeken of pi een cache-sleutel of sessie-id nodig heeft is een apart vervolg.
- **Echte usage.** De JSON levert `usage.input/output/cacheRead`. Die doorgeven in `LLMResponse` in plaats van schattingen is een klein vervolg.
- **RPC-modus** (`--mode rpc`, één proces dat blijft draaien). Pas zinvol als het opstarten van pi een merkbaar deel van de tijd kost. Bij pi-bolt is dat ~1 s per aanroep.
- **Hogere concurrency.** `get_synthesis_concurrency()` blijft 3.

## Final verification (Claude, na alle fasen)
- [ ] Smoke: `uv run pytest tests/test_smoke.py -v -n auto`
- [ ] Volledige suite: `uv run pytest tests/ -v` (als achtergrondtaak)
- [ ] Lint / typecheck: `uv run ruff check chunkhound && uv run mypy chunkhound`
- [ ] Volledige diff nagelopen tegen het Goal en de besluiten
- [ ] `.pi-handoff/` verwijderd en daar niets van gecommit

## Progress log
| Date | Phase | sessionId | Commit | Notes |
|---|---|---|---|---|
| 2026-11-11 | plan | - | - | Plan geschreven op basis van metingen en pi-probes |
| 2026-11-11 | 1 | 01a1ccc7-8736-742b-987b-d84e7c7053aa | (zie git log) | 34 contracttests groen, ruff en mypy schoon; fixtures inline in de test i.p.v. aparte bestanden |

---

## Prompts (voor Claude, per fase kopiëren)

**Een fase starten** (nieuwe sessie, model uit de fase, `cwd` = de worktree):
> Read `AGENTS.md` and `docs/melly/plans/2026-11-11-pi-cli-provider.md` in `/home/disorder/Projects/Github/chunkhound/.claude/worktrees/pi-cli-provider`. Implement only Phase N. Follow the Constraints and the Final report format in the plan. Do not start other phases.

**Feedback binnen een fase** (zelfde `sessionId`, zolang de context < ~200k):
> Review feedback on Phase N: <concreet probleem, file:line, verwacht gedrag>. Fix only this and report.

**Handoff** (zelfde `sessionId`, bij context > ~200k, bij escalatie naar astra of na compaction):
> Write `.pi-handoff/phase-N.md` (≤ 60 lines): decisions made, files changed, what was tried and failed, current test status, remaining steps. Reply only "written".

daarna in een nieuwe sessie:
> Read `AGENTS.md`, `docs/melly/plans/2026-11-11-pi-cli-provider.md` and `.pi-handoff/phase-N.md` in `/home/disorder/Projects/Github/chunkhound/.claude/worktrees/pi-cli-provider`. Continue Phase N from the handoff. Follow the Constraints and the Final report format in the plan.

**Na een time-out of annulering** (zelfde `sessionId`):
> You were interrupted. Check `git status` and `git diff`, then finish Phase N and report.
