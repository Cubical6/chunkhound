# AutoDoc C4-kaart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Op OMP coördineert `sp-execute` seriële Orca-workers en onafhankelijke taakreviews; geen Native-uitvoering. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** oorspronkelijk plan goedgekeurd op 2026-10-29 (besluitenlog rij 56); de native specificatieherziening in `8af139b9` is op 2026-10-30 goedgekeurd (rij 64). Dit concrete gewijzigde plan in `4dd739a7` is afzonderlijk door de gebruiker goedgekeurd (rij 67). De bestaande execution-coördinator mag na overdracht en integratie van de documentcommits de Task3-fix met retained implementer hervatten; de technische Important blijft open tot onafhankelijke re-review. Task1/2 blijven goedgekeurd; Task4–6/final review zijn nog niet gestart. Geen productimplementatie, nieuwe execution-worktree, Run, coördinator of wijzigingen in execution vanuit design.

**Goal:** Publiceer het neutrale C4-model uit map-uitvoer als navigeerbare AutoDoc-kaart met controleerbare bronnen, individuele relaties en directe topicdoelen.

**Architecture:** Python leest het model naast de gekozen index, koppelt definitieve topicpagina's en schrijft LikeC4-DSL plus sitegegevens. Een lokaal meegeleverd LikeC4-forkarchief levert plugin en aangepaste detailvensters; Astro/Vite bouwt de kaart afzonderlijk. De bestaande sitewriter publiceert de optionele kaart zonder architectuuranalyse, nieuwe database of Node-subproces in AutoDoc.

**Tech Stack:** bestaande Python/uv/dataclasses/pytest/Ruff/mypy; Astro 7.4.2, Vite 8.3.5, React/React DOM 19.3.0, `@astrojs/react` 7.1.1; LikeC4-fork vanaf 1.60.0; Node ≥22.23.4, CI 24; forkworkspace pnpm 11.28.5.

**Spec:** [goedgekeurde normatieve specificatie met native herziening](../specs/2026-10-29-autodoc-c4-map-design.md). **Model:** [klassen, R1–R11 en sequenties](../models/autodoc-c4-map.md). **Decisions:** [besluitenlog](../decisions/2026-10-27-autodoc-c4-map.md), inclusief rij 54, 56 en 60–67. Geen programregister. `map-structuur-design` blijft een afzonderlijke producentafhankelijkheid.

## Project Commands

Voer repositorycommando's uit vanuit de execution-worktree. `<ws>` betekent de absolute canonical ignored SDD-workspace die de coordinator met `scripts/sdd-workspace` verkrijgt; `<fork>` is `<ws>/likec4-fork`; `<site>` is de in de taak genoemde proefsite. Vervang die aanduidingen vóór dispatch door concrete paden. Reviewers voeren alleen de niet-muterende kwaliteitscommando's uit, met command-local `TMPDIR=<ws>/qa/task-N`; geen installs, formatterwrites, builds of extra browserproeven door reviewers.

| Doel                         | Exact commando                                                       | Herkomst / wanneer                                                                                                             |
| ---------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Bootstrap                    | `uv sync --locked`                                                   | `.github/workflows/ci.yml:114`; alleen als worktree-setup dit nog niet deed                                                    |
| Native development-bootstrap | `make dev`                                                           | `Makefile:52-59`, `.github/workflows/ci.yml`; alleen eerste worker bij ontbrekende lokale native bootstrap, niet bij elke taak |
| Python lint                  | `uv run ruff check chunkhound`                                       | `Makefile:73-74`                                                                                                               |
| Python types                 | `uv run mypy chunkhound`                                             | `Makefile:76-77`; iedere taakreview                                                                                            |
| Python format                | `uv run ruff format chunkhound`                                      | projectrichtlijnen; alleen implementer, geen ongerelateerde heropmaak                                                          |
| AutoDoc-contracten           | `uv run pytest tests/autodoc/ -v`                                    | bestaande pytest-suite; taken 1, 3, 5, 6                                                                                       |
| Verplichte smoke             | `uv run pytest tests/test_smoke.py -v -n auto`                       | projectrichtlijnen; vóór iedere commit                                                                                         |
| Volledige suite              | `uv run pytest tests/ -v`                                            | `Makefile:79-80`; eindcontrole en verplicht vóór eventuele PR-push                                                             |
| Projectwebsite               | `npm ci --prefix site` gevolgd door `npm run build --prefix site`    | `.github/workflows/ci.yml:32-33`; upgrade-integratie in taak 1                                                                 |
| Wheel                        | `uv build --wheel --clear`                                           | `.github/workflows/ci.yml:423`; taak 6, zonder Watchman-release-env                                                            |
| Sdist                        | `uv build --sdist --out-dir dist`                                    | `.github/workflows/release.yml`; taak 6                                                                                        |
| Resourceverificatie          | `uv run python scripts/verify_autodoc_wheel_resources.py dist/*.whl` | bestaand script; taak 6                                                                                                        |
| Forkinstall                  | `pnpm install --frozen-lockfile`                                     | vastgepinde upstream-workspace; taak 2, na lokale tooltoevoeging opnieuw met bijgewerkt lockfile                               |
| Forkbuild                    | `pnpm turbo run build --filter=likec4 --concurrency=1`               | geserialiseerde upstream Turbo-build; bewezen in Task3 na declarationrace, taken 2–3                                           |
| Forkpack                     | `pnpm turbo run pack --filter=likec4`                                | na geslaagde forkbuild; upstream package-/Turbo-scripts, taken 2–3                                                             |
| Forklint                     | `pnpm run lint:errors-only`                                          | upstream root `package.json`; fork-taakreview                                                                                  |
| Forktypes                    | `pnpm turbo run typecheck --filter=likec4`                           | upstream Turbo-configuratie; fork-taakreview                                                                                   |
| Native corecontracten        | `pnpm --filter @likec4/core test`                                    | bestaand package-script; taken 2–3, inclusief gewone aggregatie en expanded boundaries                                         |
| Native DSL-/layoutcontracten | `pnpm --filter @likec4/language-server test`                         | bestaand package-script; taak 3, nieuwe echte DSL/model/layoutregressies                                                       |
| Native layoutcontracten      | `pnpm --filter @likec4/layouts test`                                 | bestaand package-script; taak 3, bestaande geometriecontracten                                                                 |
| Site-install/build           | `npm install` gevolgd door `npm run build`                           | gegenereerde `package.json`; taken 2–6 in schone proefsites                                                                    |
| Sitepreview                  | `npm run preview -- --host 127.0.0.1`                                | gegenereerde `package.json`; implementer-runtimebewijs                                                                         |

Oxfmt-opdrachten gelden voor de gewijzigde forkbestanden in taken 2–3: `pnpm exec oxfmt --write <gewijzigde-TS/JS-bestanden>` voor de implementer, `pnpm exec oxfmt --check <dezelfde-bestanden>` voor review. De vastgelegde versie is 0.75.0; controleer `--help`/`--version` en rapporteer de concrete bestanden. Dit vervangt niet repo-breed de upstreamformatter.

## Global Constraints

- Spec is normatief; geen nieuwe produceranalyse, code-niveau, componentgroepen, truncatielimiet, database, strict-modus of eigen npm-publicatie.
- JSON `schema_version: 1`; selecteer `<scope>_c4_model.json` bij de daadwerkelijk gekozen `<scope>_code_mapper_index.md`, niet via een aparte scopezoekactie.
- Eén systeem per geïndexeerde root/scope, geneste repositories inbegrepen. Status en neutrale identiteit komen van de producent; AutoDoc herclassificeert niet.
- Implementatie-/bron-/repositorypaden zijn POSIX-paden vanaf de gezamenlijke indexroot; `TopicCoverage.file` is relatief aan de map-uitvoermap. Bind aan `DocsitePage.source_path`, link daarna met de definitieve slug.
- Gewicht = aantal unieke gedeelde bestanden; oprollen met unies. “Hoort bij” en topicviewdoelen zijn uitsluitend direct; een direct gedekte container én component blijven beide staan.
- Iedere onderliggende relatie bewaart eigen status en bronnen. Geen status voor de samengevoegde pijl en geen voorkeur voor een directe relatie. Samenvattende labels maximaal 60 tekens; geen `[...]` of LLM-aanroep vanuit de kaartvertaling.
- Bronlinks: herkende GitHub/GitLab/Bitbucket-remotes, eigen repositorycommit, inclusief regelbereik; anders leesbare tekst. Geen remotecredentials, uitvoerbare model-HTML, codefragmenten of editorlinks.
- Volledige kaart op `/architecture/?view=<viewId>`; context `index`; onbekende view geeft zichtbare melding en context. Volledige views niet afkappen; gericht include-beleid zonder onbegrensde modelwildcards.
- `SiteExtras` vervangt de drie losse optionele writerparameters; alle callers migreren, zonder compatibiliteitsshim. `DocsiteSite` blijft sitemetadata.
- `architecture.json` altijd aanwezig bij volledige generatie. Zonder bruikbaar model gewone site, waarschuwing met hersteladvies, exit 0, geen optionele kaartimports. Alleen eerder door AutoDoc gemaakte kaartuitvoer verwijderen.
- Assets-only bewaart topics, DSL en kaartgegevens; geen producentmodel lezen of dekking herberekenen. Bestaand gedrag voor package/README zonder geldige `site.json` behouden.
- React-wrappers importeren hun TSX-kind rechtstreeks met `client:only="react"`; de layout ontdekt Astro-wrappers via `import.meta.glob`. Optionele integratie-imports alleen bij `enabled` kaartgegevens én `likec4/`; plugin `throwIfInvalid: true`. Een overgebleven gebruikersbestand in die directory activeert dus geen kaart.
- LikeC4 upstream `0375d146f8de2eb919033bd3b43b3701194f518b` / 1.60.0. Gebouwd `likec4`-package bevat plugin, React-bundel, gegenereerde CSS/fonts en notices, niet slechts diagrambron. Geen tweede diagramruntime toevoegen.
- Native hierarchyondersteuning geldt per echte onderliggende relatie met niet-lege `metadata.chunkhound_id`, niet per FQN-prefix of connectionbrede opt-in. Containment is geen relatie. Geen proxies, flattening, inputuitsluiting, stil verlies, fixturevernauwing, tweede renderer of producent-/schemauitbreiding; Builder-SDK, deployment- en dynamic-viewuitbreiding blijven buiten scope.
- Task3 sluit pas met behoud van exacte geselecteerde relatie-ID's, echte eindpunten/kaderranden, bruikbare layout en afzonderlijk klikbare heen-/terugpijlen in de bestaande native consumer/plugin/browser. Het shipped én uit de volledige patch gereconstrueerde archief moeten slagen; dit is geen naar Task4 verschuifbare Important.
- Astro 7.4.2; Vite 8.3.5; `@astrojs/react` 7.1.1; React en React DOM 19.3.0; Node minimaal 22.23.4, CI Node 24. Bestaande Python `>=3.10,<3.15`, alle Python via uv; enums gebruiken `str, Enum`, niet Python-3.11-only `StrEnum`.
- TS/JS: Google-stijl, oxfmt en oxlint; uitzondering uitsluitend `// oxlint-disable-next-line <regel> -- <reden>`. Bestaande Python-kwaliteitsconfiguratie behouden; geen repo-brede toolingmigratie.
- Permanente tests alleen voor consumentgedrag en lastige grenzen. Incidentele bron-/kopie-/hash-/formuleringsasserties verwijderen, niet herpinnen. Browserbewijs is geen bronstringtest.

## Review Focus

1. Systeem↔container, systeem↔component en container↔component met echte nesting: geen kindlus, verdwenen of samenvallende heen-/terugpijl; selectie blijft exact — taak 3, `test_R1_R6_R10_marked_hierarchy_keeps_selected_relations` en `test_R1_R6_hierarchy_layout_uses_real_boundaries`, beide archive-/browserproeven.
2. Meerdere indexen, gelijke bestandsnamen in geneste repositories en directe container-plus-componentdekking: geen kruisdekking of verlies van een direct doel; ouders krijgen uniegewicht — taak 1, beide bestaande `test_R5_*`-contracten; taak 3, exacte topicselectie.
3. Quotes, backslashes, regeleinden, Unicode, gereserveerde namen en remotecredentials: geldige DSL, tekstweergave en uitsluitend veilige commitlinks — taken 1–3, bronlinkcontract, echte DSL-consument en detail-harness.
4. Directe/afgeleide relaties met gemengde status of marker: behoud individuele details zonder markerlek naar ongeldige of niet-geselecteerde relaties — taken 2–3, bestaande boundary-/aggregatiecontracten plus `test_R6_hierarchy_exception_does_not_leak`.
5. Kaartsite opnieuw genereren zonder model versus assets-only met gewijzigd producentbestand: uitsluitend full-generation ruimt eigen oude kaartuitvoer op; presentatie-update bewaart data — taak 5, twee lifecyclecontracten.

## Bestanden en gedeelde grenzen

| Taak | Bestanden                                                                                                                                                                                  | Verantwoordelijkheid                                                                   |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| 1    | nieuw `chunkhound/autodoc/architecture/{__init__,model,loader,coverage,source_links}.py`                                                                                                   | Neutraal contract, modelselectie, referentiegrenzen, dekking en bron-URL's             |
| 2    | nieuw `chunkhound/autodoc/assets/vendor/likec4/{README.md,manifest.json,chunkhound.patch,LICENSE,NOTICE,likec4-1.60.0-chunkhound.1.tgz}`                                                   | Herbouwbare forkbronwijziging, licenties en gebouwd distributiearchief                 |
| 3    | wijzig bestaande `architecture/{likec4_ids,views,likec4_writer,site_data}.py`, native DSL/core/layoutbestanden en vendorresources; exacte paden hieronder                                  | Verliesvrije projectie, begrensde native hierarchyondersteuning en bewezen distributie |
| 4    | nieuw `assets/src/components/Architecture{Map,MiniMap}.{astro,tsx}` en `assets/src/pages/architecture/index.astro`                                                                         | Echte interactieve kaartcomponenten; getest in een tijdelijke Astro-site               |
| 5    | wijzig `autodoc/{models,generator,site_writer,site_writer_renderers}.py`, `assets/{astro.config.mjs,package.json,tsconfig.json}`, `assets/src/{layouts/DocLayout.astro,styles/global.css}` | Productiepublicatie, optionaliteit, lifecycle, navigatie en zoekintegratie             |
| 6    | wijzig `scripts/verify_autodoc_wheel_resources.py`, relevante CI, gebruikers-/onderhoudsdocs en changelog                                                                                  | Wheel/sdist, schone installatie en complete gebruikersroute                            |

In deze tabel zijn Pythonpaden zonder prefix relatief aan `chunkhound/autodoc/`. Concrete testpaden staan per taak. Alleen `__init__.py` als package-marker; geen extra re-exportlaag.

### Interne publicatiegrens, geen tweede producentformaat

Taak 3 schrijft `ArchitectureData` als JSON-geschikte `TypedDict` in `site_data.py`; taak 4 definieert dezelfde TS-velden in `ArchitectureMap.tsx` en importeert die type-only in de minikaart:

- `schemaVersion: 1`, `enabled: bool`, `contextView: "index"`.
- `views: dict[view_id, {title: str, level: str, elementId: str | None}]`.
- `elements: dict[neutral_id, {name: str, kind: str, description: str, status: str | None, focusView: str, defaultView: str | None}]`; het systeem heeft geen verzonnen status.
- `topics: dict[final_slug, {view: str | None, directElementIds: list[str]}]`.
- Leeg = `enabled: false` en drie lege dictionaries, niet een gedeeltelijk model.

DSL-metadata krijgt één gestructureerd tekstveld `chunkhound_detail` met JSON `version: 1`. Elementpayload: `kind`, `status` (systeem `null`), `sources`, `topics`, `focusView`, `defaultView`. Relatiepayload: `status`, `sources`, `source`, `target`; endpoints bevatten `id`, `fqn`, `title`. `sources` bevat `{kind,path,startLine,endLine,url}` met `url: str | null`; `topics` bevat `{title,url,weight}`. `metadata.chunkhound_id` blijft apart. Native `link`-velden plus leesbare `metadata.bronnen`/`metadata.topics` blijven bestaan. Geen ruwe remote-URL's in de publieke payload. Taak 2 consumeert deze grens; taak 3 produceert haar.

## Uitvoeringstaken

**Hervatting, geen herstart:** Task1/2 zijn gereviewd/goedgekeurd volgens `<ws>/progress.md`; hun onderstaande stappen zijn historische taakbeschrijvingen, geen nieuwe opdrachten. Task3 bestaat al in executioncommit `d955e11c`, resourcecommit `1ab39170` en forkcommit `818a388b`. Na plangoedkeuring integreert uitsluitend de bestaande coördinator de documentcommits, met behoud van de eigen nog ongecommitteerde besluitlogrij 59, en hervat de retained Task3-implementer. Geen nieuwe bootstrap, worktree, Run of coördinator; geen nieuwe uitvoering vanuit design. Vervolgorde: Task3-fix/re-review → Task4 → Task5 → Task6 → final review. Rulings1–5 en de bestaande Task2-detail-/security-/packagingcontracten blijven gelden.

### Task 1: Lees het juiste model en bereken controleerbare dekking

**Files:** Create `chunkhound/autodoc/architecture/{__init__,model,loader,coverage,source_links}.py`; Test `tests/autodoc/test_architecture_input.py`, `tests/autodoc/test_architecture_coverage.py`, `tests/autodoc/test_architecture_source_links.py`. Integreer eerst de bestaande upgradecommit `c7a2a7fc955bbbfc99e906522e9e41f1188f8adb`; ontwerp die upgrade niet opnieuw.

**Classes:** `C4Model`, `SoftwareSystem`, `Element`, `Relation`, `Source`, `Repository`, `MergedLabel`, `TopicCoverage`, `CoveredElement`, `Status`, `ElementKind`, `SourceKind`, `ModelLoader`, `CoverageIndex`, `SourceLinkBuilder`; bestaande `DocsitePage` als consumenttype.

**Read:** model §1–3 en spec “Producentgrens”, “Dekking” en “Foutgrenzen”; `chunkhound/autodoc/models.py:23-50`, `chunkhound/autodoc/index_loader.py:25-105`, `chunkhound/autodoc/generator.py:44-84,209-290`; `chunkhound/code_mapper/scope.py:19-66`; `pyproject.toml:199-249`; projectrichtlijnen en `skill://test-driven-development`.

**Tools:**

- `lsp` definitions voor `DocsitePage` en references voor `find_index_file` vóór aansluiting op bestaande types/selectie.
- `bash` `git show --stat c7a2a7fc955bbbfc99e906522e9e41f1188f8adb` vóór integratie; bevestig de bekende bestaande upgradebron, niet een nieuwe upgradekeuze.
- `bash` de pytest-, lint-, type- en smokecommando's uit Project Commands; projectwebsite-install/build na upgrade-integratie.

**Interfaces:**

- Consumes: bestaande `DocsitePage(source_path: str | None, slug: str, title: str, ...)`; gekozen `index_path: Path`, `input_dir: Path`; `log_warning: Callable[[str], None] | None`.
- Produces: dataclasses/enums met exact de velden uit model §2 en JSON-toewijzing §3; geen nieuwe classificatievelden.
- `ModelLoader.load(*, index_path: Path, log_warning: Callable[[str], None] | None = None) -> C4Model | None`.
- `CoverageIndex(model: C4Model, pages: list[DocsitePage], input_dir: Path, log_warning: Callable[[str], None] | None = None)`; `.topics_for(element_id: str) -> list[tuple[DocsitePage, frozenset[str]]]`; `.direct_elements_for(page: DocsitePage) -> list[str]`. Eerste resultaat sorteert op aflopend uniegewicht en daarna `(page.title, page.slug)`; directe ids deterministisch sorteren.
- `SourceLinkBuilder(model: C4Model)`; `.link(source: Source) -> str | None`; tekstbrongegevens blijven op `Source` staan.

**Acceptance:**

- Promise: juiste scope, definitieve topic-URL's, unieke gewichten en commitvaste bronnen zonder herinterpretatie van architectuur.
- Evidence: onderstaande contracttests voor R1–R6/R10/R11-consumptie; gewone site en projectwebsite bouwen na overname van de al goedgekeurde upgrade. Bronselectie volgt bestaand gedrag; source: `chunkhound/autodoc/index_loader.py`.
- Judged by: user — domein- en bronveiligheidsgrenzen; tests leveren controleerbaar bewijs.

- [ ] **Step 1: Integreer de bestaande upgrade.** Gebruik `git cherry-pick --no-commit c7a2a7fc955bbbfc99e906522e9e41f1188f8adb` als de wijziging nog ontbreekt. Behoud de huidige goedgekeurde spec/model/plan en alle besluiten; voeg bij een logconflict historische upgradefeiten toe zonder huidige rijen te vervangen. Behoud niet-gerelateerde gebruikerswijzigingen. Run beide projectwebsitecommando's en de verplichte smoke vóór het committen van uitsluitend deze integratie. De oude upgrade-worktree is geen vereiste.
- [ ] **Step 2: Schrijf de failing consumenttests.** `test_R5_selected_index_and_repository_paths_do_not_cross_bind`: twee indexen/modellen en `frontend/src/client.ts` versus `backend/src/client.ts` geven uitsluitend het gekozen model en de juiste topicdekking. `test_R5_direct_targets_differ_from_rolled_up_topics`: direct containerbestand plus componentdekking, dubbele covers en een overlappend pad geven beide directe ids, één topiclink per ouder, uniegewicht in plaats van optellen, definitieve slug; een documentatie-only onderdeel zonder files krijgt geen direct doel. `test_input_failures_warn_without_inventing_architecture`: afwezig/ongeldig/onbekende versie → `None` plus oorzaak/hersteladvies; onbekende parent/endpoint/bron/topicreferentie verwijdert alleen de afhankelijke inhoud; geldig model met nul relaties blijft geldig. `test_R11_sources_use_their_own_repository_commit`: parametrize HTTPS/SSH voor GitHub/GitLab/Bitbucket, geneste repoprefix op padgrenzen, inclusief range, credentials en onbekende host/commit; assert exacte veilige URL of `None`.

  Concrete assertions in de coveragefixture: systeem `system`, container `container`, component `component`, topic met definitieve slug `final-topic`, twee unieke bestanden en herhaalde covers:

  ```python
  assert coverage.direct_elements_for(page) == ["component", "container"]
  assert [(p.slug, len(files)) for p, files in coverage.topics_for("system")] == [
      ("final-topic", 2)
  ]
  assert coverage.direct_elements_for(uncovered_page) == []
  assert source_links.link(unknown_host_source) is None
  ```

- [ ] **Step 3: Run `uv run pytest tests/autodoc/test_architecture_input.py tests/autodoc/test_architecture_coverage.py tests/autodoc/test_architecture_source_links.py -v`.** Verwacht FAIL wegens ontbrekende architectuurmodule, niet wegens een netwerk- of native-bootstrapfout.
- [ ] **Step 4: Implementeer de Interfaces.** Eén genormaliseerde pad-/id-index per geladen model; coverage gebruikt bestandsverzamelingen en bestaande paginaobjecten. JSON-vorm-/versiefouten en verwachte leesfouten geven waarschuwingen; geen brede exception die programmeerfouten maskeert. Koppel alleen met de gekozen indexstam, ook als de scopeheading anders is. Meld onbekende ids: onbekende parent verwijdert die tak, onbekend endpoint die relatie; filter onbekende bron-id's en sla elementen/relaties zonder overgebleven onderbouwing over. Onbekende repository verwijdert die bron; onbruikbaar merged-label verwijdert alleen de override; onbekende cover/missende pagina verwijdert alleen die koppeling. Verwijder transitive dangling referenties, behoud overige bruikbare inhoud.
- [ ] **Step 5: Run de nieuwe tests, AutoDoc-suite, lint/types en een tijdelijke uv-Python-aanroep die twee echte topicbestanden plus beide modellen laadt en de gekozen directe ids, definitieve URL en codehost-URL afdrukt.** Verwacht PASS en uitsluitend waarden uit het gekozen model; verwijder de proefbestanden na bewijsregistratie.
- [ ] **Step 6: Werk de changelog bij met de gerealiseerde consumentgrens; run verplichte smoke en commit uitsluitend de vijf nieuwe modules, drie tests en eigen changelogwijziging.** Commit: `feat(autodoc): consume neutral C4 model and topic coverage`.

### Task 2: Bouw de LikeC4-fork met volledige detailinformatie

**Files:** In `<fork>` Modify `packages/diagram/src/overlays/element-details/ElementDetailsCard.tsx`, `packages/diagram/src/likec4diagram/relationship-popover/RelationshipPopover.tsx`, `packages/likec4/package.json`, root `package.json` en `pnpm-lock.yaml`; Create `packages/diagram/src/chunkhound/metadata.ts`. In ChunkHound Create de zes `chunkhound/autodoc/assets/vendor/likec4/`-bestanden uit de bestandstabel. Geen externe forkremote of publicatie aanmaken.

**Classes:** geen nieuwe domeinklassen; gebruik de interne publicatiegrens en bestaande LikeC4-element-/relatiemodellen.

**Read:** spec “Detailvensters”, “Distributie”, “Tekstgrenzen”; interne publicatiegrens hierboven; projectrichtlijnen voor TS/JS. Op de vastgepinde upstreamcommit: `package.json`, `pnpm-workspace.yaml`, `turbo.json`, `packages/{diagram,react,likec4}/package.json`, hun Turbo-configs, `packages/likec4/tsdown.config.mts`, beide detailbestanden, `packages/vite-plugin/src/modules.d.ts`, `packages/diagram/src/ReactLikeC4.tsx`, `LICENSE`. Gebruik de officiële bron-URL's onder Sources.

**Tools:**

- `mcp__docs_mcp__search_docs` `{library:"likec4",version:"1.60.0",query:"element metadata relationship model direct derived relations ReactLikeC4 navigation",limit:3}` vóór detailwijzigingen.
- `read` `https://raw.githubusercontent.com/likec4/likec4/0375d146f8de2eb919033bd3b43b3701194f518b/packages/diagram/src/overlays/element-details/ElementDetailsCard.tsx` vóór de eerste forkedit.
- `read` `https://raw.githubusercontent.com/likec4/likec4/0375d146f8de2eb919033bd3b43b3701194f518b/packages/diagram/src/likec4diagram/relationship-popover/RelationshipPopover.tsx` vóór relatie-/navigatiegebruik; gepinde bron gaat vóór afwijkende docsvoorbeelden.
- `lsp` definitions/references voor de twee detailcomponenten en hun model-/navigatiehooks in de lokale fork vóór wijzigen.
- `bash` `pnpm exec oxfmt --help` en `pnpm exec oxfmt --version` na de lokale tooltoevoeging; daarna fork-install/build/pack/lint/types, scoped oxfmt, schone site-install/build en Python smoke uit Project Commands.
- `eval` browser: eigen tab openen, detail-harness daadwerkelijk bedienen, screenshots in `<ws>/screens/task-2-details.png`, tab sluiten. Eerst browserdocumentatie lezen; geen usertab hergebruiken.

**Interfaces:**

- Consumes: `chunkhound_id` en `chunkhound_detail` volgens de gedeelde grens; native `diagramEdge.relations` met alle onderliggende relatie-id's.
- Produces: installeerbaar `likec4@1.60.0-chunkhound.1`, archief `likec4-1.60.0-chunkhound.1.tgz`, exports `likec4/react` en `likec4/vite-plugin` intact. Geen extra publiek adapter-API.
- `manifest.json`: upstream URL/commit, forkcommit, patch-SHA256, artifactnaam/versie/SHA256, Node/pnpm-versies en uitgevoerde buildcommando's. `chunkhound.patch` bewaart alle forkbron-/lockfilewijzigingen ten opzichte van upstream; README beschrijft checkout/apply/build/pack en vervanging. `LICENSE` kopieert de upstreamlicentie; `NOTICE` bewaart toepasselijke bronvermeldingen, waaronder NVIDIA. Alleen een genegeerde checkout is geen bewaarde forkbron.

**Acceptance:**

- Promise: elementdetails tonen status, afzonderlijke bronnen, gewogen topics en Focus-view; een pijl toont iedere directe en afgeleide relatie met eigen status/bronnen en endpointnavigatie.
- Evidence: fail-before/pass-after detail-harness met gemengde relaties en kwaadaardige tekst; schone installatie van het werkelijk gepackte archief toont de aangepaste UI en lokale stijlen/fonts. Native relatie-inventaris/API: source: `read` `https://raw.githubusercontent.com/likec4/likec4/0375d146f8de2eb919033bd3b43b3701194f518b/packages/diagram/src/likec4diagram/relationship-popover/RelationshipPopover.tsx`; bundelgrens: source: `mcp__docs_mcp__search_docs`.
- Judged by: user — zichtbare detailkwaliteit en veilige bronweergave; screenshots/DOM-waarnemingen dragen het oordeel.

- [ ] **Step 1: Maak `<fork>` vanaf exact upstreamcommit en installeer met upstream pnpm/lockfile.** Voeg oxfmt uitsluitend als vastgelegde fork-devdependency toe en behoud de bestaande oxlintconfig. Stel uitsluitend het te packen `likec4`-package op de herkenbare forkversie in; geen ChunkHound-versiebump of npm-publicatie.
- [ ] **Step 2: Maak een tijdelijke echte Vite/React-consument van de nog ongewijzigde upstreambuild.** Gebruik een kleine geldige DSL met één containerpijl die een directe relatie en twee componentrelaties projecteert, gemengde statussen en afzonderlijke bronnen. Geef alle entiteiten de afgesproken metadata, waaronder tekst `<img src=x onerror=...>`, quotes en Unicode. Controleer vóór de fix in de browser dat semantische status/bron/topic/Focus-velden ontbreken; leg dit vast als failing acceptatiescenario, niet als test van bronstrings.
- [ ] **Step 3: Pas de twee detailcomponenten aan en implementeer uitsluitend de benodigde metadata-uitlezing in `metadata.ts`.** Reacttekst, geen HTML-injectie. Iedere relatie uit `diagramEdge.relations` blijft zichtbaar in direct/afgeleid; geen status op de geaggregeerde pijl. Endpointacties openen het echte onderliggende element, niet alleen het uitgezoomde kader. Focus gebruikt de metadata-view; topics gebruiken definitieve URL's en aflopend gewicht. Behoud MIT/NVIDIA-notices.
- [ ] **Step 4: Leg gecontroleerde forkbron vast en bouw/pack haar.** Format gewijzigde TS/JS met oxfmt en run forklint/types; run verplichte Python smoke vanuit de execution-worktree vóór de lokale forkbroncommit. Commit uitsluitend de forkbron-/lockfilewijzigingen, zodat de build uit de vastgelegde forkcommit komt. Run forkbuild/forkpack; verwacht exit 0 en een packagearchief, niet een monoreporoot. Turbo verzorgt generate/sources, diagramstyles, React, SPA en pluginmodules; sla die prerequisites niet handmatig over.
- [ ] **Step 5: Installeer het nieuwe `.tgz` in een schone kopie van de harness en bouw/start die.** Herhaal het scenario: alle drie relaties en hun individuele status/bronnen zichtbaar; elementtopics correct geordend; Focus- en endpointacties werken; scriptpayload blijft tekst; CSS en fonts laden uit de gebouwde site zonder tweede diagramruntime. Bewaar screenshot, exacte waarnemingen en package-identiteit.
- [ ] **Step 6: Bewaar de volledige bronpatch, het archief, licenties, werkelijke manifestwaarden en onderhoudsinstructies onder `assets/vendor/likec4/`.** Maak de patch van upstream naar de vastgelegde lokale forkcommit. Herbouw vanuit een schone upstreamcheckout plus patch en controleer het functionele detailcontract opnieuw; geen eis van byte-identieke gzip-timestamps. Run Python smoke en commit uitsluitend deze resources: `feat(autodoc): bundle LikeC4 fork with provenance details`.

### Task 3: Herstel verliesvrije projectie en native hierarchy-layout

**Files:**

- Modify in execution: `chunkhound/autodoc/architecture/{likec4_ids,views,likec4_writer,site_data}.py`; Test `tests/autodoc/test_architecture_projection.py`. Deze modules en tests bestaan al; geen tweede projectielaag.
- Modify in `<fork>`: `packages/language-server/src/validation/relation.ts`, `packages/core/src/compute-view/element-view/predicates/relation-direct.ts`, `packages/core/src/model/connection/model/find.ts`; behoud `packages/core/src/compute-view/element-view/clean-connections.ts` en zijn Ruling5-contract.
- Modify in `<fork>`: `packages/language-server/src/views/LikeC4Views.ts`, `packages/layouts/src/graphviz/{GraphvizLayoter,GraphvizParser,layout-model}.ts`; Create `packages/layouts/src/graphviz/hierarchy-edges.ts` als interne geometriehelper, geen package-export of tweede layouter.
- Test in `<fork>`: Create `packages/language-server/src/__tests__/chunkhound-hierarchy.spec.ts`; behoud bestaande `packages/language-server/src/validation/relation.spec.ts` en core `boundary-relations.spec.ts`, `clean-connections.spec.ts`, `multiple-relationships.spec.ts`.
- Modify vendor `chunkhound/autodoc/assets/vendor/likec4/{README.md,manifest.json,chunkhound.patch,likec4-1.60.0-chunkhound.1.tgz}` en eigen changelogdeel. Behoud LICENSE/NOTICE. `packages/likec4/tsdown.config.mts` alleen aanpassen als de schone archiveproef een ontbrekende gepatchte native dependency aantoont; geen tweede runtime/package.

**Classes:** `LikeC4IdAllocator`, `ViewSpec`, `ViewLevel`, `LikeC4Writer`; consumeert alle contractklassen/enums uit Task1 en bestaande `DocsitePage`. `ArchitectureData` blijft een technische TypedDict. Native `LikeC4Model`, computed/diagram edges en `GraphvizLayouter` zijn rendererverantwoordelijkheden, geen nieuwe domeinklassen.

**Read:** model §1–3, goedgekeurde spec “LikeC4-vertaling” en de volledige acceptatietabel; Task1/2 Interfaces en gedeelde publicatiegrens; `<ws>/design-feedback.md`, `<ws>/progress.md` met Rulings1–5, `<ws>/task-3-review-initial.json`, `<ws>/task-3-report.md:113-135`, `<ws>/qa/task-3-fix-r1/{fixture.json,expected.json,projection-inventory.json,node-red.txt,vite-build-red.txt}`; `chunkhound/autodoc/assets/vendor/likec4/README.md`; alle hierboven genoemde native bestanden; `<fork>/packages/language-server/src/model/parser/{ModelParser,Base}.ts`, `<fork>/packages/language-server/src/test/testServices.ts`, `<fork>/packages/language-services/src/common/LikeC4.ts`, `<fork>/packages/language-server/src/LikeC4LanguageServices.ts`, `<fork>/packages/layouts/src/graphviz/{DotPrinter,ElementViewPrinter,QueueGraphvizLayoter}.ts`, `<fork>/packages/core/src/types/{model-data,view-computed,view-layouted}.ts`; projectrichtlijnen en `skill://test-driven-development`.

**Tools:**

- `mcp__docs_mcp__search_docs` `{library:"likec4",version:"1.60.0",query:"DSL metadata links view of include relationship with title override",limit:3}` vóór gewijzigde DSL-generatie; dit bewijst geen hierarchy-layout, daarvoor gepinde bron.
- `lsp` references op `LayoutTaskParams` in `<fork>/packages/layouts/src/graphviz/GraphvizLayoter.ts` vóór interfacewijziging; controleer native callers en herhaal dit voor ieder ander gewijzigd geëxporteerd symbool.
- `read` de gepinde native bestanden uit Read, package-scripts/lockfile en upstream DSL-documentatie bij afwijking van docs; wasm-graphviz blijft 1.29.2, geen versie-upgrade als oplossing.
- `bash` de exacte Python- en native Project Commands; schone installed-archiveconsumer, strict Vite-build en volledige patchreconstructie volgens stappen hieronder.
- `browser` via `eval` voor de werkelijke LikeC4View-harness, alleen na expliciete browsertoestemming; gebruik een eigen tab, bewaar PNG's onder `<ws>/screens/` en sluit die tab.

**Interfaces:**

- Consumes: Task1 `C4Model`, `CoverageIndex`, `SourceLinkBuilder`; Task2 detailmetadata/forkarchief. Geen wijziging aan `schema_version: 1`, neutrale IDs, status of bronnen.
- `LikeC4IdAllocator(model: C4Model)`; `.allocate(element: SoftwareSystem | Element) -> str`; `.fqn(element_id: str) -> str`. Eén toewijzing voor het hele model, systeem inbegrepen.
- `ViewSpec(view_id: str, level: ViewLevel, scope_element_id: str | None, include_rules: list[str], title: str = "", relation_ids: list[str] | None = None)`. Behoud de bestaande vierargumentencaller; `None` selecteert alle modelrelaties, `[]` selecteert géén. `title` bewaart paginatitels en `relation_ids` de selectiebeslissing; geen DSL terugparsen (Rulings3–4).
- `ViewLevel`: `SYSTEM_CONTEXT="context"`, `CONTAINER="container"`, `COMPONENT="component"`, `FOCUS="focus"`, `TOPIC="topic"`. View-ID's: `index`, `containers`, `components_` + UTF-8-hex van container-id, `focus_` + UTF-8-hex van element-id (ook systeem), `topic_` + definitieve `page.slug`; zichtbare titels blijven namen.
- `build_views(*, model: C4Model, coverage: CoverageIndex, pages: list[DocsitePage], ids: LikeC4IdAllocator) -> list[ViewSpec]`; `project_relations(model: C4Model, visible: set[str], relation_ids: list[str] | None = None) -> dict[tuple[str, str], list[Relation]]` in `views.py`. Selecteer eerst de exacte neutrale relaties, projecteer daarna; geen hierarchyfilter of voorkeur voor directe relaties.
- `LikeC4Writer(*, coverage: CoverageIndex, ids: LikeC4IdAllocator, source_links: SourceLinkBuilder)`; `.write(model: C4Model, views: list[ViewSpec], out_dir: Path) -> None`; uitsluitend de beheerde `likec4/`-directory.
- `build_site_data(*, model: C4Model | None, coverage: CoverageIndex | None, views: list[ViewSpec], ids: LikeC4IdAllocator | None, pages: list[DocsitePage]) -> ArchitectureData`; `build_search_records(*, model: C4Model, data: ArchitectureData) -> list[dict[str, str]]`.
- Native context: voeg aan `LayoutTaskParams<A>` uitsluitend de optionele interne input `relations?: Readonly<Record<RelationId, Relationship<A>>>` toe, met de bestaande coretypes. De DSL-serviceroute geeft de bestaande `model.$data.relations` door bij zowel batch- als individuele layout; `layoutLikeC4Model` doet hetzelfde. Geen nieuw producentveld, outputschema of publiek AutoDoc-adapter-API. Queue en bestaande callers zonder relationcontext behouden hun gewone gedrag.
- Native geometrie: `routeHierarchyEdge<A extends AnyAux>(edge: ComputedEdge<A>, source: DiagramNode<A>, target: DiagramNode<A>): DiagramEdge<A>` in de nieuwe interne `hierarchy-edges.ts`. Deze helper ontvangt uitsluitend een reeds per onderliggende relatie toegelaten hierarchy-edge. `GraphvizParser` behoudt echte `id`, `source`, `target` en `relations`; de relationcontext blijft interne input en verschijnt niet als nieuwe model-/viewentiteit.

**Acceptance:**

- Promise: alle geselecteerde relaties blijven vanuit het neutrale model via de bestaande native keten zichtbaar, correct gericht, afzonderlijk aanklikbaar en controleerbaar; gewone ongemarkeerde LikeC4-semantiek verandert niet.
- Evidence: `test_R1_R6_R10_marked_hierarchy_keeps_selected_relations`, `test_R1_R6_hierarchy_layout_uses_real_boundaries` en `test_R6_hierarchy_exception_does_not_leak` op echte DSL/services, plus oorspronkelijke Python-/Node-contracten en de beide archiveproeven hieronder. Publieke consumerroute `LikeC4.layoutedModel()`: source: `<fork>/packages/language-services/src/common/LikeC4.ts`.
- Evidence: actual DSL-validatie en metadata: source: `<fork>/packages/language-server/src/model/parser/ModelParser.ts`; interne layoutinput en native parsing: source: `<fork>/packages/layouts/src/graphviz/GraphvizLayoter.ts`. Dit zijn wijzigingspunten, geen claim dat de ontbrekende hierarchyondersteuning al werkt.
- Judged by: user — R1–R11-presentatie, veilige details en bruikbare pijlen; concrete consumer-/geometrieasserties en browserbewijs zijn de technische gate.

- [ ] **Step 1: Neem het bestaande rode checkpoint over zonder het opnieuw te bevestigen.** Registreer fixture met acht relaties, focus(app) vijf geselecteerd tegenover één geprojecteerd en zes native validatiefouten uit beide rode rapporten. Bestaande modules, commits, Rulings1–5 en goedgekeurde Task1/2 vormen het startpunt; geen nieuwe “ontbrekende API”-RED of bootstrap.
- [ ] **Step 2: Voeg de drie permanente native consumentregressies toe in `chunkhound-hierarchy.spec.ts`.** Gebruik `createTestServices` en echte DSL/services, niet Builder-SDK of gemockte Graphviz. De eerste controleert alle zes gemarkeerde ancestor/descendantrichtingen, echte nesting, exacte geselecteerde onderliggende IDs en ongewijzigde status/bronnen. De tweede controleert de werkelijk layouted views: eindige bounds/controlpoints, pijlstart en -spits op het juiste echte node-/kader met de native arrowhead-offset, bruikbare labels en verschillende routes voor beide richtingen; niet alleen aantallen of niet-lege punten. De derde controleert afwezige/lege marker en een gemarkeerde naast een ongemarkeerde of niet-geselecteerde relatie: geen verruimde parent-child-toelating of viewlek. Behoud bestaande gewone directe/afgeleide en expanded-boundary-tests, inclusief hun ongemarkeerde geldige relaties. Geen helper-, forwarding-, DOT-string- of snapshottest toevoegen.

  Exacte consumentasserties voor de eerste regressie: de `focus*Ids` hieronder zijn de uit het echte model gelezen `metadata.chunkhound_id`-waarden van alle onderliggende viewrelaties, niet de edge-ID's of opnieuw aangeleverde fixturewaarden. Dezelfde assertions gelden computed én layouted:

  ```javascript
  expect([...focusAppIds].sort()).toEqual(
    [
      'r-app-component',
      'r-component-app',
      'r-sys-app',
      'r-app-sys',
      'r-app-external',
    ].sort(),
  );
  expect([...focusComponentIds].sort()).toEqual(
    [
      'r-app-component',
      'r-component-app',
      'r-sys-component',
      'r-component-sys',
      'r-component-external',
    ].sort(),
  );
  expect([...focusSystemIds].sort()).toEqual(
    ['r-sys-app', 'r-app-sys', 'r-sys-component', 'r-component-sys'].sort(),
  );
  expect([...directTopicTargetIds].sort()).toEqual(['app', 'component']);
  ```

- [ ] **Step 3: Begrens native validatie, relationpredicaten en connection lookup per oorspronkelijke relatie.** DSL-validatie laat de parent-child-uitzondering uitsluitend toe bij een individueel gemarkeerde relatie; ongemarkeerde ongeldige relaties blijven fouten, ook naast een gemarkeerde. Predicaten in `relation-direct.ts` en lookup in `connection/model/find.ts` bewaren daarna precies de geselecteerde relaties. Gebruik echte containment en geparste metadata, geen ID-naamheuristiek of `some(marker)` die een hele connection vrijgeeft. Behoud Ruling5-cleanup en gewone direct/derived-projectie; raak Builder/deployment/dynamic guards niet aan.
- [ ] **Step 4: Voer de nieuwe native regressies uit met `pnpm --filter @likec4/language-server test`.** Model/selectiegevallen moeten na Step3 GREEN zijn; leg voor de nieuwe geometriegevallen de concrete failing aansluitingen/routes vast vóór de layoutfix. Herhaal niet de oorspronkelijke bekende consumer/plugin-RED om haar te bevestigen.
- [ ] **Step 5: Implementeer de begrensde native geometriecorrectie na Graphviz-nodeplaatsing.** Geef relationcontext door in beide `LikeC4Views`-routes en `layout-model.ts`; `GraphvizLayouter` geeft haar intern door aan de parser. Route uitsluitend toegelaten hierarchy-edges met de echte gelegde node-/compoundbounds in `hierarchy-edges.ts`: verbind de kaderrand met de werkelijke kindrand, gebruik afzonderlijke deterministische lanes voor heen/terug en plaats labels buiten nodes met de bestaande bbox-/labelhulpmiddelen. Gebruik native spline-/arrowheadconventies en neem routes/labels mee in diagram-bounds. Laat deze edges niet weg als Graphviz voor de bestaande leafankerregel geen bruikbare edge oplevert; herstel hun geometrie vanuit dezelfde computed edge, zonder extra model/viewnode of relatie. Gewone edges blijven via de bestaande parser lopen. Geen globale missing-edge-suppressie of alternatief layout-/renderpad.
- [ ] **Step 6: Run de drie native Project Commands voor core, language-server en layouts.** Verwacht GREEN voor nieuwe selectie-/geometrie-/begrenzingscontracten én bestaande aggregatie/boundary/layoutcontracten. Verhelp nieuwe regressies gericht; geen generieke guardverwijdering, fixturevernauwing of herpinnen van incidentele source-/snapshotasserties.
- [ ] **Step 7: Verwijder uitsluitend de verliesgevende Python-hierarchycut.** Verwijder de ancestor/descendant-drop en verouderde uitleg in `views.py`. Behoud in `likec4_writer.py::_view_rules` de eindige exclude/reinclude-selectie: node-includes mogen impliciete relaties eerst wissen, maar daarna moeten alle en uitsluitend geselecteerde neutrale IDs terugkomen. De clear-loop is niet de defecte hierarchyfilter; haar verwijderen zou opnieuw buur-van-buurrelaties laten lekken. Behoud andere legitieme projectieregels, titels, metadata en het onderscheid `None` versus `[]`. Schrijf alle drie `.c4`-bestanden met geldige identifiers, escaping, C4-soorten/legenda, native links en bestaande detailpayload. Labels gebruiken alle geprojecteerde relaties, inclusief directe: één titel, geleverd label of twee-/drie+-terugval, maximaal 60 tekens; gemengde pijlen krijgen geen eigen status.
- [ ] **Step 8: Run `uv run pytest tests/autodoc/test_architecture_projection.py -v`.** Behoud `test_site_records_use_final_urls_and_exclude_relations`: exacte publicatie-IDs, directe topicdoelen, definitieve URL's en uitsluitend elementzoekrecords. Zonder model blijft de afgesproken volledige `enabled: false`-payload met lege dictionaries bestaan. Alleen consumentgerichte regressies bij een werkelijk ontbrekende rand toevoegen; geen permanente DSL-bronstringasserties.
- [ ] **Step 9: Verifieer de gewijzigde native bron met oxfmt-check, forklint en forktypes.** Alleen implementer format eerst de eigen gewijzigde TS/JS-bestanden. Rapporteer concrete bestanden, toolversies en nieuwe diagnostics los van bekende baselineproblemen; onderdruk of repareer geen ongerelateerde baseline om een groene totaalclaim te krijgen.
- [ ] **Step 10: Leg de native bronfix vast in de bestaande fork.** Run verplichte Python smoke vanuit execution vóór deze commit; commit uitsluitend de native bron-/consumenttestwijzigingen, met behoud van eerdere Task2/Ruling5-patches. Broncommit is de basis voor build en volledige patch, niet een onaangetoonde dirty build.
- [ ] **Step 11: Bouw en pack exact deze forkcommit.** Run de geserialiseerde forkbuild en daarna forkpack uit Project Commands. Verwacht exit0 en één volledig `likec4`-packagearchief met gepatchte DSL/core/layout, plugin, React/CSS/fonts en notices. Behoud de bestaande tsdown0.23.0 `deps.alwaysBundle`-oplossing voor patched core; verifieer daadwerkelijk dat ook de nieuwe native wijzigingen meekomen.
- [ ] **Step 12: Installeer het archief in een schone consumer en verifieer computed én layouted model plus strict plugin.** Genereer DSL uit de oorspronkelijke acht-relatiefixture, ongewijzigd. De public API `LikeC4.computedModel()` én `LikeC4.layoutedModel()` moeten de exacte Step2-inventarissen met echte endpoints, status, bronnen en nesting behouden. Controleer ook de overige niveaus en relationloze focus. Voeg uitsluitend een aanvullende topiccase met directe container én component toe: beide blijven doelen; alleen hun directe incidentrelaties, geen buur-van-buurlek. Controleer `test_R10_colliding_names_keep_neutral_identity`, `test_R1_R3_R6_views_keep_only_their_explicit_targets`, `test_R2_status_and_sources_survive_projection`, `test_R7_R8_R9_projected_edges_keep_relations_and_bounded_labels`, inclusief non-ASCII/lege/gereserveerde namen, suffixen `-2`/`-3`, quotes/backslashes/regeleinden en 60-tekengrens. Build met `{workspace: 'likec4', throwIfInvalid: true, ai: 'disabled'}` moet slagen; een eigen corrupt DSL-statement moet non-zero falen en na herstel weer slagen. Bewaar inventories/assertie-uitvoer en exacte archive-identiteit onder `<ws>/qa/task-3-fix-r1/`.
- [ ] **Step 13: Bedien dezelfde shipped native views in de echte browserharness.** Gebruik bestaande Task2 Vite/React/LikeC4View-route, geen Task4-assets of tweede renderer. Open voor elk van de drie hiërarchieparen beide richtingen: juiste zichtbare frame-/nodeaansluitingen, leesbare labels, geen kindlus/verdwenen edge en afzonderlijk klikbare pijlen. Klik iedere relatie en controleer oorspronkelijke neutrale endpoints, individuele status/code-doc-bronnen en native endpoint-/focusnavigatie. Herhaal de bestaande directe-plus-afgeleide aggregatie en veilige tekstweergave, inclusief een gemarkeerde naast een gewone geldige relatie. Bewaar concrete waarnemingen en screenshots `<ws>/screens/task-3-hierarchy-shipped-*.png`; alleen metadata of aantallen zijn onvoldoende.
- [ ] **Step 14: Reconstrueer onafhankelijk uit upstream plus de volledige patchset.** Maak `chunkhound.patch` van exact upstream `0375d146...` naar de nieuwe forkcommit, inclusief alle Task2/Ruling5- en nieuwe wijzigingen. Pas haar toe op schone upstreambron, installeer met lockfile, bouw geserialiseerd en pack opnieuw, zonder eerder `dist`, node_modules of archief te hergebruiken. Installeer dit archief in een tweede schone consumer; herhaal Step12 én Step13 volledig, inclusief echte layout, zes richtingen, oorspronkelijke fixture, selectiebegrenzing, aggregatie/security en strict pluginfout. Bewaar eigen rapporten en `<ws>/screens/task-3-hierarchy-reconstructed-*.png`; geen byte-identieke gzip-eis.
- [ ] **Step 15: Werk vendorresources en onderhoudsdocs bij en commit die afzonderlijk.** Leg werkelijke upstream-/forkcommit, archiveversie/-naam/SHA256, volledige patch en herbouwcommando's vast; behoud licenties en schrijf geen verzonnen manifestwaarden. README noemt de metadata-begrenzing, native geometrieacceptatie en beide archiveproeven. Run verplichte Python smoke vóór de afzonderlijke resourcecommit.
- [ ] **Step 16: Rond de Pythonprojectiefix af met AutoDoc-suite, lint/types en verplichte smoke.** Werk alleen het eigen changelogdeel bij en verwijder eigen tijdelijke proefcode nadat bewijs is vastgelegd. Commit uitsluitend de gewijzigde projectiemodules, eventuele consumenttest en changelog. Rapporteer bewezen GREEN versus bekende baselinefailures; geen volledige-suite-GREEN claim zonder uitvoer.
- [ ] **Step 17: Geef de fix terug aan dezelfde coördinator voor onafhankelijke Task3-re-review.** Rapporteer native-, resource- en Pythoncommits plus bewijs per acceptatiecriterium, inclusief beide schone archives/browserproeven. De Important sluit uitsluitend bij aangetoond behoud én juiste layout/bediening van alle zes richtingen; geen waiver of overdracht van de blocker aan Task4. Behoud de oorspronkelijke taak-/dispatchgeschiedenis en retained implementer tot review akkoord is. Pas daarna Task4 hervatten.

### Task 4: Maak de interactieve Astro/React-kaartassets

**Files:** Create `chunkhound/autodoc/assets/src/components/ArchitectureMap.astro`, `ArchitectureMap.tsx`, `ArchitectureMiniMap.astro`, `ArchitectureMiniMap.tsx`; Create `chunkhound/autodoc/assets/src/pages/architecture/index.astro`. Geen productiewriteromleiding of placeholderkaart; deze assets werken in de echte tijdelijke Astro-consument uit deze taak.

**Classes:** consumeert `ViewSpec`/`ArchitectureData`; geen nieuwe domeinklassen.

**Read:** spec “Views en bediening”, “Onderdelen”, directe topicdoelen en tekstgrenzen; taak 3 publicatie-JSON; `chunkhound/autodoc/assets/src/layouts/DocLayout.astro`, `chunkhound/autodoc/assets/src/styles/global.css`; projectrichtlijnen TS/JS. Officiële Astro client-directives, gepinde LikeC4 `packages/vite-plugin/src/modules.d.ts` en `packages/diagram/src/{ReactLikeC4,LikeC4View}.tsx`.

**Tools:**

- `mcp__docs_mcp__search_docs` `{library:"likec4",version:"1.60.0",query:"ReactLikeC4 onNavigateTo LikeC4View browser viewId virtual react module",limit:3}` vóór componentkeuze.
- `read` `https://docs.astro.build/en/reference/directives-reference/#client-directives` vóór Astro-wrappercode; docs-mcp dekt Astro major 7 niet.
- `read` `https://raw.githubusercontent.com/likec4/likec4/0375d146f8de2eb919033bd3b43b3701194f518b/packages/diagram/src/ReactLikeC4.tsx` vóór navigatieprops.
- `read` `https://raw.githubusercontent.com/likec4/likec4/0375d146f8de2eb919033bd3b43b3701194f518b/packages/diagram/src/LikeC4View.tsx` vóór minikaartprops.
- `read` `https://raw.githubusercontent.com/likec4/likec4/0375d146f8de2eb919033bd3b43b3701194f518b/packages/vite-plugin/src/modules.d.ts` vóór modelgebonden exports/providergebruik.
- `bash` schone site-install/build/preview, scoped oxfmt/oxlint uit de forktooling, Python smoke.
- `eval` browser: eigen tab; alle view-/URL-/detailscenario's; screenshots `<ws>/screens/task-4-map.png` en `task-4-unknown-view.png`; sluiten.

**Interfaces:**

- Consumes: `ArchitectureData` uit taak 3; `likec4:react` exports `ReactLikeC4`, `LikeC4View` en het modelgebonden provider-/hook-API volgens de gepinde bron. Niet de ongebonden primitive gebruiken zonder modelprovider.
- Produces: `ArchitectureMap({data}: {data: ArchitectureData}): ReactElement` en `ArchitectureMiniMap({viewId}: {viewId: string}): ReactElement`, beide default exports; `ArchitectureMap.tsx` exporteert ook het type `ArchitectureData` voor de type-only mini-import. Astro-wrappers nemen respectievelijk `data` en `viewId` aan en importeren hun TSX-kind rechtstreeks.
- `ArchitectureMap` leest de query bij openen, beheert de actieve view en synchroniseert navigatie, gekopieerde URL en browser back/forward. Mini gebruikt `LikeC4View`; de volledige kaart `ReactLikeC4` met pan/zoom en de bestaande detail-/navigatieacties.

**Acceptance:**

- Promise: een link opent exact de gekozen view; onbekende view toont context plus melding; kleine kaarten en volledige kaart zijn echt interactief.
- Evidence: onderstaande echte browserproef, build en screenshots; Astro-hydratatie: source: `read` `https://docs.astro.build/en/reference/directives-reference/#client-directives`; LikeC4-props/provider: source: `read` `https://raw.githubusercontent.com/likec4/likec4/0375d146f8de2eb919033bd3b43b3701194f518b/packages/vite-plugin/src/modules.d.ts`.
- Judged by: user — navigatie, legenda, leesbaarheid, details en zichtbare foutmelding.

- [ ] **Step 1: Leg het failing browserscenario vast in een tijdelijke Astro 7.4.2-consument van de taak 3-gegevens en echte fork.** Open `/architecture/?view=<focus-id>`; zonder nieuwe assets is de vereiste kaart/navigatie afwezig. Deze tijdelijke consument gebruikt dezelfde versies, pluginopties en bestaande AutoDoc-layout als productie; geen alternatieve renderer.
- [ ] **Step 2: Implementeer de vijf assets en type-only `ArchitectureData`-grens.** Beide wrappers gebruiken `client:only="react"`; volledige route krijgt de bestaande layout. Houd URL-state in de volledige kaart, reageer op `popstate` en native `onNavigateTo`, controleer viewlidmaatschap vóór renderen. Een onbekende id toont een leesbare melding en `index`; geen crash of stil verdwijnende kaart. Geen `dangerouslySetInnerHTML` voor modeltekst.
- [ ] **Step 3: Format/lint uitsluitend de nieuwe TSX; bouw en start de tijdelijke site.** Verwacht geslaagde Astro-build, geen providerfout, één React-/diagramruntime en werkelijke stijlen/fonts. Geef de component bij de proef de gegevens uit taak 3, niet handmatig afwijkende view-id's.
- [ ] **Step 4: Bedien context → containers → componenten → elementdetails → Focus-view; klik de gemengde pijl en een bron/topiclink.** Kopieer de focus-URL naar een nieuwe eigen tab, controleer dezelfde view, gebruik back/forward en probeer een onbekende id. Controleer miniweergave en een relationloos element; geen afkappen van een groter model. Bewaar screenshots, DOM-/consolewaarnemingen en sluit alle eigen tabs. Dit is runtimebewijs, geen permanente test van intern HTML of formuleringen.
- [ ] **Step 5: Werk changelog bij, run verplichte smoke en commit uitsluitend de vijf assets en eigen changelogwijziging.** Commit: `feat(autodoc): add interactive architecture map assets`.

### Task 5: Publiceer kaart, gewone site en assets-only via de bestaande writer

**Files:** Modify `chunkhound/autodoc/{models.py:32-79,generator.py:209-290,site_writer.py:40-159,site_writer_renderers.py:36-81,123-188}`; Modify `chunkhound/autodoc/assets/{astro.config.mjs,package.json,tsconfig.json,src/layouts/DocLayout.astro,src/styles/global.css}`. Test Modify `tests/autodoc/test_docsite_generation.py`, `test_docsite_ia_artifacts.py`, `test_autodoc_assets_only.py`; Create `tests/autodoc/test_architecture_generation.py`. Alle testpaden staan onder `tests/autodoc/`.

**Classes:** creëert `SiteExtras`; consumeert bestaande `DocsiteSite` ongewijzigd, `DocsitePage`, `NavGroup`, `GlossaryTerm`, `C4Model`, `ModelLoader`, `CoverageIndex`, `LikeC4IdAllocator`, `SourceLinkBuilder`, `ViewSpec`, `LikeC4Writer` en `ArchitectureData`.

**Read:** model §2/§5; spec volledige generatie, assets-only, foutgrenzen; alle genoemde Pythonbestanden plus `chunkhound/autodoc/{site_writer_dirs.py,template_loader.py,docsite.py}` en `chunkhound/api/cli/commands/autodoc.py:35-55`; bestaande tests; `skill://test-driven-development` en projectrichtlijnen.

**Tools:**

- `lsp` references voor `write_astro_site` en `_render_search_index` vóór hun signaturewijziging; huidige writerinventaris: productie `generator.py`, tests generation/IA, en na upgrade geen byte-manifesttest meer.
- `mcp__docs_mcp__search_docs` `{library:"likec4",version:"1.60.0",query:"Vite plugin workspace throwIfInvalid Astro integration",limit:3}` vóór config-integratie.
- `read` `https://docs.astro.build/en/guides/framework-components/#hydrating-server-rendered-components` vóór Astro-layoutintegratie; major-7-docsgat via officiële bron.
- `read` `https://vite.dev/guide/features#glob-import` vóór wrapperontdekking; Vite-8-docsgat via officiële bron.
- `bash` AutoDoc-test/lint/types/smoke en schone site-install/build/preview uit Project Commands; echte CLI `uv run chunkhound autodoc --assets-only --out-dir <site>`.
- `eval` browser: eigen tab, home/topic/search/kaart-proef; screenshots `<ws>/screens/task-5-topic.png` en `task-5-no-model.png`; sluiten.

**Interfaces:**

- Consumes: alle taak 1/3-API's en taak 4-assets; `load_text(relative_path: str) -> str`, `load_bytes(relative_path: str) -> bytes` voor package-resources.
- `SiteExtras(nav_groups: list[NavGroup] | None = None, glossary_terms: list[GlossaryTerm] | None = None, homepage_overview: str | None = None, architecture: C4Model | None = None)` in bestaande `models.py`.
- `write_astro_site(*, output_dir: Path, site: DocsiteSite, pages: list[DocsitePage], index: CodeMapperIndex, allow_delete_topics_dir: bool, extras: SiteExtras, log_warning: Callable[[str], None] | None) -> None`. De callback blijft apart van site-inhoud en bereikt `CoverageIndex` voor ontbrekende topickoppelingen; generator geeft zijn bestaande callback door. `input_dir` komt uit bestaande `site.source_dir`; geen vijfde bundelveld.
- `write_astro_assets_only(*, output_dir: Path) -> None` blijft ongewijzigd. `generate_docsite(...) -> DocsiteResult` behoudt bestaande publieke signature en loggingroute.
- `_render_search_index(pages: list[DocsitePage], architecture_records: list[dict[str, str]] | None = None) -> str`; bestaande topicrecordkeys/semantiek blijven gelijk. Nieuwe records gebruiken dezelfde `title/slug/description/body/url`-vorm en focus-URL; `body` bevat soort en status.

**Acceptance:**

- Promise: gewone site blijft werken; kaart verschijnt alleen met model; topicdoelen/search/bronlinks werken; full-generation en assets-only hebben verschillende, veilige data-eigendom.
- Evidence: lifecycle-/CLI-contracten hieronder plus werkelijk gebouwde sites met en zonder kaart; pluginfout blijft fataal. Conditionele plugin/import en Astro-wrapperhydratie: source: `mcp__docs_mcp__search_docs`; glob-ontdekking: source: `read` `https://vite.dev/guide/features#glob-import`.
- Judged by: user — zichtbare navigatie en behoud/verwijdergrens; tests bewijzen databehoud en correcte selectie.

- [ ] **Step 1: Schrijf failing generatiecontracten.** `test_full_generation_removes_only_owned_architecture_outputs`: genereer met model, voeg eigen bestand toe, hergenereer zonder/ongeldig model; gewone topics/IA blijven correct, eigen bestand blijft, oude beheerde DSL/route/components/archive verdwijnen, JSON expliciet leeg en alleen topiczoekrecords. `test_no_model_preserves_unowned_paths_and_disables_map_imports`: begin zonder eigen kaartmetadata maar met gebruikersbestanden onder `likec4/` en op een gereserveerd kaartpad; behoud die bij eerste én herhaalde generatie zonder model, bouw zonder kaartdependencies. `test_assets_only_preserves_architecture_and_ignores_changed_input_model`: wijzig producentmodel, run assets-only; oorspronkelijke `.c4`, JSON en topics blijven ongewijzigd, presentatie vernieuwd. `test_missing_model_is_warning_not_cli_failure`: echte CLI met vastgelegde topiccleanupresponse op uitsluitend de LLM-netwerkgrens; exit 0, waarschuwing met oorzaak/hersteladvies en bruikbare gewone site. Behoud metadata-loze assets-only en topicdirectorybescherming.

  Concrete assertions na respectievelijk volledige hergeneratie en assets-only:

  ```python
  assert json.loads(architecture_path.read_text())["enabled"] is False
  assert user_file.read_text() == original_user_content
  assert not owned_architecture_page.exists()
  # In de afzonderlijke assets-only-test:
  assert architecture_path.read_bytes() == original_architecture_data
  assert model_dsl_path.read_bytes() == original_model_dsl
  assert topic_path.read_text() == original_topic_content
  ```

- [ ] **Step 2: Run `uv run pytest tests/autodoc/test_architecture_generation.py tests/autodoc/test_autodoc_assets_only.py -v`.** Verwacht FAIL op ontbrekende publicatie/lifecycle, niet op bronstringasserties. Verwijder nog aanwezige incidentele template-/markupasserties in de geraakte tests; herintroduceer geen door de upgrade verwijderde hashmanifesttests.
- [ ] **Step 3: Voer de writer-cutover en generatievolgorde uit.** Na `load_topics` laadt `ModelLoader` bij de gekozen `index_path`; na cleanup maakt generator `SiteExtras`. Migreer alle references naar de nieuwe writergrens. Schrijver bouwt coverage/views/DSL/sitegegevens en voegt architectuurzoekrecords toe. Topic-Markdown blijft buiten kaart-UI; de layout koppelt via de bestaande definitieve topicslug.
- [ ] **Step 4: Publiceer de optionele runtime en de lifecycle.** Lees vóór overschrijven bestaande eigen `architecture.json` met `schemaVersion: 1` én `enabled: true` als bewijs van een eerder gepubliceerde kaart. Alleen dan mag full-generation de vaste beheerde kaartpaden opruimen; lege/ontbrekende kaartmetadata geeft geen eigendom over gelijknamige gebruikersbestanden. Kopieer kaartassets/archive voor een bruikbaar model of bestaande kaartsite bij assets-only. Conditioneer React-/pluginimports én dependencies op ingeschakelde kaartgegevens en `likec4/`, niet enkel directorybestaan. Package gebruikt `likec4: file:vendor/likec4/likec4-1.60.0-chunkhound.1.tgz` en de gepinde frontendversies. Verwijder alleen de drie beheerde DSL-bestanden, route, vier componenten, archief en lege eigen directories; geen recursive wipe. Behoud topicdirectorybescherming. Assets-only schrijft lege gegevens uitsluitend als die ontbreken; bestaande JSON/DSL/topics blijven intact. Zonder geldige site-metadata blijven package/README zoals bestaand gedrag.
- [ ] **Step 5: Integreer layout/home/search.** Ontdek Astro-wrappers via `import.meta.glob`; zijbalkkaartlink en homecontext alleen bij `enabled`. Topic “Hoort bij” en minikaart volgen uitsluitend `topics[slug].directElementIds`/`view`; rolled-up ouders en buren worden geen links. Geen directe dekking betekent geen regel/minikaart. Zoekresultaten openen juiste focus, relaties zijn niet zoekbaar als architectuurelement.
- [ ] **Step 6: Run contracten, AutoDoc-suite, lint/types en drie echte siteproeven.** (a) uv-Python-harness roept echte `generate_docsite` met `llm_manager=None` aan op topicfixture plus model; `npm install`, build, preview en browser: home → kaart → topic → beide directe doelen/minikaart → zoekfocus. (b) Hergeneratie zonder/ongeldig model bouwt gewone site en bewaart eigen bestanden. (c) Echte CLI assets-only op kaartsite én oudere site, daarna beide bouwen; oorspronkelijke kaartdata blijven gelijk. Bewaar waarschuwingen/exitcodes en screenshots; geen Node-build vanuit Python.
- [ ] **Step 7: Werk gegenereerde `assets/README.md` en `site/src/pages/docs/cli-reference.md` bij met modelplaatsing, waarschuwingen, bron-/kaartlinks en assets-onlygrenzen.** Werk changelog bij, run verplichte smoke en commit uitsluitend de genoemde productie-/test-/docbestanden: `feat(autodoc): publish optional C4 maps and preserve presentation updates`.

### Task 6: Bewijs distributie en de complete gebruikersroute

**Files:** Modify `scripts/verify_autodoc_wheel_resources.py`, `.github/workflows/ci.yml`, `chunkhound/autodoc/assets/vendor/likec4/README.md`, `chunkhound/autodoc/assets/README.md`, `site/src/pages/docs/cli-reference.md`, `CONTRIBUTING.md`, `CHANGELOG.md`; Modify `pyproject.toml:165-175` alleen als echte wheel/sdist-inspectie een inclusiegat aantoont. Geen extra runtimeverpakking naast de bestaande resourcebenadering.

**Classes:** consumeert bestaande `DocsiteSite`/`DocsitePage`, alle nieuwe contract-/publicatie-API's en de twee werkelijke forkdetailcomponenten; geen nieuwe domeinklassen.

**Read:** spec “Distributie”, volledige acceptatietabel en bewijsgrenzen; `pyproject.toml:1-3,165-185`, `hatch_build.py:137-193`, `scripts/verify_autodoc_wheel_resources.py`, `.github/workflows/{ci,release}.yml`; projectrichtlijnen, taak 2-manifest en onderhouds-README.

**Tools:**

- `read` het werkelijke forkmanifest, bronpatch en wheel/sdist-inhoud via bestaande archivelezers; geen hashclaim zonder berekening op het gebouwde archief.
- `bash` wheel/sdist/resourcecommando's, volledige pytest-suite, lint/types en smoke uit Project Commands; schone site-install/build/preview vanuit de gedistribueerde resources.
- `eval` browser: eigen tab; complete acceptatieroute en screenshots `<ws>/screens/task-6-end-to-end.png`; sluiten.

**Interfaces:**

- Consumes: alle eerdere taakgrenzen en `verify_autodoc_wheel_resources.py` bestaande CLI `wheels...`; deze CLI blijft bruikbaar.
- Produces: wheel én sdist met alle benodigde kaartassets, bronpatch/manifest/notices en echte `.tgz`; verifier controleert resourceleesbaarheid, manifestintegriteit en uitvoerbare forkexports vanuit het wheel, niet incidentele templatebytes.
- Geen claim `map → AutoDoc` op alleen fixtures. Zodra echte producentuitvoer beschikbaar is, gebruik die voor dezelfde gebruikersroute; anders rapporteert de coordinator de ontbrekende producentacceptatie expliciet en vraagt om aanlevering, niet om scopeverlaging of een gefingeerde succesclaim.

**Acceptance:**

- Promise: een gebruiker van het gebouwde Python-package krijgt de aangepaste kaart, niet toevallig upstream-code uit een ontwikkelcheckout; updates zijn herbouwbaar en licenties blijven meegeleverd.
- Evidence: werkelijk wheel/sdist, bestaande verifier plus schone venv/site-installatie, build/browser en finale criteria R1–R11; package-inclusie: source: `pyproject.toml`.
- Judged by: user — volledige kaart-/topicroute en producentacceptatie; kwaliteitscommando's en artifactinspectie onderbouwen de technische grens.

- [ ] **Step 1: Breid de bestaande resourceverifier uit met het distributiecontract.** Verwijder de bestaande inhoudsassertie voor `navData` in de template; controleer in plaats daarvan dat de gedistribueerde resources een echte kaartsite kunnen leveren. Verifieer archiefnaam/versie/SHA tegen het manifest en benodigde exports/notices; dit beschermt artifactintegriteit, niet byte-stabiele templates. Laat een ontbrekend archief of foutieve checksum in een tijdelijke kopie falen en herstel daarna; geen permanente bronkopietest.
- [ ] **Step 2: Bouw wheel én sdist en voer de verifier uit.** Inspecteer beide archives op de resources en installeer het wheel met `uv pip install --python <ws>/wheel-venv/bin/python <wheel>` in een nieuwe `uv venv <ws>/wheel-venv`. Genereer vanuit een cwd buiten de repo een site met echte gedistribueerde imports, fixturetopics/model en bestaande LLM-loze API-route. Installeer npm-dependencies in die schone site en bouw/start haar. Verwacht de eigen forkversie en zichtbare aangepaste detailvelden, zonder broncheckoutimports. Bewijs sdist-herbouw naar een wheel dat dezelfde resourcecontracten haalt.
- [ ] **Step 3: Leg dezelfde wheel-resourcecontrole vast in de bestaande CI-wheelbouwstap met Node 24.** Gebruik geen flaky netwerkruntime in gewone unit-tests; schone npm-installatie/build hoort bij de expliciete distributie-integratieproef. Run de exact toegevoegde CI-commando's lokaal vóór commit.
- [ ] **Step 4: Bedien de volledige spec-acceptatietabel in de geïnstalleerde site.** Controleer meerdere repositories/niveaus, status/code-config-doc, gemengde pijl, labels/terugval, veilige bronlinks, relationloze focus, beide directe topicdoelen, ontbrekende dekking, zoeken, gekopieerde view en onbekende id. Controleer ook de eerder gebouwde gewone/oudere sites. Noteer elk criterium met concreet runtime-/testbewijs, geen algemene “werkt”-claim. Gebruik echte producentuitvoer voor de pipelineclaim als die beschikbaar is; anders is dat een benoemde afhankelijkheid vóór finale gebruikersacceptatie.
- [ ] **Step 5: Werk gebruikersdocs, contributie-/forkupdate-instructies en changelog bij met de daadwerkelijke commando's en bewijsgrenzen.** Verwijder eigen tijdelijke harnesses na vastlegging van rapporten/screenshots; geen nieuwe scaffolds meeleveren. Run volledige suite, lint/types en verplichte smoke; commit alleen de taakbestanden: `test(autodoc): verify packaged C4 map distribution`.

## Modeldekking en finale review

| Regels / klasse                                              | Eigenaar en bewijs                                                                              | Niet in deze software                                                                               |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| R1/R11: systeem/niveaus/repositories                         | taken 1, 3, 6: contract, echte nesting, zes native hierarchyrichtingen en meerdere repositories | Producent bepaalt systeemindeling en externe onderbouwing                                           |
| R2/R3/R6: bronnen/status/relaties                            | taken 1–3, 6: exacte selectie, beide archive-/layout-/browserproeven en individuele details     | Producent classificeert bronnen/status en ontdekt relaties; geen AutoDoc-heranalyse                 |
| R4/R5: bestanden/overlap/unie                                | taken 1, 5: named R5-tests en directe UI                                                        | Unieke componenttoewijzing van implementatiebestanden wordt door map bepaald, niet opnieuw berekend |
| R7/R8/R9: projectie en labels                                | taken 2–3, 6: echte geprojecteerde pijl, alle relaties en labelgrenzen                          | LLM-bundeling/cache/semantische samenvatting uit titels behoort aan producent                       |
| R10: identiteit                                              | taken 1, 3: neutral-id-behoud en botsende/non-ASCII namen                                       | Identiteitsberekening/evolutie behoort aan producent; slugs geen stabiele ids                       |
| Alle contractdataclasses/enums                               | taak 1 Classes, taak 3 consumeert ze                                                            | Geen nieuwe database                                                                                |
| `ViewSpec`, `ViewLevel`, `LikeC4IdAllocator`, `LikeC4Writer` | taak 3 Classes/Interfaces                                                                       | Geen tweede renderer                                                                                |
| `ModelLoader`, `CoverageIndex`, `SourceLinkBuilder`          | taak 1 Interfaces, taak 5 consumeert ze                                                         | Geen servicelaag                                                                                    |
| `SiteExtras`, `DocsiteSite`, `DocsitePage`                   | taak 5 Classes/Interfaces; pagina's ook taken 1/3                                               | Bestaande site blijft sitemetadata                                                                  |

Iedere taak krijgt één implementer en daarna onafhankelijke taakreview. Task1/2 blijven goedgekeurd; na gebruikersgoedkeuring van dit gewijzigde plan hervat de bestaande coördinator uitsluitend de Task3-fix met retained implementer en onafhankelijke re-review, daarna 4 → 5 → 6. De finale reviewer controleert de volledige specacceptatietabel, bron-/toolrapportage, commits en echte implementerbewijzen en draait exact de niet-muterende Project Commands. Geen extra reviewers of herhaling van al bewezen browser-/testscenario's zonder benoemd risico. Daarna gebruikersacceptatie en `finishing-a-development-branch`; geen push, merge of worktreeverwijdering zonder de toepasselijke toestemming.

## Sources en planbewijsgrenzen

- Lokale code: `generator.py:222-284`, `index_loader.py:25-105`, `models.py:32-79`, `site_writer.py:40-159`, `site_writer_renderers.py:36-81,131-188`, `template_loader.py:6-34`; paden hierboven volledig uitgewerkt in de taakblokken.
- LSP-references `write_astro_site` op 2026-10-29: productiecaller `generator.py`, tests `test_docsite_generation.py`, `test_docsite_ia_artifacts.py` en de op deze branch nog aanwezige outputmanifesttest; upgradecommit verwijdert die laatste. Alle callers worden opnieuw via LSP gecontroleerd vóór de cutover.
- Upgradebron: `c7a2a7fc955bbbfc99e906522e9e41f1188f8adb` staat op `main`; omvat AutoDoc/projectwebsite Astro 7.4.2, Node 24-CI en verwijdering van incidentele tests. Niet toegepast tijdens planning; huidige ontwerpbranch bewaart de goedgekeurde documenten.
- Upstreambronbasis voor ieder genoemd forkpad: `https://raw.githubusercontent.com/likec4/likec4/0375d146f8de2eb919033bd3b43b3701194f518b/`. [Buildconfig](https://github.com/likec4/likec4/blob/0375d146f8de2eb919033bd3b43b3701194f518b/packages/likec4/tsdown.config.mts), [root scripts](https://github.com/likec4/likec4/blob/0375d146f8de2eb919033bd3b43b3701194f518b/package.json), [virtuele exports](https://github.com/likec4/likec4/blob/0375d146f8de2eb919033bd3b43b3701194f518b/packages/vite-plugin/src/modules.d.ts), [plugin/Astrohandleiding](https://github.com/likec4/likec4/blob/0375d146f8de2eb919033bd3b43b3701194f518b/apps/docs/src/content/docs/tooling/vite-plugin.mdx).
- Grounding: geen eigen ChunkHound-index of gemounte ChunkHound-MCP; `find` faalde met zoekmodel-404. Gerichte grep/read en controller-LSP plus twee read-only designonderzoeken gebruikt, geen index gestart/geleend. LikeC4 1.60.0 heeft docs-mcp-dekking; Astro major 7, Vite/React/React DOM/@astrojs/react niet, daarvoor officiële bronnen volgens de spec.
- Planning heeft geen productcode, dependencies, fork-/consumerbuild of browser in execution gewijzigd/gestart. Bestaande executionbewijzen zijn gelezen, niet door design opnieuw uitgevoerd of als hierarchy-GREEN gebruikt. De oorspronkelijke acht-relatiefixture, bekende rode output en O-MAP-afhankelijkheid blijven staan. De geschreven spec en dit concrete gewijzigde plan zijn afzonderlijk goedgekeurd (besluitenlog rij 64 en 67); die goedkeuring is geen bewijs dat de native reparatie al werkt.
- Oxfmt-cli: [officiële opties](https://oxc.rs/docs/guide/usage/formatter/cli.html); fork-lockfile/rootpackage leggen oxfmt0.75.0 en pnpm11.28.5 vast. Native tests komen uit de bestaande `test`-scripts van core/language-server/layouts. De geserialiseerde build is in `<ws>/task-3-report.md:93-94` bewezen na de declarationrace.
- Hervattingsbronnen: `<ws>/design-feedback.md`, `<ws>/progress.md` (Rulings1–5), `<ws>/task-3-report.md:113-135` en `<ws>/qa/task-3-fix-r1/`; bronbasis fork `818a388bfee525a318b3536dea4f5870fb8c0331`. Task2- en Ruling5-acceptatie zijn geen vervangend bewijs voor de zes geweigerde hierarchyrichtingen.
- LSP-references `LayoutTaskParams` op 2026-10-30: 21 verwijzingen in `GraphvizLayoter.ts`, `QueueGraphvizLayoter.ts`, package-index en `LikeC4Views.ts`; gerichte bronlezing vond daarnaast `layout-model.ts`. De huidige taskinput bevat alleen `view`/`styles`, computed edges bevatten relatie-ID's en de oorspronkelijke metadata staat in `model.$data.relations`: daarom een interne read-only relationcontext, geen nieuwe producentmarker. Bron: `<fork>/packages/core/src/types/{view-computed,model-data}.ts`, `<fork>/packages/language-server/src/views/LikeC4Views.ts:161-205,275-287`, `<fork>/packages/layouts/src/graphviz/{GraphvizLayoter,GraphvizParser,layout-model}.ts`.
- Geometriekeuze voor deze uitvoering: native nodeplaatsing/hiërarchie behouden; alleen individueel gemarkeerde hierarchy-edgegeometrie vanuit echte node-/compoundbounds corrigeren in de bestaande Graphvizparserketen. De bestaande leafankerregel bewijst geen juiste kaderrand; modelinventaris, werkelijke pijlaansluitingen en browserbediening zijn daarom alle drie verplicht. Dit is een voorgeschreven implementatie, geen uitgevoerde layout-GREEN.
