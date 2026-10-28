# Spec: `chunkhound map` levert de C4-structuur

- Datum: 2026-10-27 · Branch: `Cubical6/map-structuur-design` (basis `829ec586`)
- Besluitenlog: [2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md) (rij 1–36; "rij N" hieronder)
- Bindend kader: AutoDoc-C4-log `autodoc-c4-design/docs/melly/decisions/2026-10-27-autodoc-c4-map.md` rij 11–32 ("C4-log rij N")
- Model: [map-structuuranalyse.md](../models/map-structuuranalyse.md)

## 1. Doel en afbakening

`chunkhound map` schrijft naast de bestaande topics-Markdown een renderer-onafhankelijk C4-model plus bewijs (C4-log rij 15): softwaresysteem, containers, componenten, externe systemen, personen en relaties, elk met bronnen. AutoDoc rendert het; dat valt buiten deze spec (C4-log rij 30).

**In scope:** statische verwijzingen, deterministische groepen, containers en opslag, dependency-indeling, samenvoeging tot componenten, identiteit over runs, elementen uit documentatie, labels van samengevoegde pijlen, topicdekking, lockbestand, twee JSON-bestanden met schema.

**Buiten scope:** codeniveau (C4-log rij 24); federatie over meerdere databases (C4-log rij 31); LikeC4-uitvoer en de zichtbare vorm van _gedocumenteerd_ (C4-log rij 32); gericht bijmaken van topics (rij 23); volledige aanroep-/overervinganalyse voor andere talen dan Python, TS/JS/TSX/JSX en PHP (rij 15; issues Cubical6/chunkhound#1–#27, rij 16); wijzigingen aan HyDE of deep research (rij 23).

**Invarianten**

1. `--no-c4` geeft exact de huidige uitvoer, zonder extra tokens of statische analyse (rij 17).
2. Index, topics en gecombineerd document blijven byte-gelijk; `map` schrijft nooit genummerde links naar niet-topicbestanden in de index, omdat AutoDoc die als topic laadt (`chunkhound/autodoc/index_loader.py:22,54-65`; rij 29).
3. Het lockbestand bevat alleen echte uitkomsten: nooit terugval of proef (rij 19, 30).
4. Model en bewijs worden samen geschreven of geen van beide (rij 31).

## 2. Domeinmodel

Zie [model §1](../models/map-structuuranalyse.md#1-domeinmodel): 15 begrippen, regels R1–R12 met voorbeelden. Kern: relaties alleen uit statische verwijzingen (R1); componenten als vereniging van deterministische groepen (R2); identiteit via wederzijdse meerderheid 0,5 met tombstones (R3); id = soort + term (R4); containers volgen runtime-grenzen (R5); dependency-soort uit 3 stemmen (R6); volledig bewijs (R7).

**Open issues**

- zonder dossier: begrippen en regels zijn niet tegen een COGNiam-dossier gecontroleerd (rij 13).

**I3-checkpointstatus:** niet van toepassing (zonder dossier).

## 3. Ontwerpklassendiagram en vertaaltabel

Klassen per eenheid (§4) met Engelse namen; elk begrip uit §1 heeft een rij in de vertaaltabel. Zie [model §2](../models/map-structuuranalyse.md#2-ontwerpklassendiagram) en [model §3](../models/map-structuuranalyse.md#3-vertaaltabel); de runvolgorde staat in [model §5](../models/map-structuuranalyse.md#5-sequencediagrammen).

## 4. Design patterns

Geen patroon gekozen; zie [model §4](../models/map-structuuranalyse.md#4-design-patterns).

## 5. Architectuur

Nieuw subpakket `chunkhound/code_mapper/c4/` naast de bestaande topicstroom (rij 30):

| Eenheid | Verantwoordelijkheid | Rij |
|---|---|---|
| `references.py` | Statische verwijzingen per bestand | 32 |
| `runtime.py` | Containers, opslagkandidaten, bestand → container | 22, 32 |
| `grouping.py` | `TreeSpec` eerste run, daarna `replay` | 21, 32 |
| `classify.py` | Stemrondes voor dependencies en twijfelgevallen | 12, 22, 33 |
| `merge.py` | Samenvoegen, namen, omschrijvingen, titels (`merge`, `titles`) | 25, 27, 33 |
| `documented.py` | Elementen en relaties uit documentatie | 34 |
| `identity.py` | Id's, R3-overerving, tombstones, geschiedenis | 3, 35 |
| `summaries.py` | Views afleiden, labels voor samengevoegde pijlen | 35 |
| `topic_coverage.py` | Dekking via gedeelde geciteerde bestanden (naam vermijdt botsing met `chunkhound/code_mapper/coverage.py:11,48`) | 23, 30 |
| `lockfile.py` | Lezen, toepassen, atomair schrijven | 31 |
| `model.py` | Pydantic-modellen van model, bewijs en lockbestand | 35 |
| `writer.py` | Atomair schrijven van beide JSON-bestanden | 31 |
| `schemas/` | Meegeleverde JSON Schema's | 35 |
| `codeboarding/` | Gekopieerde MIT-code met kop en `LICENSE`: `source_inspector.py`, bron-terugval van `hierarchy_builder.py`, `clustering/names/` (CodeBoarding `13adc4a0`) | 20, 21 |

**Volgorde** ([model §5](../models/map-structuuranalyse.md#5-sequencediagrammen)): lockbestand lezen → topics en C4-tak parallel → `documented` (heeft de door topics geciteerde documenten nodig) → identiteit, dekking, `summaries` → schrijven → lockbestand. Herpogingen komen na de rest (rij 19, 30).

## 6. CLI en uitvoer

Parser `chunkhound/api/cli/parsers/code_mapper_parser.py`; commando `chunkhound/api/cli/commands/code_mapper.py`.

| Aanroep | Gedrag | Rij |
|---|---|---|
| `map <scope> --out D` | Markdown + C4 | 17 |
| `--no-c4` | Exact huidige uitvoer | 17 |
| `--no-markdown` | Alleen C4; topics worden wel onderzocht (nodig voor dekking) | 17 |
| `--no-c4 --no-markdown`, `--combined --no-markdown` | argparse-fout, exitcode 2 | 31 |
| `--plan` / `--overview-only` (één vlag, `code_mapper_parser.py:60-61`) | Overview + C4-proef: alleen deterministische stappen en lockbestand-hergebruik, 0 extra aanroepen, dekking "niet berekend", `run.kind = trial`, lockbestand ongewijzigd | 28 |
| `--plan --no-markdown` | Ook geen HyDE; 0 aanroepen; geen database nodig | 28, 32 |

- De databasecontrole (`commands/code_mapper.py:196-201`) blijft voor de volledige run en `--no-markdown` (topics); de C4-tak zelf leest van schijf (rij 32).
- Uitvoer in `--out`: `<safe_scope>_c4_model.json` en `<safe_scope>_c4_evidence.json`; `safe_scope` via `chunkhound/utils/text.py:4-7`, scopelabel via `chunkhound/code_mapper/orchestrator.py:49-58`. Schrijven via tijdelijk bestand + `os.replace`, eerst beide tijdelijke bestanden, dan beide vervangen (rij 31).
- Extra melding bij terugval: `C4: K elementen via terugval (niet opgeslagen)`; exitcodes verder ongewijzigd (rij 31).

## 7. Statische analyse en groepen

- **Bestandslijst:** dezelfde bestandssysteemloop als HyDE (`chunkhound/code_mapper/scope.py:8-70`) zonder het plafond `max_scope_files` (`:50`), omdat R7 volledig bewijs eist (rij 32).
- **Imports** voor alle talen met mapping, zonder database: `ImportContextService` (`chunkhound/services/research/shared/import_context.py:98-106`) en `resolve_import_paths` (`chunkhound/services/research/shared/import_resolver.py:91-116`).
- **Aanroepen en overerving** voor Python, TS/JS/TSX/JSX, PHP via de gekopieerde `source_inspector`, doel via de import-binding; zonder binding geen pijl. Andere talen: alleen imports, marker `imports_only` (rij 15, 20).
- **Filters:** type-only (Python `if TYPE_CHECKING:`, TS `import type`) → in het bewijs, status `type_only`, geen pijl; een import waarvan de naam nergens anders in het bestand voorkomt → status `unused`, geen pijl, tenzij re-export (`__init__.py`, `index.ts`, `__all__`) (rij 7, 11).
- **Record:** `(from, to, kind, line, status)`, onafgekapt in het bewijs (rij 8, 32).
- **Containers** (rij 5, 22): standaardvelden per ecosysteem (PEP 621 `[project.scripts]`, `bin` in `package.json`/`composer.json`, Cargo `[[bin]]`/`src/main.rs`) en Dockerfiles zonder taalmodel; sjablonen met plaatshouders tellen niet; meerdere startpunten in één pakket = één container. Een bestand hoort bij de container van de dichtstbijzijnde manifestmap. Zonder herkende container is de scope één container met marker `provisional`.
- **Opslag** (rij 6, 22): kandidaten op type (`Path`-velden, `VOLUME`, compose `volumes:`), niet op naam; geen framework- of namenlijst.
- **Groepen** (rij 21): eerste run `TreeSpec` per container via de gekopieerde `clustering/names/` met ChunkHounds bestanden als eenheden en de verwijzingen als koppelingen; daarna `replay`. Bestanden onder een opgeslagen prefix worden zonder taalmodel geplaatst; niet-geclaimde groepen gaan naar `merge`.

## 8. Taalmodelstappen

Alle aanroepen via `complete_structured_typed` (`chunkhound/interfaces/llm_provider.py:293-333`) binnen de `--jobs`-limiet (`code_mapper_parser.py:135`). Utility- en syntheseprovider uit `chunkhound/llm_manager.py:313,326`. Bij `--plan` nul aanroepen.

| Stap | Model | Wanneer | Invoer → uitvoer | Rij |
|---|---|---|---|---|
| `classify` | utility | Alleen kandidaten niet in het lockbestand; 3 parallelle gebundelde rondes | Dependencies (naam, importplekken, configverwijzingen, omschrijving), siteframeworks, twijfelgevallen, opslagkandidaten → stem `library`/`external_system`/`storage_driver` (en container-ja/nee) | 9, 12, 22 |
| `merge` | synthese | 1 per container bij eerste run of bij nieuwe niet-geclaimde groepen | Groepen (prefix, bestandsnamen), verwijzingen tussen groepen, bestaande componenten → indeling, naam, omschrijving, relatietitels | 25, 27 |
| `titles` | synthese | 1 per container met nieuwe of gewijzigde relaties zonder `merge` | Relaties met soorten verwijzingen → titels "werkwoord + via" | 33 |
| `documented` | utility | 1 per run als een bronbestand een andere hash heeft | Root-README van de scope + documentatiebestanden die topics citeren → personen, externe systemen, containers, componenten, relaties met letterlijk citaat en bestand:regel | 34 |
| `summaries` | utility | 1 per run met nieuwe labels | Samengevoegde pijlen met ≥2 verschillende titels → label ≤60 tekens | 35 |

- **Telling `classify`:** 3–0 → soort; 2–1 → meerderheid + `disputed` met afwijkende stem; 1–1–1 → bibliotheek + gemarkeerd; mislukt één ronde, dan tellen de twee overige (rij 12). Volgorde per ronde geschud met vaste seed.
- **Hergebruik:** relatietitel zolang de vingerafdruk (componentpaar + gesorteerde set `(soort, doelbestand)`) gelijk is (rij 33); label zolang de set (relatie-id, titel) gelijk is (rij 35); documentatie-uitkomst zolang de hashes van de bronbestanden gelijk zijn (rij 34).
- **Antwoordcontrole:** schema; elke groep precies één keer; component binnen één container; stem binnen de vaste soorten; citaat staat letterlijk op het opgegeven bestand:regel; label ≤60 tekens. Afgekeurd telt als tijdelijke fout (rij 33, 34, 35).
- **Fouten** via `_is_retryable_poi_error` (`chunkhound/code_mapper/service.py:95-119`): tijdelijk → één herpoging na de rest, daarna gemarkeerde terugval, niet opgeslagen; niet-tijdelijk of setupfout → exitcode 1, niets geschreven (rij 19, 33).

| Stap | Terugval (marker `fallback`) |
|---|---|
| `classify` | Bibliotheek, `not_classified` |
| `merge` | Elke groep een eigen component, naam uit prefix, geen omschrijving, `not_merged`, id `provisional` |
| `titles` | Titel uit de soort verwijzing: "importeert", "roept aan", "erft van" |
| `documented` | Laatst opgeslagen uitkomst als die er is, anders geen documentatie-elementen |
| `summaries` | Label deterministisch uit de onderliggende titels |

## 9. Identiteit, status en dekking

- **Normalisatie:** `slugify_kebab(ascii_only=True)` (`chunkhound/utils/text.py:10-16`) (rij 35).
- **Id's:** `systeem:`/`container:` + manifestnaam (`[project].name`, `name`, `[package].name`; Dockerfile zonder manifest → mapnaam); `opslag:` + configsleutel; `extern:`/`persoon:` + dependency of letterlijke term; component `component:` + naam uit `merge` bij ontstaan, daarna R3; relatie `<van-id>-><naar-id>`, één per geordend paar (rij 4, 6, 35). Voorvoegsels zoals goedgekeurd in rij 4 en 35; alleen de JSON-veldnamen zijn Engels.
- **Botsing bij een nieuw component-id:** bestaat het id al voor een _aangetroffen_ element of als tombstone → achtervoegsel `-2`, `-3`. Bestaat het als _gedocumenteerd_ element zonder bestanden → het nieuwe component neemt dat id over en wordt _aangetroffen_ (R4; rij 4).
- **R3:** vergelijking met het lockbestand; renames via `git diff -M --name-status <base_sha> HEAD`; zonder git of bij onbekende `base_sha` geen renames, vermeld in `run.renames` (rij 35). Geschiedenisranden ≥10% aan één kant: `continuation`/`split`/`merge`/`new`/`removed` (rij 3).
- **Status (R9):** elke bron krijgt haar soort van de stap die haar levert, zonder lijst: `references.py` → code; `runtime.py` en `classify` (manifest, Dockerfile, compose, configsleutel) → configuratie; `documented.py` → documentatie. _aangetroffen_ zodra ≥1 bron code of configuratie is (C4-log rij 29).
- **Documentatierelaties:** een relatie tussen twee _aangetroffen_ interne elementen zonder statische verwijzing komt niet op de kaart maar als niet-geverifieerd citaat in het bewijs (R1; rij 1). Een relatie met een persoon, extern systeem of _gedocumenteerd_ element komt op de kaart met status _gedocumenteerd_ (C4-log rij 21, 22, 25).
- **Dekking:** na de topics, zonder taalmodel, per element via gedeelde geciteerde bestanden; component zonder topic → `undescribed`; bij `--plan` "niet berekend"; _gedocumenteerd_ element zonder bestanden heeft geen dekking (rij 23; C4-log rij 12, 25).
- **Samengevoegde pijlen:** views context, containers en componenten per container worden deterministisch afgeleid; één onderliggende titel → overgenomen zonder aanroep (rij 35; C4-log rij 27, 28).

## 10. Schema's en lockbestand

Pydantic-modellen (`model.py`) → `model_json_schema()` ([docs](https://docs.pydantic.dev/2.13/concepts/json_schema/)), meegeleverd in `chunkhound/code_mapper/c4/schemas/`; Engelse velden; geheel getal `schema_version`, verhoogd bij een brekende wijziging (rij 24, 35).

| Bestand | Inhoud |
|---|---|
| `_c4_model.json` | `run` (`kind`, `schema_version`, `head_sha` via `orchestrator.py:37`, `scope`, `fallback_count`, `renames`); `elements` (`id`, `kind`, `name`, `description`, `status`, `parent`, `markers`, `coverage{status, topics}`); `relations` (`id`, `from`, `to`, `title`, `status`, `reference_counts`, `markers`); `merged` (`id`, `from`, `to`, `view`, `label`, `underlying`, `markers`); `history` |
| `_c4_evidence.json` | `schema_version`; `references` (`relation` of `null`, `from`, `line`, `to`, `kind`, `status`); `citations` (`target` element-/relatie-id of `null`, `file`, `start_line`, `end_line`, `source` `topic`\|`documentation`, `verified`); `element_files` |

Markers: `fallback`, `trial`, `disputed`, `undescribed`, `imports_only`, `provisional`, `not_merged`, `not_classified`.

**Lockbestand** `<target_dir>/.chunkhound/map.lock.json` (`target_dir`: `orchestrator.py:116`), los van `--out` en van de database-locatie (rij 26). Eén sectie per scopelabel met `base_sha`, `tree_spec`, `components`, `tombstones`, `relations` (met vingerafdruk), `classifications`, `documented` (hashes + uitkomst, rij 34), `summaries` (labels, rij 35) en `overrides` (handgeschreven, nooit overschreven, gaan voor) (rij 31). Gesorteerde sleutels, relatieve paden met `/`, geen tijdstempels. Geschreven via `os.replace` na een volledige run met exitcode 0; terugvalitems weggelaten; nooit bij `--plan` of exitcode 1. Geen bestandsvergrendeling. Committen is de keuze van de gebruiker via `.chunkhound/*` + `!.chunkhound/map.lock.json` in `.gitignore`; `map` wijzigt `.gitignore` niet (rij 18, 26).

## 11. Testen

Volgens TESTING_PHILOSOPHY in `AGENTS.md`: alleen contracten. Map `tests/code_mapper/c4/`, fixture-repo met Python, TS, PHP, manifest, Dockerfile en README; taalmodellen via `FakeLLMProvider` (`tests/fixtures/fake_providers.py:20,133`) (rij 36).

| Test | Contract | Rij |
|---|---|---|
| `test_no_c4_output_matches_upstream` | `--no-c4` byte-gelijk aan huidige uitvoer | 17 |
| `test_conflicting_output_flags_exit_2` | Twee vlagcombinaties → exitcode 2 | 31 |
| `test_plan_no_markdown_zero_calls_no_db` | 0 aanroepen, geen database, lockbestand ongewijzigd, `kind: trial` | 28, 32 |
| `test_rerun_unchanged_zero_calls_stable_output` | Tweede run: 0 aanroepen, zelfde model en lockbestand (op `head_sha` na) | 18, 27 |
| `test_component_identity_majority` | Voorbeelden (a), (b), (b′) en een rename | 3 |
| `test_static_reference_rules` | Gebruikt/ongebruikt/type-only/re-export/aanroep met en zonder binding | 1, 7, 11 |
| `test_llm_failure_contract` | Tijdelijk → terugval, exitcode 0, lockbestand zonder terugval; niet-tijdelijk → exitcode 1, niets geschreven | 19, 33 |
| `test_output_validates_against_schema` | Beide bestanden valide; elk id in het bewijs bestaat in het model | 24, 35 |
| `test_autodoc_loads_only_topics` | Echte `index_loader` leest precies de topics | 29 |
| `test_documented_quote_must_exist` | Niet-letterlijk citaat afgekeurd | 34 |
| `test_override_wins` | `overrides` gaan voor | 31 |

Gedragstests van de gekopieerde CodeBoarding-code gaan mee met MIT-kop. Smoke op deze repo met echte provider: aanroepen, tokens en duur van de eerste run; tweede run 0 aanroepen; handmatige beoordeling van de groepen. Kwaliteitscommando's: zie §13.

## 12. Risico's

| Risico | Maatregel / status | Rij |
|---|---|---|
| Dode functies leveren pijlen | Bekend; alleen ongebruikte imports gefilterd | 7, 11 |
| Gezamenlijke stemfout in alle 3 rondes | `disputed` + `overrides`; CLI-providers lagere concurrency (`chunkhound/providers/llm/base_cli_provider.py:470-485`) | 12 |
| Drempel 0,5 gemeten op één Python-project (CodeBoarding-geschiedenis) | Niet gemeten op ChunkHound | 10, 14 |
| Zonder dossier | Open issue | 13 |
| Aanroepen via afgeleide types (`self.service.run()`) | Geen pijl; bekend gat | 20 |
| Groepskwaliteit op ChunkHound niet gemeten | Smoke met handmatige beoordeling | 21 |
| Geen bestandsplafond en geen parse-cache | Duur gemeten in smoke; cache later indien nodig | 32, 36 |
| Gelijktijdige runs | Laatste schrijver wint | 31 |
| Verzonnen documentatie-extractie | Letterlijke citaatcontrole | 34 |
| Titelfrequentie ±20–28% van codecommits (proxy) | Gemeten met `.scratch/new_arrow_probe.py`; werkelijk lager `[INFERENCE]` | 33 |
| Eerste run kosten: ±40k invoertokens `classify` + `merge` + `documented` ±2–10k | Geschat `[INFERENCE]`; gemeten in smoke | 22, 34 |

## 13. Tooling

**Stack** (uit `pyproject.toml:18` en `uv.lock`): Python `>=3.10,<3.15`; pydantic 2.13.4; tree-sitter 0.25.2; tree-sitter-language-pack 0.9.0; pytest 8.4.2; ruff 0.13.3; mypy 1.18.2. Geen nieuwe dependencies (rij 20).

**Docs-dekking**

| Pakket | Status |
|---|---|
| pydantic 2.13.4 | `web: https://docs.pydantic.dev/2.13/concepts/json_schema/` |
| tree-sitter 0.25.2 | `docs missing` (docs-mcp `search_docs`: bibliotheek niet in de store) |

**Project Commands** (`AGENTS.md` KEY_COMMANDS):

```bash
uv run ruff check chunkhound
uv run mypy chunkhound
uv run pytest tests/code_mapper -v
uv run pytest tests/test_smoke.py -v -n auto
```

**Grondslag in deze sessie:** ChunkHound niet geïndexeerd in deze worktree (`.chunkhound` bevat alleen `daemon.log`) → `grep`/`read`/`glob`/`bash`; docs-mcp mist pydantic en tree-sitter → officiële web-docs; CodeBoarding-kloon `13adc4a0` (MIT) alleen gelezen; `gh` voor de issues van rij 16.

## 14. Bronnen

- Besluitenlog rij 1–36; C4-log rij 11–32.
- Code: zie de `pad:regel`-verwijzingen per sectie.
- CodeBoarding `13adc4a0`: `agents/relation_edges.py`, `diagram_analysis/{diagram_generator,scope_assembly,incremental_update}.py`, `static_analyzer/clustering/names/`, `infra/constants.py:20` (rij 33).
- Metingen: `.scratch/new_arrow_probe.py` (rij 33), `.scratch/autodoc_index_probe.py` (rij 29), CodeBoarding-geschiedenis (rij 10). Wegwerpscripts, niet gecommit.
