# AutoDoc C4-kaart — ontwerp

Status: onafhankelijke review uitgevoerd; één open UX-keuze (O-TOPIC-UI) vóór gebruikersgoedkeuring van de geschreven specificatie; geen implementatiegoedkeuring.

Besluiten: [besluitenlog](../decisions/2026-10-27-autodoc-c4-map.md), in het bijzonder rij 32–48. Model: [autodoc-c4-map](../models/autodoc-c4-map.md). Geen programregister; de afzonderlijke `map`-designsessie is een afhankelijkheid, niet stilzwijgend onderdeel van deze uitvoering.

## Doel en afbakening

Een lezer van een door AutoDoc gegenereerde site kan de onderbouwde architectuur verkennen van systeemcontext via containers naar componenten, de bijbehorende topics vinden en vanuit elementen en relaties naar bronbestanden gaan. De kaart onderscheidt aangetroffen architectuur van alleen gedocumenteerde architectuur. Zij presenteert geen nieuwe architectuurclaims op basis van topicsamenvattingen.

`map` onderzoekt en exporteert het renderer-onafhankelijke model. AutoDoc leest dat model, koppelt definitieve topic-URL's, vertaalt naar LikeC4 en publiceert de kaart. De LikeC4-fork verzorgt rendering en aangepaste detailvensters. De browser analyseert geen code en doet geen LLM-aanroepen voor de kaart (rij 15, 30, 38, 44).

**In scope:** de AutoDoc-consument, de hieronder vastgelegde producentgrens, de benodigde LikeC4-aanpassingen, het meegeleverde forkarchief en integratie met de gegenereerde site, inclusief hergeneratie en `--assets-only`.

**Buiten scope:** architectuuronderzoek en exportimplementatie in `map` (`map-structuur-design`); herhalen van de afzonderlijke Astro/Vite-upgrade; codeniveau, dynamische/sequence-diagrammen, componentgroepen, viewlimieten, databasefederatie, extra externe repositoryconfiguratie, editorlinks en broncodefragmenten in de site. Geen nieuwe service-, Strategy- of Factory-laag.

De uitvoering sluit aan op de afzonderlijk goedgekeurde Astro 7.4.2/Vite 8.3.5-upgrade uit `autodoc-c4-map`. Deze designcheckout bevat de oude template nog; dat is geen reden om de upgrade opnieuw uit te voeren. Het combineren van de benodigde wijzigingen hoort expliciet in het latere implementatieplan (rij 18–20 en de designbrief).

## Domain model

Zie [model §1: begrippen, regels en voorbeelden](../models/autodoc-c4-map.md#1-domeinmodel). De lokale regels R1–R11 verwijzen naar het besluitenlog, niet naar dossier-id's.

Eén geïndexeerde root/scope levert één softwaresysteem, eventueel met meerdere geneste repositories. Aangetroffen containers en componenten hebben expliciete implementatiebestanden; een bestand hoort bij hoogstens één component en gedeelde code mag rechtstreeks bij een container horen. Personen en externe systemen vereisen eveneens onderbouwing. Een component is het diepste getekende niveau, niet automatisch een directory.

Code of configuratie als bron geeft status `aangetroffen`; uitsluitend documentatie geeft `gedocumenteerd`. Alleen gedocumenteerde interne onderdelen mogen zonder implementatiebestanden bestaan, maar hebben geen directe topicdekking. Topicdekking is bestandsoverlap, geen architectuurrelatie. Samengevoegde pijlen houden alle onderliggende relaties met hun afzonderlijke bronnen en status; zij krijgen geen eigen status.

Open issues, gelijk aan model §1:

- **O-DOSSIER · zonder dossier.** Handgeschreven model; geen automatische dossiercontrole of I3-checkpoint. I3-status: niet van toepassing, zonder dossier.
- **O-MAP · Producent buiten deze scope.** Structuuranalyse, bronclassificatie en identiteitsevolutie worden in `map-structuur-design` uitgewerkt. Die sessie is niet automatisch gesynchroniseerd met latere contractbesluiten. Afstemming is een afhankelijkheid, geen uitgevoerde overdracht; deze sessie stuurt daar niet ongevraagd berichten heen.
- **O-TOPIC-UI · Selectie in de topicgerichte weergave.** De onafhankelijke review vraagt te bepalen of `Hoort bij` en de topickaart uitsluitend direct gedekte elementen gebruiken of ook opgerold gedekte voorouders. Ook het geval met directe dekking van zowel een container als een component moet expliciet zijn. Dit is een open gebruikerskeuze, geen door de planner te kiezen standaard.

## Producentgrens: JSON-model

### Selectie en velden

Bij de gekozen `<scope>_code_mapper_index.md` hoort precies het naastliggende `<scope>_c4_model.json`. Gebruik dezelfde bestandsstam als de daadwerkelijk gekozen index, niet een onafhankelijk gevonden model van een andere scope. De bestaande indexselectie blijft leidend (`code_mapper/writer.py:83`, `autodoc/generator.py:222-236`; rij 39).

Het contract heeft `schema_version: 1` en de volgende objecten. Veldnamen zijn letterlijk JSON-namen; interne Python-attributen mogen duidelijkere namen krijgen volgens de vertaaltabel.

| Onderdeel         | Velden en betekenis                                                                                                                                   |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repositories[]`  | `id`, `path`, `remote_url` (string of `null`), `commit`; provenance per repository, geen globale commit.                                              |
| `system`          | `id`, `name`, `description`; precies één eigen systeem, apart van `elements`.                                                                         |
| `elements[]`      | `id`, `kind`, `parent`, `name`, optionele `description`, `technology`, `status`, `files[]`, `sources[]` met bron-id's.                                |
| `relations[]`     | `id`, `source`, `target`, `title`, `technology`, `status`, `sources[]` met bron-id's. Endpoints verwijzen naar het systeem of een element.            |
| `merged_labels[]` | `source`, `target`, `relations[]` met alle onderliggende relatie-id's, `label`; voor benodigde projectieparen met minstens twee verschillende titels. |
| `topics[]`        | `file`, `covers[]`; iedere dekking bevat `element` en `files[]` met unieke gedeelde geciteerde implementatiebestanden.                                |
| `sources[]`       | `id`, `repository`, `path`, `start_line`, `end_line`, `kind`; volledige brongegevens, niet gereconstrueerd uit een mogelijk afgekorte Sources-footer. |

`kind` voor elementen: `container`, `component`, `person`, `externalSystem`. Bronsoorten: `code`, `config`, `doc`. Statuswaarden: `aangetroffen`, `gedocumenteerd`. Containers hebben het systeem als ouder; componenten een container; personen en externe systemen staan buiten die hiërarchie (`parent: null`). Lege technologie is toegestaan wanneer die niet is aangeleverd; AutoDoc verzint haar niet. Neutrale ids zijn onderling ondubbelzinnig en door `map` bepaald, niet afgeleid uit weergavenamen of LikeC4-FQN's (rij 26, 39–41; model R1/R10).

AutoDoc herclassificeert bronnen en status niet. Het bewaart de opgegeven bronnen per element en per relatie. Een aanwezig model zonder relaties blijft bruikbaar; ontbrekende architectuur wordt niet uit topics aangevuld.

### Padruimte en topickoppeling

`elements[].files`, `topics[].covers[].files`, `sources[].path` en `repositories[].path` gebruiken POSIX-paden vanaf de gezamenlijke **indexroot**, ook wanneer een kleinere scope is gekozen. Bijvoorbeeld `frontend/src/client.ts` en `backend/src/client.ts` zijn twee bestanden. De repository op de indexroot gebruikt `.`. Voor codehostlinks wordt het repositoryvoorvoegsel op padcomponentgrenzen verwijderd; een bron in repository `frontend` met pad `frontend/src/client.ts` linkt naar `src/client.ts` in die repository. Geen overeenkomst op uitsluitend de bestandsnaam (rij 48; `code_mapper/scope.py:63-66`).

`topics[].file` is juist relatief aan de map-uitvoermap, zoals de bestaande index (`autodoc/index_loader.py:84-85`). AutoDoc koppelt die aan `DocsitePage.source_path` en gebruikt daarna de definitieve `DocsitePage.slug` voor links. Titelwijzigingen of opgeschoonde Markdown bepalen niet de koppeling (`generator.py:63-84`). Een modeltopic zonder werkelijk gegenereerde pagina levert geen kapotte link op; meld de ontbrekende koppeling.

## Dekking en bronherkomst

### Topicdekking

Voor ieder paar topic/element bewaart AutoDoc een verzameling gedeelde bestanden. Oprollen naar de container en het systeem is de **unie** van directe en onderliggende verzamelingen, niet de som van tellingen. Een topic verschijnt eenmaal per element; gewicht is de grootte van de unie en bepaalt alleen de aflopende volgorde van topiclinks. Gebruik een vaste secundaire volgorde voor gelijke gewichten. Gedeelde containerbestanden geven niet automatisch dekking aan componenten (model R3–R5; rij 12–13, 41).

Alleen gedocumenteerde interne onderdelen zonder implementatiebestanden hebben geen directe dekking. Een container kan wel opgerolde dekking van werkelijk geïmplementeerde kinderen hebben. Zonder dekking verschijnt geen topickaart of regel “Hoort bij”.

### Bronlinks

Een klik opent het volledige bestand bij de codehost op de door `map` vastgelegde commit, met het inclusieve regelbereik als anker. Ondersteun de standaard remotevormen van GitHub, GitLab en Bitbucket; converteer herkende HTTPS- en Git-SSH-remotes naar de passende HTTPS-bestandslink. Geen gok naar hostvormen voor onbekende/self-hosted hosts. Zonder herkenbare remote, bruikbare commit of passend repositorypad blijven bronpad en regels leesbare tekst; publiceer geen link naar een bewegende branch (rij 34, 45, 48).

Bronnen tonen hun soort, zodat een documentatiebron herkenbaar blijft naast code/configuratie. Geen codefragmenten, tokens uit remotes of `vscode://`-links in de site. Vrije modeltekst wordt als tekst weergegeven en voor DSL/JSON/HTML correct ge-escaped, niet als uitvoerbare HTML.

## LikeC4-vertaling en views

### Model en projectie

AutoDoc schrijft `likec4/specification.c4`, `likec4/model.c4` en `likec4/views.c4`. Specificatie: `person`, `softwareSystem`, `container`, `component`, `externalSystem`, herkenbare C4-notatie en een legenda. Alleen gedocumenteerde elementen krijgen `#gedocumenteerd`, `color muted` en een expliciete notatie; gedocumenteerde relaties een stippellijn, aangetroffen relaties een doorgetrokken lijn. Die relatievormen gelden voor de individuele relaties; een gemengde samengevoegde pijl mag niet de status van één onderliggende relatie suggereren. De zichtbare tekststatus blijft per relatie beschikbaar, dus kleur is niet het enige onderscheid (rij 29, 40; [C4-notatie](https://c4model.com/diagrams/notation)).

`LikeC4IdAllocator` maakt slugs uit namen met `a-z0-9_-`, maakt ook een lege, gereserveerde of ongeldig beginnende slug geldig en lost botsingen onder dezelfde ouder op met `-2`, `-3` in gesorteerde neutrale-id-volgorde. Namen en identifiers worden niet ongecontroleerd in DSL geplakt. De echte identiteit staat in `metadata.chunkhound_id`; relaties houden hun neutrale identiteit en individuele bronnen eveneens in metadata. Slugs zijn presentatie, geen duurzaam architectuur-id (rij 26, 38, 40).

Bekende bronlinks worden native `link`-velden. Tekstbronnen blijven in `metadata.bronnen`; topiclinks met dekking in `metadata.topics`. De fork krijgt daarnaast de gestructureerde `chunkhound_*`-gegevens die nodig zijn voor status, individuele bronnen, definitieve topiclinks en focusnavigatie. De serialisatie daarvan is een interne grens tussen schrijver en fork, geen tweede neutraal exportformaat (rij 40–41).

### Views en bediening

| View                        | Inhoud en toegang                                                                                                                                                            |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Systeemcontext `index`      | Eigen systeem, personen en onderbouwde externe systemen; start op `/architecture/` en kleine homekaart.                                                                      |
| Containerview               | Alle containers binnen het systeem en hun relevante directe buren op dit abstractieniveau; bereikbaar bij inzoomen op het systeem.                                           |
| Componentview per container | Alle componenten van die container plus relevante directe buren, op het passende niveau; bereikbaar bij inzoomen op de container.                                            |
| Focus-view per element      | Gekozen element met directe inkomende/uitgaande relaties en hun andere endpoints; ook zonder relaties blijft het gekozen element zichtbaar. Knop “Focus-view” in de details. |
| Topicview                   | De door het topic gedekte elementen met hun directe relaties en buren; geen kaart voor een topic zonder dekking.                                                             |

Views bevatten expliciet gekozen elementen, geen onbegrensde model-wildcards. Focus- en topicviews gebruiken gerichte relatie-includes zoals `include a -> x` en `include x -> b`, niet het eerder gecorrigeerde algemene patroon. Bij projectie op een hoger niveau bewaart LikeC4 alle onderliggende relaties (rij 22, 40).

Volledige views worden niet afgekapt; pan/zoom en focus helpen bij grote modellen. Er zijn geen extra componentgroepen of maximumaantallen. Inzoomen gebruikt `view of` en navigatieknoppen; wisselen van view houdt de URL `/architecture/?view=<viewId>` bij, zodat een gekopieerde URL dezelfde view opent. Een onbekende view-id opent de systeemcontext met een zichtbare melding (rij 33, 36, 40, 45).

Voor samengevoegde pijlen geldt model R7–R9: één verschillende titel blijft die titel; meerdere titels krijgen het bijbehorende `merged_labels`-label via een `with { title }`-override. Een directe relatie krijgt geen voorrang. Ontbreekt een bruikbaar label, dan geldt de vastgelegde deterministische terugval: twee titels met `·`, bij drie of meer de eerste titel met `+N relaties`, passend binnen 60 tekens. Geen `[...]` en geen LLM-aanroep vanuit AutoDoc. De producent blijft verantwoordelijk voor gebundelde/gecachete samenvattingen uitsluitend uit onderliggende titels (rij 23, 27–28, 41).

### Detailvensters

De fork past `ElementDetailsCard.tsx` aan: soort, beschrijving, technologie, status, bronnen, dekkende topics op gewicht en Focus-view. `RelationshipPopover.tsx` toont **iedere** onderliggende relatie met eigen titel, status en bronnen, gesplitst in direct en afgeleid, plus navigatie naar de onderliggende elementen. Ook een pijl met gemengde onderliggende statussen krijgt geen samengevatte status. De architectuurpijl en de topiclinks blijven verschillende dingen (rij 22, 28–29, 40–41).

## Site-integratie en generatie

### Onderdelen

Zie [model §2: ontwerpklassendiagram en modulegrenzen](../models/autodoc-c4-map.md#2-ontwerpklassendiagram) en [model §3: vertaaltabel](../models/autodoc-c4-map.md#3-vertaaltabel). Het pakket `chunkhound/autodoc/architecture/` groepeert het exportmodel, loader, dekking, id-toewijzing, bronlinks, views, DSL-schrijver en sitegegevens. Geen nieuwe database.

`SiteExtras` bundelt de bestaande optionele navigatie, woordenlijst en homepage-inleiding met `architecture: C4Model | None`. `generator.py` maakt de bundel; `write_astro_site` ontvangt die in plaats van de drie losse optionele parameters. Alle aanroepers migreren mee. Verplichte invoer blijft apart en `DocsiteSite` behoudt zijn betekenis als sitemetadata (rij 43; huidige grens `site_writer.py:59-68`).

### Volledige generatie

De volgorde staat in [model §5](../models/autodoc-c4-map.md#5-sequencediagrammen): topics laden, model laden, definitieve pagina's koppelen, dekking oprollen en site schrijven. De bestaande eventuele LLM-topicopschoning blijft los van de kaartvertaling.

Met een bruikbaar model schrijft AutoDoc de DSL, kaartcomponenten, `/architecture/`-pagina en benodigde gegevens. De zijbalk bevat de kaart; de homepagina krijgt een kleine systeemcontext met link naar de volledige kaart. Topicpagina's krijgen via `DocLayout.astro` de regel “Hoort bij” en kleine topicview. Topic-Markdown wordt daarvoor niet aangepast (rij 33, 41, 44).

`src/data/architecture.json` bestaat altijd: met publicatiegegevens of expliciet leeg. Het bevat de koppelingen naar view-id's, definitieve topic-URL's en gedekte elementen die het layout nodig heeft. De bestaande zoekindex krijgt records voor containers, componenten, personen en externe systemen met naam, soort, beschrijving, status en focus-view-URL. Geen relatiezoekrecords; bestaande topicrecords behouden hun contract (rij 37, 41).

De optionele `ArchitectureMap.astro` en `ArchitectureMiniMap.astro` importeren hun TSX-component rechtstreeks met `client:only="react"`. `DocLayout.astro` ontdekt de **Astro-wrappers** via `import.meta.glob`, niet dynamisch te hydrateren React-tags. `ArchitectureMap.tsx` verzorgt de volledige interactieve kaart; `ArchitectureMiniMap.tsx` de kleine kaarten via `LikeC4View`. Zonder model zijn wrappers, TSX-kaartcomponenten en virtuele LikeC4-imports afwezig (rij 41, gecorrigeerd door rij 46; [Astro client-directives](https://docs.astro.build/en/reference/directives-reference/#client-directives)).

`astro.config.mjs` activeert de React-integratie en `LikeC4VitePlugin({ workspace: 'likec4', throwIfInvalid: true })` alleen met `likec4/`. Ook imports van de optionele integratie zijn conditioneel. Bij de afzonderlijke `astro build` berekent de plugin views en lay-out en levert `likec4:react`; AutoDoc start hiervoor geen Node-bouwstap. CSS en fonts van de gebundelde fork worden met de kaart meegeleverd en in de echte site gecontroleerd. Voeg niet zonder noodzaak een tweede `@likec4/diagram`-runtime toe naast het gekozen gebundelde `likec4/react` ([LikeC4 v1.60.0 pluginhandleiding](https://github.com/likec4/likec4/blob/v1.60.0/apps/docs/src/content/docs/tooling/vite-plugin.mdx), [React-bundel](https://github.com/likec4/likec4/blob/v1.60.0/packages/react/tsdown.config.mjs)).

Zonder bruikbaar model schrijft AutoDoc de gewone site, lege kaartgegevens en uitsluitend topiczoekrecords. Volledige hergeneratie verwijdert uitsluitend eerder door AutoDoc gegenereerde kaartuitvoer: DSL, architectuurpagina, optionele kaartcomponenten en meegeleverd kaartarchief. Geen kaartlink, homekaart of “Hoort bij”. Andere bestanden blijven ongemoeid; bestaande beschermingsregels voor topicdirectories blijven gelden (rij 35, 44).

### `--assets-only`

Vernieuw de presentatie, configuratie, kaartcomponenten en bijbehorend forkarchief voor een bestaande kaartsite. Behoud `.c4`-bestanden, `architecture.json` en topicinhoud; lees geen nieuw producentmodel en herbereken geen dekking. Een oudere site zonder kaartgegevens krijgt lege kaartgegevens en geen kaart. De bestaande metadata bepaalt of package/README kunnen worden vernieuwd; behoud het huidige gedrag zonder `site.json` (`site_writer.py:40-56,124-129`; rij 44).

## Distributie en onderhoud van de fork

Basis: LikeC4 **v1.60.0**, upstream-commit `0375d146f8de2eb919033bd3b43b3701194f518b` ([officiële tag](https://api.github.com/repos/likec4/likec4/git/ref/tags/v1.60.0)). Houd de aanpassing beperkt tot de benodigde detailweergave en het bijbehorende metadata-contract; geen eigen renderer of afsplitsing van de architectuurmethodiek.

Bouw de aangepaste diagramcomponenten via de React-bundel in het uiteindelijke `likec4`-package. Dat package biedt zowel `likec4/react` als `likec4/vite-plugin`. Het upstream-monoreporoot is geen vervangende installeerbare dependency. De build moet ook de bijbehorende stijlen verwerken; uitsluitend TSX-bronbestanden kopiëren levert niet het vereiste pakket op ([package](https://github.com/likec4/likec4/blob/v1.60.0/packages/likec4/package.json), [packagebuild](https://github.com/likec4/likec4/blob/v1.60.0/packages/likec4/tsdown.config.mts)).

Check het gebouwde `.tgz`-archief in als AutoDoc-resource onder `chunkhound/autodoc/assets/`, met vastgelegde forkbron/revisie, buildinstructies, herkenbare artifactversie en licentievermeldingen. Het moet in wheel én sdist zitten en via de bestaande resourcebenadering geladen worden (`template_loader.py`, `pyproject.toml:165-175`). AutoDoc kopieert het naar de gegenereerde site; `package.json` gebruikt pakketnaam `likec4` met een lokale `file:`-tarballdependency ([npm package-spec](https://docs.npmjs.com/cli/v12/using-npm/package-spec/); rij 47).

Forkupdates bouwen en vervangen het archief, werken versie/dependency-integriteit samen bij en bewijzen dat een schone site-installatie daadwerkelijk de nieuwe detailweergave gebruikt. Behoud MIT- en toepasselijke bronvermeldingen ([licentie](https://github.com/likec4/likec4/blob/v1.60.0/LICENSE)), waaronder bestaande NVIDIA-vermeldingen in [diagramcode](https://github.com/likec4/likec4/blob/v1.60.0/packages/diagram/src/index.ts). Geen eigen npm-publicatie nodig. Overige runtime-dependencies worden niet automatisch meegebundeld; dit is geen offline-installatiebelofte. De forkbron, nieuwe forkcommit en artifactbytes worden pas tijdens de goedgekeurde productuitvoering gemaakt; er is nu geen forkbuildbewijs.

## Foutgrenzen

| Situatie                                                                              | Vereist resultaat                                                                                                                                              |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Model ontbreekt, JSON is onleesbaar/structureel onbruikbaar, of schemaversie onbekend | Consolewaarschuwing met oorzaak en hersteladvies; gewone site zonder kaart, exitcode 0. Geen strict-instelling.                                                |
| Onbekende id-verwijzing of ontbrekende topicpagina                                    | Betrokken onderdeel/koppeling overslaan en melden. Afhankelijke relaties/views bevatten geen dangling verwijzingen; overige bruikbare inhoud blijft zichtbaar. |
| Model heeft geen relaties                                                             | Teken de aanwezige elementen; geen verzonnen relaties.                                                                                                         |
| Onbekende remote/hostvorm of geen bruikbare commit                                    | Bronpad en regelbereik als tekst; geen gegokte of niet-commitvaste link.                                                                                       |
| Onbekende view-id                                                                     | Systeemcontext met zichtbare melding.                                                                                                                          |
| Eigen ongeldige DSL, falende fork- of Astro-build                                     | Echte fout. Geen verborgen retry die de kaart verwijdert en succes suggereert.                                                                                 |

Verwachte invoerproblemen lopen via de bestaande `log_warning`-route (`generator.py:219-235`). De plugin gebruikt expliciet `throwIfInvalid: true`, omdat upstream standaard alleen rapporteert. Programmerings- en buildfouten worden niet algemeen gevangen en omgezet naar “geen model” (rij 45–46).

## Design patterns

[Model §4](../models/autodoc-c4-map.md#4-design-patterns): **Introduce Parameter Object**, `SiteExtras`, om optionele site-inhoud bij de bestaande writergrens te bundelen. Alternatief **Preserve Whole Object** met uitbreiding van `DocsiteSite` is afgewezen als bredere herstructurering zonder noodzaak voor deze functie (rij 43; [Fowler](https://refactoring.com/catalog/introduceParameterObject.html)). Geen aanvullende patronen.

## Tooling

Versies hieronder zijn de beoogde stack, niet geïnstalleerde C4-dependencies in deze checkout. Manifestranges onderbouwen de combinatie; zij bewijzen geen geslaagde integratie.

| Package/runtime  | Versie en bron                                                                                                                                                                               | Docsdekking voor dit ontwerp                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Astro            | 7.4.2, afzonderlijk goedgekeurde upgrade (rij 19); de C4-uitvoering herhaalt die niet.                                                                                                       | web: https://docs.astro.build/en/reference/directives-reference/                                              |
| Vite             | 8.3.5, upgradebasis uit de designbrief; valt binnen `^8.3.4` van LikeC4 en Astro React.                                                                                                      | web: https://vite.dev/guide/features                                                                          |
| LikeC4-fork      | Basis 1.60.0 en bovenstaande upstream-commit; forkartifact bevat de eigen aanpassing.                                                                                                        | docs-mcp 1.60.0                                                                                               |
| `@astrojs/react` | 7.1.1 uit de officiële [Astro 7.4.2-bron](https://github.com/withastro/astro/blob/astro%407.4.2/packages/integrations/react/package.json). Geen beweerde minimale Astro-peercompatibiliteit. | web: https://raw.githubusercontent.com/withastro/astro/astro%407.4.2/packages/integrations/react/package.json |
| React            | 19.3.0; [release-metadata](https://registry.npmjs.org/react/19.3.0), voldoet aan LikeC4 `^19.3.x`.                                                                                           | web: https://registry.npmjs.org/react/19.3.0                                                                  |
| React DOM        | 19.3.0; [release-metadata](https://registry.npmjs.org/react-dom/19.3.0), zelfde React-lijn.                                                                                                  | web: https://react.dev/reference/react-dom                                                                    |
| Node.js          | Minimaal 22.23.4; CI Node 24, ongewijzigd upgradebesluit rij 19.                                                                                                                             | web: https://raw.githubusercontent.com/withastro/astro/astro%407.4.2/packages/integrations/react/package.json |

Python blijft de bestaande `>=3.10,<3.15`-stack met `uv`; geen nieuwe Python-runtime of database. Bestaande Ruff/mypy/pytest-configuratie blijft leidend (`pyproject.toml:18,199-249`). TS/JS volgt de opgegeven Google-stijl, automatische opmaak via oxfmt en lint via oxlint; uitzonderingen alleen als `// oxlint-disable-next-line <regel> -- <reden>`. Geen repo-brede toolingmigratie. Voor de forkbuild blijven upstream-workspacegereedschap en lockfile uitgangspunt; exacte uitvoeringscommando's komen in het implementatieplan na inspectie van de echte fork.

Grounding: `read`/`grep` voor bestaande paden en symbolen; `mcp__docs_mcp_find_version` en `mcp__docs_mcp_search_docs` voor LikeC4; officiële bronbestanden en documentatie voor ontbrekende packageversies. Geen extra project-MCP of editorintegratie toegevoegd.

## Verificatie en acceptatie

Dit zijn eisen voor de implementatie, **geen reeds geslaagde controles**. Fixtures voor de consument mogen het vastgelegde producentcontract invullen; de uiteindelijke claim `map → AutoDoc` vereist ook echte producentuitvoer zodra die afhankelijkheid beschikbaar is.

| Contract / regel                 | Waarneembaar bewijs                                                                                                                                                                                                                       |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1/R11: niveaus en systeemgrens  | Gebouwde site met één systeem, meerdere repositories, container- en componentviews; geen code-elementen of impliciete repositoryfederatie.                                                                                                |
| R2/R3/R6: onderbouwing en status | Echte details met code/config/doc-bronnen, zichtbaar gedocumenteerde interne onderdelen en relaties; geen topicpijlen of directe dekking voor documentatie-only onderdelen. Producent bepaalt classificatie, consument toont die correct. |
| R4/R5: overlap en oprollen       | Contracttest met containerbestanden en overlappende covers: unieke bestandsunie, één topiclink, correct gewicht en definitieve URL; geen dekking door alleen dezelfde bestandsnaam in een andere repository.                              |
| R7: samengevoegde relaties       | Gebouwde, aangeklikte uitgezoomde pijl met directe én afgeleide relaties, gemengde status en afzonderlijke bronnen; niets verdwijnt door samenvoegen.                                                                                     |
| R8/R9: labels                    | Geleverd samenvattend label en deterministische terugval zichtbaar zonder `[...]`; maximaal 60 tekens voor samenvattende labels. Bundeling/cache van de LLM is een producentverplichting, niet een AutoDoc-test.                          |
| R10: neutrale identiteit         | Hernoemde en botsende/non-ASCII namen leveren geldige DSL en behoud van neutrale metadata; geen claim dat LikeC4-slugs blijvende ids zijn. Identiteitsberekening zelf ligt bij `map`.                                                     |
| Paden en bronlinks               | GitHub/GitLab/Bitbucket commitvaste links, regelbereiken, geneste repositoryvoorvoegsels en leesbare tekst zonder remote.                                                                                                                 |
| Alle kaartpaden                  | Browserproef: home → volledige kaart → niveaus → elementdetails/Focus-view → topic → “Hoort bij”/minikaart → kaart. Zoekresultaat en gekopieerde view-URL openen de juiste focus; onbekende view toont melding/context.                   |
| Volledige generatie              | Echte generatie met model, daarna zonder/ongeldig model: waarschuwing, exitcode 0, gewone site bouwt en oude gegenereerde kaartuitvoer verdwijnt zonder andere bestanden te verwijderen.                                                  |
| `--assets-only`                  | Kaartsite behouden: topicinhoud, `.c4`, `architecture.json` en dekking blijven gelijk; vernieuwde UI bouwt. Oudere site zonder model bouwt eveneens.                                                                                      |
| Tekstgrenzen                     | Consumergerichte contracttests en echte DSL-build met quotes, backslashes, regeleinden, Unicode en botsende identifiers; geen geïnjecteerde DSL/HTML.                                                                                     |
| Distributie                      | Schone installatie van het werkelijk gebouwde forkarchief vanuit een gegenereerde site én beschikbaarheid vanuit wheel/sdist; aangepaste detailvensters en CSS zichtbaar, niet per ongeluk upstream-code.                                 |
| Foutgrenzen                      | Invoerproblemen volgens de fouttabel; ongeldige eigen DSL laat de build daadwerkelijk falen, niet stil zonder kaart doorgaan.                                                                                                             |

Voer bij implementatie de relevante AutoDoc-tests uit, `uv run mypy chunkhound` tijdens review en de verplichte smoke-suite `uv run pytest tests/test_smoke.py -v -n auto` vóór commits. Een echte Astro/Vite/fork-build met en zonder model en een browserproef blijven verplicht; alleen tests zijn geen integratiebewijs. Permanente tests beschermen consumentgedrag en lastige grenzen, niet gekopieerde templates, interne forwarding of exacte formuleringen. Bestaande tests voor incidentele tekst/implementatiedetails worden bij wijziging verwijderd, niet opnieuw vastgepind. Werk de gebruikersdocumentatie en forkonderhoudsinstructies bij met de daadwerkelijke uitvoering.

## Sources en bewijsgrenzen

- Domein, UX en grenzen: besluitenlog rij 11–48; methodiek [C4-abstracties](https://c4model.com/abstractions), [notatie](https://c4model.com/diagrams/notation), [grote modellen](https://c4model.com/faq#does-the-c4-model-scale). De tool is geen bron voor nieuwe domeinclaims.
- Bestaande consumentgrenzen: `chunkhound/autodoc/models.py:15-50`, `index_loader.py:76-105`, `generator.py:44-84,209-290`, `site_writer.py:40-112,124-129`; resourceverpakking `pyproject.toml:165-175`, `template_loader.py`; gezamenlijke bestandspaden `code_mapper/scope.py:19,63-66`.
- LikeC4 API's: docs-mcp-zoekresultaten voor 1.60.0, plus de hierboven geopende versiegebonden officiële package-, build- en plugindocumentatie. `layoutLikeC4Model` bestaat: JSON plus Builder is een afgewezen alternatief, niet technisch onmogelijk (correctie rij 40). De gekozen DSL/pluginroute blijft staan.
- **Ontbrekende bronnen:** deze worktree heeft geen eigen ChunkHound-index of gemounte ChunkHound-MCP; `find` mislukte met een onbeschikbaar zoekmodel (404), dus exact `grep`/`read` als fallback. Geen index gestart of uit een andere worktree geleend. Docs-mcp biedt voor Astro alleen 4.16.19, niet major 7; React, React DOM, Vite en `@astrojs/react` ontbreken. Daarvoor officiële web-/releasebronnen gebruikt; geen scrape gestart.
- **Niet uitgevoerd:** C4-productcode, dependency-installatie, forkcreatie/-build, tarballinstallatie, Astro-integratiebuild en browserproef. Compatibele manifestranges en bronvoorbeelden vervangen die controles niet. Deze specificatie mag na review naar planning, niet rechtstreeks naar implementatie.
