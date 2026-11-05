# O-MAP deel A §20: ruis onder externe systemen en personen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Wijkt de code af van de spec, stop dan en leg het voor; verzin geen eigen keuze.

**Goal:** `overrides.drop` en `overrides.merge` in het lockbestand halen een extern systeem of persoon weg of voegen het samen, en de documentstap maakt minder ruis.

**Architecture:**

- `Overrides` krijgt `drop` en `merge`; lockversie blijft 5.
- Nieuwe pure module `c4/curation.py`, aangeroepen in `assemble_with_notes` na `documented_relations()` en vóór de overrides `names`/`descriptions`/`titles`.
- `assemble_with_unlinked` heet `assemble_with_notes` en geeft `AssemblyNotes`; `finish_c4` zet de overgeslagen vermeldingen in het rapport.
- Prompt `c4_documented.md` krijgt één alinea (R15).

**Tech Stack:** Python `>=3.10,<3.15`, pydantic 2, pytest (`asyncio_mode = "auto"`), ruff, mypy. Geen nieuwe dependencies.

**Spec:** [docs/melly/specs/2026-11-03-omap-producent-design.md §20](../specs/2026-11-03-omap-producent-design.md) · Model: [map-structuuranalyse.md](../models/map-structuuranalyse.md) R13–R16 · Besluitenlog: [2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md), rijen 155–156

**Nulmeting (2026-11-05, op `5c6712af`):** `tests/code_mapper` + `tests/services/extraction`: 605 passed, 1 skipped. `tests/autodoc`: 121 passed. Smoke: 14 passed. `uv run mypy chunkhound/code_mapper`: geen fouten.

## Project Commands

```bash
uv run pytest tests/code_mapper tests/services/extraction -q -p no:cacheprovider -n auto   # per taak
uv run pytest tests/test_smoke.py -v -n auto                                                # verplicht vóór een commit
uv run ruff check <gewijzigde .py-bestanden>                                                # de repo heeft elders al fouten
uv run mypy chunkhound/code_mapper
uv run python scripts/generate_c4_schemas.py                                                # na wijziging van c4/model.py
```

## Global Constraints

- **Geen providerrun.** Tests gebruiken de nep aan de providergrens (`tests/code_mapper/c4/conftest.py`). Run 5 vraagt aparte goedkeuring (§20.6).
- **Geen push.** Eén commit per taak op `c4/shared-extraction-layer`.
- **Lockversie blijft 5** (`SCHEMA_VERSION`); `_VALIDATOR_VERSION` blijft 3.
- **Niet aanraken:** contract (`contract.py`), AutoDoc, `classify.py`, `c4_classify.md`, `overrides.classifications`/`placements`.
- **Geen alias** voor `assemble_with_unlinked`; alle aanroepers volgen.
- **Testfilosofie (`AGENTS.md`):** contracttests via publieke uitvoer (kaartmodel, bewijs, contract, rapport); geen tests op `curation.py` zelf of op de prompttekst.
- **Git-status:** `.superpowers/design/c4-shared-extraction-claude-handoff.md` is niet van dit plan en blijft ongestaged. `.chunkhound/map.lock.json` niet wijzigen of verwijderen.
- Code, prompts en rapportregels in het Engels.

## Review Focus

1. **Volgorde in het lockbestand:** dezelfde `drop`/`merge` in andere volgorde geven dezelfde uitvoer en rapportregels — Taak 2, `test_curation_ignores_invalid_entries_with_a_reason`.
2. **Relaties die niet geraakt worden:** een relatie zonder weggehaald of samengevoegd eindpunt houdt id, titel en status — Taak 2, `test_merge_moves_sources_and_collapses_relations` (relatie `component:a->storage:sqlite`).
3. **Overrides voor verdwenen id's:** een `names`-override voor de bron van een merge doet niets; het doel houdt zijn naam — Taak 2.
4. **Tweede run na een merge:** geen aanroep, dezelfde titel uit het lockbestand (vingerafdruk over de omgezette referenties) — Taak 3, `test_drop_and_merge_reach_the_contract_and_replay`.
5. **Proefrun:** rapportregels zonder aanroep en zonder contract — Taak 3, `test_trial_run_reports_ignored_overrides_without_calls`.

---

### Task 1: `drop` en `merge` in het lockbestand (§20.1)

**Files:**

- Modify: `chunkhound/code_mapper/c4/model.py:153-159` (`Overrides`)
- Modify: `chunkhound/code_mapper/c4/schemas/map_lock.schema.json` (gegenereerd)
- Test: `tests/code_mapper/c4/test_lockfile.py`

**Classes:** `Overrides` (attributen `drop`, `merge`).

**Read:** spec §20.1; `chunkhound/code_mapper/c4/lockfile.py`; `tests/code_mapper/c4/test_lockfile.py:141-185`.

**Tools:**

- `bash` `uv run python scripts/generate_c4_schemas.py` — na de modelwijziging, om het schema te verversen
- `bash` Project Commands (pytest, ruff, mypy, smoke) — vóór de commit

**Interfaces:**

- Produces: `Overrides.drop: list[str]` (element-id's), `Overrides.merge: dict[str, str]` (bron-id → doel-id), beide standaard leeg.

**Acceptance:**

- Promise: een lockbestand met `drop` en `merge` blijft geldig en die velden overleven elke run; een fout type geeft een duidelijke laadfout.
- Evidence: `test_override_section_is_never_rewritten` (uitgebreid); `test_corrupt_lockfile_is_reported_not_overwritten` (twee nieuwe gevallen); `test_shipped_schema_matches_model`.
- Judged by: tests — het lockformaat is een machinecontract.

- [ ] **Step 1: Rode tests.**
  - In `test_override_section_is_never_rewritten`: `manual` krijgt ook `"drop": ["external:httpx"]` en `"merge": {"external:google": "external:gemini"}`; extra assert `read_scope_lock(tmp_path, "/").overrides.merge == {"external:google": "external:gemini"}`.
  - In de parametrisatie van `test_corrupt_lockfile_is_reported_not_overwritten` twee gevallen: een scope met `"overrides": {"drop": "external:httpx"}` en een met `"overrides": {"merge": {"external:google": 1}}`. Neem de overige velden over uit een geldige scope (bijv. `sample_lock().model_dump(mode="json", by_alias=True)` in een helper), zodat alleen `overrides` de fout veroorzaakt.
- [ ] **Step 2:** `uv run pytest tests/code_mapper/c4/test_lockfile.py -q -p no:cacheprovider` — verwacht: FAIL (onbekend veld `drop`/`merge`; de twee nieuwe foutgevallen falen al om dezelfde reden, controleer dat ze na Step 3 nog steeds slagen om de juiste reden).
- [ ] **Step 3:** Voeg `drop: list[str] = Field(default_factory=list)` en `merge: dict[str, str] = Field(default_factory=dict)` toe aan `Overrides`. Draai `uv run python scripts/generate_c4_schemas.py`.
- [ ] **Step 4:** Project Commands — verwacht: alles groen, `test_shipped_schema_matches_model` slaagt.
- [ ] **Step 5: Commit** `feat(c4): accept drop and merge overrides in the map lock` (model, schema, test).

### Task 2: Nabewerking in de assemblage (§20.2, §20.4 eerste punt, §20.5 test 1–3)

**Files:**

- Create: `chunkhound/code_mapper/c4/curation.py`
- Modify: `chunkhound/code_mapper/c4/assemble.py:90-97,430-489`
- Modify: `chunkhound/code_mapper/c4/pipeline.py:17,844` (alleen de rename; de rapportregels zijn Taak 3)
- Test: `tests/code_mapper/c4/test_assemble.py`

**Classes:** `AssemblyNotes` (nieuw), `UnlinkedCounts`, `Overrides`, `Element`, `Relation`, `Citation`, `Reference`.

**Read:** spec §20.2 en §20.4; model R7, R9, R13, R14, R16; `assemble.py:276-489`; `merge.py:119-139` (`relation_fingerprint`, `fallback_title`); `pipeline.py:440-524` (`_fingerprints`, `_pending_titles`, `_titles`); `tests/code_mapper/c4/test_assemble.py`.

**Tools:**

- `lsp` references op `assemble_with_unlinked` — vóór de rename, om elke aanroeper te vinden
- `bash` Project Commands (pytest, ruff, mypy, smoke) — vóór de commit

**Interfaces:**

- Consumes: `Overrides.drop`, `Overrides.merge` (Taak 1).
- Produces:
  - `assemble.AssemblyNotes` — `@dataclass(frozen=True)` met `unlinked: UnlinkedCounts` en `ignored_overrides: tuple[str, ...]`.
  - `assemble.assemble_with_notes(inp: AssemblyInput) -> tuple[list[Element], list[Relation], C4Evidence, AssemblyNotes]`; `assemble()` blijft de eerste drie teruggeven.
  - `ignored_overrides` bevat volledige rapportregels, gesorteerd: eerst alle `drop`, dan `merge`, elk op bron-id. Vorm, letterlijk:
    - `C4-overrides: drop ignored for <id> (<reason>)`
    - `C4-overrides: merge ignored for <bron> -> <doel> (<reason>)`
  - Redenen, letterlijk, gecontroleerd in deze volgorde (eerste treffer telt): `not on the map` (bron, dan doel) · `not an external system or person` (bron, dan doel) · `same element` · `different kinds` · `dropped` (bron of doel staat in `drop`) · ronde 2: `target is merged itself`.
  - `curation.curate(...)` is intern voor `assemble.py`; vorm vrij, maar puur: geen mutatie van de invoer, uitkomst onafhankelijk van de volgorde van `drop` en `merge`.

**Acceptance:**

- Promise: met `drop` verdwijnt een extern systeem of persoon met zijn relaties; met `merge` gaat alles naar het doel en vallen dubbele relaties samen; een ongeldige vermelding wordt overgeslagen met een reden.
- Evidence: `test_drop_removes_element_relations_and_citations_but_keeps_references` (R13); `test_merge_moves_sources_and_collapses_relations` (R14, R9); `test_curation_ignores_invalid_entries_with_a_reason` (R16); bestaande tests in `test_assemble.py` ongewijzigd groen na de rename.
- Judged by: tests — domeinregels R13, R14, R16 zijn elk met de spec-voorbeelden vastgelegd.

- [ ] **Step 1: Rename en rode tests.** Vervang in `test_assemble.py` `assemble_with_unlinked(inp)[3]` en `*_, unlinked = …` door `assemble_with_notes(inp)` met `.unlinked` op de vierde waarde. Nieuwe tests op `assembly_input()`:
  - `test_drop_removes_element_relations_and_citations_but_keeps_references` (R13): `Overrides(drop=["external:stripe", "external:stripe"])` →
    - `"external:stripe"` niet in elementen en niet in `evidence.element_files`;
    - `"component:a->external:stripe"` niet in relaties;
    - geen citaat met `target` `"external:stripe"` of `"component:a->external:stripe"`;
    - de referentie `a.py:2` staat er nog met `to == "package:stripe"` en `relation is None`;
    - `notes.ignored_overrides == ()` (dubbel id telt één keer);
    - `"component:a->storage:sqlite"` ongewijzigd t.o.v. `assemble(assembly_input())`.
  - `test_merge_moves_sources_and_collapses_relations` (R14), drie gevallen in één test of geparametriseerd:
    1. _Code-bron, document-doel:_ voeg `DocElement("external", "Payments", citation(line=7), "Takes payments.")`, `DocRelation("A", "Payments", "pays via", citation(line=8))`, een referentie `Reference(relation=None, from_file="a.py", line=8, to="package:openai", kind="call", status="counts")`, `external_sites["openai"] = [("a.py", 8)]` en `classifications["openai"] = Classification("external_system", ("external_system",) * 3, ("disputed",), False)` toe. `inp.titles[relation_fingerprint("component:a", "external:payments", [("import", "package:stripe"), ("call", "package:openai")])] = "charges cards"`. Overrides `merge={"external:stripe": "external:payments", "external:openai": "external:payments"}`, `names={"external:stripe": "Ignored"}`. Verwacht:
       - alleen `external:payments`, met naam `"Payments"`, omschrijving `"Takes payments."`, status `"found"`, markers `["disputed"]`;
       - één relatie `component:a->external:payments`: status `"found"`, `reference_counts == {"import": 1, "call": 1}`, markers `["disputed"]`, titel `"charges cards"`;
       - citaten `a.py:2` (code) en `pyproject.toml:9` (configuration) hebben `target == "external:payments"`; het citaat `README.md:8` hoort bij de relatie;
       - referenties `a.py:2` en `a.py:8` houden `to` (`package:stripe`, `package:openai`) en krijgen `relation == "component:a->external:payments"`;
       - `evidence.element_files` heeft geen sleutel `external:stripe` of `external:openai`.
    2. _Document-bron, code-doel:_ `DocElement("external", "Stripe API", citation(line=7))`, `DocRelation("User", "Stripe API", "pays with", citation(line=8))`, `DocRelation("Stripe API", "stripe", "wraps", citation(line=9))`; `merge={"external:stripe-api": "external:stripe"}`. Verwacht: `person:user->external:stripe` met titel `"pays with"` en status `"documented"`; geen relatie `external:stripe->external:stripe` en geen citaat met dat id als `target`; het citaat `README.md:9` is weg; `external:stripe` heet `"stripe"`.
    3. _Twee personen uit documenten:_ `DocElement("person", "Users", citation(line=7))`, `DocRelation("User", "App", "uses", citation(line=5))`, `DocRelation("Users", "App", "works in", citation(line=6))`; `merge={"person:users": "person:user"}`. Verwacht: één relatie `person:user->container:app` met titel `"uses"` (de relatie die het id al had); citaten regel 5 en 6 hebben dat id als `target`; `person:users` bestaat niet.
  - `test_curation_ignores_invalid_entries_with_a_reason` (R16): met `DocElement("external", "Payments", citation(line=7))` en `DocElement("external", "Billing", citation(line=8))` erbij:
    - `drop=["external:gone", "container:app"]`, `merge={"person:user": "external:stripe", "external:stripe": "external:stripe", "external:payments": "external:billing", "external:billing": "external:stripe"}` → `ignored_overrides == ("C4-overrides: drop ignored for container:app (not an external system or person)", "C4-overrides: drop ignored for external:gone (not on the map)", "C4-overrides: merge ignored for external:payments -> external:billing (target is merged itself)", "C4-overrides: merge ignored for external:stripe -> external:stripe (same element)", "C4-overrides: merge ignored for person:user -> external:stripe (different kinds)")`; `external:billing` is samengevoegd in `external:stripe`, `external:payments` blijft.
    - kring `merge={"external:payments": "external:billing", "external:billing": "external:payments"}` → beide `(target is merged itself)`, beide elementen blijven.
    - `merge={"external:payments": "external:stripe", "external:billing": "external:gone"}` → alleen `external:billing -> external:gone (not on the map)`; `external:payments` is samengevoegd.
    - `drop=["external:stripe"]`, `merge={"external:payments": "external:stripe"}` → `merge ignored for external:payments -> external:stripe (dropped)`; `external:payments` blijft.
    - **Volgorde:** dezelfde overrides met omgekeerde volgorde van `drop` en van de `merge`-dict geven gelijke `assemble_with_notes(...)`-uitvoer.
- [ ] **Step 2:** `uv run pytest tests/code_mapper/c4/test_assemble.py -q -p no:cacheprovider` — verwacht: FAIL op import van `assemble_with_notes`.
- [ ] **Step 3: Implementeer.**
  - `AssemblyNotes` en `assemble_with_notes` in `assemble.py`; `pipeline.py` importeert en roept `assemble_with_notes(inp)[3].unlinked` aan.
  - `curation.py` volgt §20.2 punt 1–4. Beslissingen die de spec open laat:
    - De relatie-id's die niet veranderen en niet samenvallen, blijven hetzelfde object (geen nieuwe titel, status of markers).
    - Titel van een omgezette of samengevallen relatie mét codereferenties: `titles.get(new_id, titles.get(fingerprint, fallback_title(kinds)))`, dezelfde volgorde als `static_relations` (`assemble.py:307-311`); `fingerprint = relation_fingerprint(from, to, [(r.kind, r.to) for r in refs])` over alle referenties die na omzetting bij `new_id` horen, zodat `_fingerprints` (`pipeline.py:440-451`) dezelfde waarde berekent.
    - Status van elementen opnieuw volgens `statuses()` (`assemble.py:369-374`) op de nagewerkte citaten.
    - Daarna past `assemble_with_notes` `names`/`descriptions`/`titles` en `coverage` toe op het resultaat, en ontdubbelt de citaten zoals nu.
- [ ] **Step 4:** Project Commands — verwacht: alles groen; aantal tests = nulmeting + 3.
- [ ] **Step 5: Commit** `feat(c4): curate the map with drop and merge overrides` (`curation.py`, `assemble.py`, `pipeline.py`, `test_assemble.py`).

### Task 3: Rapport en volledige run (§20.2 titelstap, §20.4, §20.5 test 4–5)

**Files:**

- Modify: `chunkhound/code_mapper/c4/pipeline.py:844-852`
- Modify: `CHANGELOG.md` (Unreleased)
- Test: `tests/code_mapper/c4/test_pipeline.py`

**Classes:** `AssemblyNotes`, `Overrides`, `ContractCounts` (ongewijzigd, alleen gelezen).

**Read:** spec §20.2 (titelstap, contract), §20.4, §20.5; `pipeline.py:800-875`; `contract.py:247-295`; `model.py:188-222` (`relations_off_the_map`); `tests/code_mapper/c4/test_pipeline.py:1-153,519-532`; `CHANGELOG.md:1-40`.

**Tools:**

- `bash` Project Commands (pytest, ruff, mypy, smoke) — vóór de commit

**Interfaces:**

- Consumes: `assemble_with_notes`, `AssemblyNotes.ignored_overrides` (Taak 2); `Overrides.drop`/`merge` (Taak 1).
- Produces: `C4Build.report_extra` bevat `*notes.ignored_overrides` direct na de regel `C4 documentation relationships not linked: …`.

**Acceptance:**

- Promise: een gebruiker zet `drop`/`merge` in `.chunkhound/map.lock.json`, draait `chunkhound map`, en ziet de opgeschoonde kaart in het contract en elke overgeslagen vermelding in het rapport; een tweede run kost niets.
- Evidence: `test_drop_and_merge_reach_the_contract_and_replay`; `test_trial_run_reports_ignored_overrides_without_calls`.
- Judged by: tests — rapport en contract zijn de publieke uitvoer; de werking op de echte kaart volgt in run 5 (§20.6, aparte goedkeuring).

- [ ] **Step 1: Rode tests.** Gedeelde opzet (helper in het testbestand):
  - `write_sources(fixture_repo, {"README.md": "# Shop\n\nEen beheerder gebruikt Mollie; acme/admin betaalt via Stripe.\n", "notify.py": "import httpx\n\n\ndef ping() -> None:\n    httpx.get('https://n.invalid')\n"})` en `commit(...)`.
  - `documented`-antwoord met citaat `README.md:3-3` en die zin als quote: elementen person `beheerder`, external `Mollie`, external `Stripe`; relaties `beheerder -> Mollie` ("uses") en `acme/admin -> Stripe` ("pays via").
  - `merge`-antwoord zoals `merge_answer`, maar de groep met `dir == "."` gaat naar `direct`, zodat `notify.py` bij `container:shop` hoort (dat geeft `container:shop->external:httpx`).
  - Component-id's komen uit het merge-antwoord (in de probe `component:g2-3`), dus de test noemt ze niet letterlijk: `payments = next(id for id, files in first.evidence.element_files.items() if id.startswith("component:") and "shop/payments.py" in files)`.
  - Eerste run zonder lock (nulmeting via probe op `5c6712af`: `<payments>->external:requests` en `container:shop->external:httpx` `found`; `container:acme-admin->external:stripe` en `person:beheerder->external:mollie` `documented`; `externals_without_relation == ("Mollie",)`, `persons_without_relation == ("beheerder",)`); daarna `lock.overrides.drop = ["external:mollie", "external:gone"]` en `lock.overrides.merge = {"external:requests": "external:stripe", "external:httpx": "external:stripe"}`.

  `test_drop_and_merge_reach_the_contract_and_replay`: tweede run met die lock →
  - contract-elementen: geen `external:requests`, `external:httpx`, `external:mollie`, `person:beheerder`; wel `external:stripe`;
  - contract-relatie `<payments>->external:stripe` met minstens één bron van soort `"code"` en titel `"gebruikt via API"`; `pipeline_answers.calls["titles"] >= 1`;
  - `contract_counts.persons_without_relation == ("beheerder",)` en `"Mollie" not in contract_counts.externals_without_relation` (de eerste run had `("Mollie",)`: een relatie met een extern element telt nooit als verbinding, `contract.py:272-289`; `beheerder` stond er al in run 1, zie besluitrij 156);
  - `contract_counts.redundant_direct_relations == 1` (`container:shop->external:stripe` dubbelt `<payments>->external:stripe`, want `<payments>` ligt in `container:shop`);
  - `"C4-overrides: drop ignored for external:gone (not on the map)"` in `report_extra`, direct na de regel `C4 documentation relationships not linked: …`;
  - `result.lock.overrides.merge` is ongewijzigd;
  - derde run met de lock van de tweede: `pipeline_answers.calls` leeg na `clear()`, `model` en de titel van `<payments>->external:stripe` gelijk aan de tweede run.

  `test_trial_run_reports_ignored_overrides_without_calls`: na de eerste run en dezelfde overrides, `original = lock.model_copy(deep=True)`, `calls.clear()`, proefrun → `not pipeline_answers.calls`, `result.contract is None`, `result.lock is None`, de regel `C4-overrides: drop ignored for external:gone (not on the map)` staat in `report_extra`, `lock == original`, en `external:requests` staat niet in `result.model.elements`.

- [ ] **Step 2:** `uv run pytest tests/code_mapper/c4/test_pipeline.py -q -p no:cacheprovider -k "drop_and_merge or ignored_overrides"` — verwacht: FAIL op de ontbrekende rapportregel.
- [ ] **Step 3:** In `finish_c4`: `notes = assemble_with_notes(inp)[3]`; de bestaande regel gebruikt `notes.unlinked`; daarna `*notes.ignored_overrides`.
- [ ] **Step 4:** `CHANGELOG.md`, Unreleased: één entry **C4 curation overrides** — `overrides.drop` and `overrides.merge` in `.chunkhound/map.lock.json` remove or merge an external system or person; relations, citations and status follow, references stay in the evidence; invalid entries are skipped with a `C4-overrides:` report line; the lockfile stays version 5.
- [ ] **Step 5:** Project Commands — verwacht: alles groen.
- [ ] **Step 6: Commit** `feat(c4): report ignored curation overrides` (`pipeline.py`, `test_pipeline.py`, `CHANGELOG.md`).

### Task 4: Prompt van de documentstap (§20.3)

**Files:**

- Modify: `chunkhound/code_mapper/prompts/c4_documented.md:23-25`
- Modify: `CHANGELOG.md` (dezelfde Unreleased-sectie)

**Read:** spec §20.3; `chunkhound/code_mapper/prompts/c4_documented.md`; `documented.py:280-300` (stapversie).

**Tools:**

- `bash` Project Commands (pytest, ruff, mypy, smoke) — vóór de commit

**Interfaces:**

- Consumes: niets uit eerdere taken.
- Produces: een nieuwe stapversie van de documentstap (hash over de prompt), dus de volgende run roept die stap opnieuw aan.

**Acceptance:**

- Promise: de volgende run maakt geen extern systeem meer van een categorie, rol, voorbeeldnaam of bibliotheek (R15); concrete providers uit een tabel blijven.
- Evidence: geen test op de prompttekst (§20.3); bestaande tests in `tests/code_mapper` blijven groen. De werking volgt uit run 5, §20.6 controles 1–3.
- Judged by: user — de uitwerking op de echte kaart blijkt pas uit run 5 met aparte goedkeuring.

- [ ] **Step 1:** Voeg direct na regel 25 ("…a part of the described system itself.") een lege regel en deze alinea toe, letterlijk:

  ```text
  An external element names one concrete system. Never make one of a category or
  role without its own name, such as "an LLM provider", "embedding providers" or
  "an operator-controlled HTTPS endpoint"; where the fragment names the concrete
  systems, use those. A person may be a role. Never take a name that occurs only
  inside an example command, example query or code sample. A library stays
  excluded even when the text says what it does.
  ```

  De tabelregel (regel 35-36) blijft staan.

- [ ] **Step 2:** Breid de CHANGELOG-entry uit Taak 3 uit met één zin: the documentation step no longer turns a category, a role, a name from an example, or a library into an external system, so the next run asks that step again.
- [ ] **Step 3:** Project Commands — verwacht: alles groen.
- [ ] **Step 4: Commit** `feat(c4): keep categories, examples and libraries out of documented externals` (prompt, CHANGELOG).
