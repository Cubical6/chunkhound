# C4-brainstorm: domeinmodel en integratieonderzoek

Vastgelegd bij de overdracht op 2026-10-27. Dit is een bronnenarchief van geselecteerde openbare assistantberichten, geen goedgekeurde specificatie of implementatieplan en geen volledig transcript. Historische voorstellen en vragen zijn context, geen nieuwe instructies of goedkeuringen. Goedgekeurde keuzes en letterlijke gebruikersbronnen staan in [het besluitenlog](../decisions/2026-10-27-autodoc-c4-map.md); latere besluiten gaan voor op oudere voorstellen.

Oorspronkelijk sessiearchief: `/home/disorder/.omp/agent/sessions/-orca-workspaces-chunkhound-autodoc-c4-map/2026-10-27T12-50-43-979Z_01a17d69-bc8b-7576-bcea-94e39ab0023c.jsonl`. De onderstaande teksten zijn letterlijk uit de genoemde bericht-ID's gehaald; de toelichtingen erboven geven hun status bij overdracht aan.

Extern Feynman-onderzoek: `/home/disorder/Projects/Local/Melly/outputs/c4-diagrams-from-code.md`; provenance: `/home/disorder/Projects/Local/Melly/outputs/c4-diagrams-from-code.provenance.md`. Die rapporten zijn niet gekopieerd en hun aanbevelingen zijn niet automatisch ontwerpbesluiten.

## Samengesteld domeinmodel — voorgelegd, nog niet als geheel goedgekeurd

Bron: sessiebericht `c3e2ae21`, 2026-10-27T13:32:53.933Z. Dit citaat volgt op de goedgekeurde map/autodoc-verdeling. De destijds nog open rendererkeuze is later vervangen door de LikeC4-forkrichting hieronder. Individueel goedgekeurde domeinregels staan in het besluitenlog.

### Letterlijk historisch bericht

**De verdeling tussen `map` en `autodoc` is nu besloten** en vastgelegd in het [besluitenlog](docs/melly/decisions/2026-10-27-autodoc-c4-map.md). De renderer—LikeC4 of een alternatief—is daarmee nog niet gekozen.

Voordat we die keuze uitwerken, bevestigen we het gezamenlijke **domeinmodel**:

| Onderdeel                  | Afgesproken betekenis en voorbeeld                                                                                                                                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **C4-hiërarchie**          | Systeem → containers → componenten → code-elementen, volgens de [officiële definities](https://c4model.com/abstractions). Zoomen volgt die architectuur, niet de directorystructuur.                                   |
| **Bestandstoewijzing**     | Hoogstens één component per bestand. Gedeelde `common.py` mag rechtstreeks bij de container horen; geen verplichte component “Helpers”.                                                                                |
| **Topics en elementen**    | Many-to-many via geciteerde bestanden. Twee unieke gedeelde bestanden geven gewicht 2; herhaalde citaties naar hetzelfde bestand tellen eenmaal. Gewicht ordent uitsluitend de topiclijst.                             |
| **Overerving van dekking** | Dekking rolt op van component naar container naar systeem. Een topic dat twee componenten binnen dezelfde container dekt, verschijnt eenmaal bij die container.                                                        |
| **Architectuurrelaties**   | Gerichte afhankelijkheden of gegevensstromen met onderbouwing uit code, configuratie of expliciete projectdocumentatie. De Stripe-relatie uit alleen een README mag worden opgenomen, herkenbaar als _gedocumenteerd_. |
| **Documentatienavigatie**  | Topickoppelingen zijn geen C4-pijlen. Ze verbinden een architectuurelement met de bijbehorende uitleg.                                                                                                                 |

**Nog open voor het ontwerp:** renderer, te genereren diagramniveaus, exact outputformaat en gedrag bij ontbrekende of onvolledige modelgegevens. Verouderde projectdocumentatie blijft een bekend risico.

Keur je dit gezamenlijke domeinmodel goed als basis voor het verdere ontwerp?

## Docs-mcp-grounding — destijds gerapporteerde dekking

Bron: sessiebericht `df918ea8`, 2026-10-27T13:19:24.233Z. Dit is de historische controle uit de oorspronkelijke sessie, geen nieuwe statuscontrole. De Astro-v4-dekking onderbouwt geen Astro-7-API. Controleer actuele pakket- en major-dekking opnieuw waar die nodig is voor nieuwe ontwerpclaims.

### Letterlijk historisch bericht

**Alle vier bronnen zijn nu doorzoekbaar in docs-mcp.** Gecontroleerd met `find_version`, inhoudelijke `search_docs`-vragen en de opgeslagen pagina’s.

| Bron                        | Opgeslagen pagina’s | Verificatie                                                 |
| --------------------------- | ------------------: | ----------------------------------------------------------- |
| `c4model` — ongeversioneerd |                  25 | Officiële definities, zoomniveaus en notatieregels          |
| `likec4` — label 1.60.0     |                  83 | Vite-plugin, Astro-integratie en web components             |
| `mermaid` — label 12.2.0    |                 400 | C4-beperkingen, flowchart-links en beveiligingsinstellingen |
| `astro` — v4-archief        |                 315 | Vite-configuratie en React-integratie                       |

**Beperkingen:**

- Mermaid bereikte de ingestelde paginalimiet. De voor ons relevante pagina’s zijn gevonden, maar volledige dekking is niet vastgesteld.
- LikeC4 en Mermaid zijn gescrapet van hun actuele documentatiesites. De versielabels maken hiervan geen vastgezette release-snapshots. Mermaid 12-documentatie bewijst dus niet automatisch compatibiliteit met de huidige template-afhankelijkheid `^10.9.0`.
- De eerder genoemde scrape-aantallen waren verwerkte pagina’s; de tabel toont daadwerkelijk opgeslagen pagina’s.

We kunnen de **methodiek voortaan rechtstreeks aan [c4model.com](https://c4model.com/abstractions)** toetsen, los van de mogelijkheden van een renderer. De openstaande domeinvraag over gedeelde code blijft ongewijzigd.

## Onderzoek van de drie koppelingen — historisch voorstel

Bron: sessiebericht `6b3ef4a9`, 2026-10-27T13:50:29.794Z. De modelvertaling, Astro-inbouw en topic-/bronverwijzingen zijn onderzocht, niet end-to-end beproefd. De aanbevolen losse webcomponent was niet goedgekeurd als eindarchitectuur en is ingehaald door de gekozen fork-/integratierichting. De Astro-4/Vite-5-beperking geldt niet als blijvende ontwerpbeperking.

### Letterlijk historisch bericht

**Mijn voorstel: laat AutoDoc het neutrale C4-model vertalen naar LikeC4 en vooraf een webcomponent genereren. Die komt in dezelfde documentatiesite, met topiclinks en bronherkomst als afzonderlijke navigatie.**

De drie koppelingen zijn op code- en documentatieniveau uitgezocht. De daadwerkelijke build en browserwerking zijn nog niet beproefd.

## 1. Van `map` naar LikeC4: vertalen, niet opnieuw onderzoeken

`map` levert naast de topics het renderer-onafhankelijke architectuurmodel:

- elementen met hun C4-type en bovenliggend element;
- architectuurrelaties met hun onderbouwing;
- implementatiebestanden per element;
- geciteerde bestanden en bronbereiken per topic.

`autodoc` vertaalt dat **deterministisch** naar LikeC4-modelbestanden en views. Hiervoor is geen tweede LLM-interpretatie nodig.

Belangrijk: **LikeC4 dwingt zelf geen C4-methodiek af.** Onze modelregels moeten dus bewaken dat bijvoorbeeld een directory niet zomaar een component wordt. De views tonen vervolgens de passende abstractieniveaus. LikeC4 ondersteunt hiervoor scoped views: een view van een element kan de standaardbestemming worden wanneer je op dat element inzoomt. [Bron: LikeC4 views](https://likec4.dev/dsl/views/)

We houden daarbij drie soorten verbindingen uit elkaar:

| Verbinding          | Betekenis                                                                |
| ------------------- | ------------------------------------------------------------------------ |
| Architectuurrelatie | Bijvoorbeeld: API gebruikt database; dit is een C4-pijl.                 |
| C4-navigatie        | Van een systeem naar zijn containerweergave, of verder naar componenten. |
| Documentatielink    | Naar een topic of onderbouwing; geen C4-pijl.                            |

## 2. LikeC4 in Astro: een vooraf gegenereerde webcomponent

De huidige AutoDoc-template gebruikt **Astro 4**. LikeC4 **1.60.0** gebruikt zelf **Vite 8**, terwijl Astro 4 op **Vite 5** zit. Daarom raad ik af de huidige LikeC4 Vite-plugin rechtstreeks in deze template te plaatsen.

De voorkeursroute is:

1. AutoDoc schrijft de LikeC4-modelbestanden.
2. Een buildstap voert `likec4 codegen webcomponent` uit.
3. Astro publiceert de gegenereerde bundle als statisch bestand.
4. De architectuurpagina gebruikt bijvoorbeeld `<likec4-view view-id="context">`.

Dat is een officieel ondersteunde exportvorm. De versiegebonden broncode bevat ook de diagram-CSS en de toepassing daarvan binnen Shadow DOM; we hoeven dus niet op voorhand een eigen stylinglaag te bouwen. [Webcomponent-documentatie](https://likec4.dev/tooling/code-generation/webcomponent/) · [Broncode 1.60.0](https://cdn.jsdelivr.net/npm/likec4@1.60.0/react/index.mjs)

**Waarom deze route:** de LikeC4-build staat los van Astro’s Vite-build. Er is na publicatie geen aparte LikeC4-server nodig en we hoeven niet meteen Astro te upgraden of een Astro-React-integratie toe te voegen.

Wel vereist deze LikeC4-versie **Node ≥22.22.3**. React en React DOM moeten vooraf expliciet worden vastgelegd: de CLI probeert ze anders zelf te installeren. [Pakketvereisten](https://registry.npmjs.org/likec4/1.60.0) · [CLI-broncode](https://cdn.jsdelivr.net/npm/likec4@1.60.0/dist/cli/index.mjs)

## 3. Topics en onderbouwing koppelen

### Eerst topicidentiteit, daarna de definitieve URL

De uiteindelijke topic-URL ontstaat nu pas in AutoDoc, uit volgnummer en titel (`chunkhound/autodoc/generator.py:74`). Ook de oorspronkelijke topicbestandsnaam bevat een volgnummer en titelafgeleide (`chunkhound/code_mapper/render.py:117-125`). **Geen van beide is dus vanzelf een stabiele identiteit over verschillende runs.**

Daarom moet het model naar topics binnen dezelfde export verwijzen, waarna AutoDoc die verwijzingen omzet naar de werkelijk gegenereerde pagina-URL’s. We moeten geen tweede implementatie van de slugregels maken.

De voorgestelde gebruikersinteractie:

- **Kaart → topic:** documentatielinks in de elementdetails, geordend volgens het afgesproken aantal unieke gedeelde geciteerde bestanden.
- **Topic → kaart:** “Toon in architectuurkaart”, naar de bijbehorende view.
- **Element of relatie → onderbouwing:** een link naar een gegenereerde onderbouwingsectie met bestand, regels en bronsoort.

LikeC4 ondersteunt meerdere links en metadata op elementen én relaties. Daarvoor hoeven we niet meteen een eigen detailsysteem te bouwen. [Elementen](https://likec4.dev/dsl/model/) · [Relaties](https://likec4.dev/dsl/relationships/)

### Broninformatie vóór de Markdown-export bewaren

Hier zit een concrete noodzakelijke wijziging: de bestaande Sources-footer toont maximaal **drie regelbereiken per bestand**, gevolgd door `+N more` (`citation_manager.py:385-390`). AutoDoc kan de ontbrekende bereiken niet terughalen.

De volledige brongegevens moeten daarom rechtstreeks vanuit de onderzoeksmetadata in het gestructureerde exportbestand terechtkomen. Bestand en regelbereiken zijn daar al beschikbaar (`code_mapper/public_utils.py:50-73`).

> **Correctie (onderzoek open punten, zie hieronder):** deze bewering klopt niet. `merge_sources_metadata` leest `metadata.sources`, maar geen enkele producent vult dat veld: de overview zet het leeg (`chunkhound/code_mapper/service.py:263-272`) en het deep-research-resultaat heeft geen `sources`-sleutel (`chunkhound/services/research/v1/pluggable_research_service.py:490-511`).
Ook moet onderbouwing bij inzoomen en uitzoomen behouden blijven: als één hoger-niveaupijl meerdere onderliggende relaties samenvat, mag niet slechts één willekeurige bron overblijven. Gedocumenteerde relaties blijven herkenbaar als **gedocumenteerd**, niet als aangetroffen aanroep.

## Wat nog een uitvoerbare proef vereist

De voorkeursroute is onderbouwd, maar nog geen bewezen integratie. Een kleine wegwerpproef moet aantonen dat:

- de gegenereerde bundle in Astro 4 bouwt en correct wordt gestyled;
- C4-drill-down en terugnavigatie werken;
- topic- en onderbouwingslinks vanuit de details bruikbaar zijn;
- navigatie ook onder een publicatiepad zoals `/chunkhound/` werkt.

**Geen productcode of dependencies gewijzigd.** Het integratieonderzoek is vastgelegd in het besluitenlog; de webcomponentroute is nog een voorstel, geen definitief goedgekeurde implementatiekeuze.

## Latere richting — eigen LikeC4-fork en geïntegreerde componenten

Bron: sessiebericht `6feb2aba`, 2026-10-27T13:53:15.093Z. De gebruikersbron en het besluit staan in het besluitenlog. De latere Astro/Vite-upgrade is afzonderlijk goedgekeurd en uitgevoerd in autodoc-c4-map; de toekomstige LikeC4-integratie is daarmee nog niet geïmplementeerd.

### Letterlijk historisch bericht

**Dan ontwerpen we voor directe integratie van een eigen LikeC4-fork, niet rond de beperkingen van de huidige Astro/Vite-versies.** Vastgelegd in het [besluitenlog](docs/melly/decisions/2026-10-27-autodoc-c4-map.md).

De richting wordt:

- **Astro en Vite later upgraden**, met onderling passende versies.
- **LikeC4 forken** en de benodigde componenten integreren in onze ChunkHound-fork.
- **De losse webcomponent niet als eindarchitectuur vastleggen.** Die aanbeveling was vooral bedoeld om de huidige versieverschillen te omzeilen.
- **De goedgekeurde scheiding behouden:** `map` onderzoekt en produceert het renderer-onafhankelijke C4-model; `autodoc` verzorgt presentatie, navigatie, topiclinks en bronherkomst.

Nog uit te werken: welke model-, layout-, viewer- en navigatieonderdelen we hergebruiken, waar onze eigen documentatie-interface aansluit en hoe we wijzigingen uit upstream LikeC4 blijven overnemen.

**Efficiëntie blijft een expliciet ontwerp- en meetdoel:** directe integratie geeft ons controle, maar bewijst op zichzelf nog niets over bundlegrootte, laadtijd of layoutkosten.

Nu alleen de ontwerpkeuze vastgelegd; geen upgrades uitgevoerd of LikeC4-fork aangemaakt.

## Onderzoek open punten domeinmodel

Uitgevoerd na de domeinbesluiten in rijen 21–25 van het besluitenlog. Alleen lezen; geen productcode gewijzigd. LikeC4-bronnen op tag `v1.60.0`.

### Stabiele identiteit

- Topicnamen zijn LLM-tekst met een lopend volgnummer (`chunkhound/code_mapper/render.py:82-131`, `chunkhound/code_mapper/pipeline.py:279-319`); AutoDoc nummert positioneel (`chunkhound/autodoc/markdown_utils.py:164`).
- `chunks.id` en `files.id` zijn reeksnummers en veranderen bij herindexering (`chunkhound/providers/database/duckdb/schema_constants.py`, `chunkhound/services/indexing_coordinator.py:1119-1163`); `generate_chunk_id` hasht inhoud (`chunkhound/utils/chunk_hashing.py:12-50`).
- LikeC4: element-id = FQN uit de DSL-naam (`packages/language-server/src/model/fqn-index.ts`); relatie-id = hash van document, positioneel AST-pad en eindpunten (`packages/language-server/src/model/parser/ModelParser.ts`, `parseRelation`). Relaties met een onoplosbaar eindpunt vallen stil weg (`buildModel.ts`). DSL-namen: alleen letters, cijfers, `-`, `_`, niet beginnend met een cijfer.
- Feynman-rapport §6: canonieke ID's uit een deterministische inventaris (`/home/disorder/Projects/Local/Melly/outputs/c4-diagrams-from-code.md`).

### Rechtstreekse relatie naast samengevoegde pijl

- `prefer = only(directRelsList)`: bestaat er precies één rechtstreekse relatie X→Y, dan overschrijven haar titel en technologie het samengevoegde label ([`element-view/utils.ts`](https://github.com/likec4/likec4/blob/v1.60.0/packages/core/src/compute-view/element-view/utils.ts) r. 40, 114-115; [`merge-props-from-relationships.ts`](https://github.com/likec4/likec4/blob/v1.60.0/packages/core/src/compute-view/utils/merge-props-from-relationships.ts)).
- Een view-override `include X -> Y with { title ... }` wint altijd (`applyCustomRelationProperties.ts`).
- Structurizr maakt geen afgeleide relatie als er al een relatie tussen de ouders bestaat (https://docs.structurizr.com/dsl/implied-relationships).

### Status bij gemengde bronnen

- Geen precedent voor één gemengd label: Structurizr en LikeC4 laten bewijssoort aan de modelleur (properties/perspectives resp. metadata/links); het Feynman-rapport hangt bewijs per bron aan elementen en relaties.
- ChunkHound kent per chunk twee kenmerken: de taal van het bestand (`Language`, bijv. `MARKDOWN`, `YAML`, `TOML`, `TEXT`; `chunkhound/core/types/common.py:154-207`) en het chunktype (`ChunkType`). `ChunkType.is_code` (`common.py:102-134`) en `ChunkType.is_documentation` (`common.py:136-150`) splitsen chunktypes; documentatie omvat Markdown-koppen en -alinea's, maar ook commentaar en docstrings in code.
- Correctie op een eerdere [INFERENCE]: dat commentaar en docstrings onder documentatie vallen, past bij de betekenis van _gedocumenteerd_ (een bewering in proza, geen aangetroffen aanroep). Geen van beide kenmerken volstaat echter alleen: tekstbestanden worden als `PARAGRAPH` opgeslagen (`chunkhound/parsers/chunk_splitter.py:175-227`) en een `Dockerfile` krijgt `Language.TEXT` (`common.py:224-228`), zodat configuratie als documentatie zou tellen. De classificatieregel is een ontwerpkeuze. [INFERENCE]
- ChunkHound heeft geen aanroepgraaf; bronnen zijn chunks die deep research via semantisch en regex-zoeken vindt en citeert. _Aangetroffen_ betekent daarom "onderbouwd door een geciteerde code- of configuratiechunk", niet "geverifieerde aanroep" zoals bij CodeBoarding (`is_static`). [INFERENCE] op basis van het ontbreken van call-graph-code in `chunkhound/`.

### Meerdere services en repositories

- Eén database hoort bij precies één geïndexeerde root; openen onder een andere root wordt geweigerd (`chunkhound/providers/database/duckdb_provider.py:406-445`).
- Die root mag een werkmap met meerdere geneste git-repositories zijn: ChunkHound detecteert repository-roots en past per repository de eigen `.gitignore` toe (`chunkhound/utils/ignore_engine.py:219-353, 437-459`).
- `map` werkt op één root plus een scope binnen die root (`chunkhound/code_mapper/scope.py:10-66`). Repositories in afzonderlijke databases kunnen dus niet samen in één `map`-run. [INFERENCE]

### Samenvoegen met de CodeBoarding-engine

- Licentie MIT (`.scratch/codeboarding/LICENSE`), dus overnemen mag met behoud van de copyrightvermelding.
- `static_analyzer/` is ±16.000 regels Python en hangt af van `infra/` (±6.000 regels): ignore-regels, padhulpjes, de downloader van language servers (`infra.tool_registry`, `infra.install`), cluster-id's en telemetrie.
- CodeBoarding vereist Python `>=3.12,<3.13` en pint `tree-sitter==0.25.2` plus losse grammatica's (`.scratch/codeboarding/pyproject.toml:11, 56-57`); ChunkHound ondersteunt Python `>=3.10,<3.15` met `tree-sitter>=0.25.0` en `tree-sitter-language-pack` (`pyproject.toml:18, 48-51`).
- Runtime: per taal een language server, Node.js voor Python/TS/JS/PHP, een JDK voor Java, ±360 MB voor Kotlin (`.scratch/codeboarding/README.md:156, 250-252`).
- Mogelijke vormen: (1) `static_analyzer` overnemen in ChunkHound, (2) CodeBoarding als optionele externe stap en zijn `analysis.json` inlezen, (3) een lichte eigen controle op ChunkHounds eigen tree-sitter-chunks (imports, identifiers, URL's). Keuze hoort bij de benaderingen (stap 4), niet bij het domeinmodel. [INFERENCE]
- `map` bouwt vandaag geen structuur maar onderwerpen: HyDE-planning vanuit bestandslijst plus codesteekproef levert twee genummerde lijsten _points of interest_ (architectural, operational; `chunkhound/code_mapper/pipeline.py:132-423`), daarna per punt deep research (`chunkhound/code_mapper/service.py:249-479`), dekking via geciteerde versus niet-geciteerde bestanden (`chunkhound/code_mapper/coverage.py:48-75`) en topic-Markdown (`chunkhound/code_mapper/writer.py:26-95`). Juist de componentindeling en code-relaties ontbreken; dat is wat CodeBoarding levert. CodeBoarding vult daarmee het componentniveau aan, ChunkHound houdt context, containers, documentatie en topics. [INFERENCE]

### Volledige bronnen

- Volledige regelbereiken worden nergens op schijf bewaard. Topicbestanden bevatten alleen de ingekorte Sources-footer (`chunkhound/services/research/shared/citation_manager.py:385-391`); `map` schrijft geen JSON (`chunkhound/code_mapper/writer.py:54-95`). AutoDoc leest alleen die footer (`chunkhound/autodoc/references.py:66`).

### Zichtbare vorm van _gedocumenteerd_

- LikeC4 kent geen ingebouwde status hiervoor. Elementtags zijn standaard onzichtbaar (`enableElementTags` standaard uit, `packages/diagram/src/context/DiagramFeatures.tsx`); relatietags worden niet getekend. [INFERENCE]
- Elementen: view-stijlregel op tag met `border`, `opacity`, `color` (`applyViewRuleStyles.ts`). Relaties: alleen `line`/`color` via `include … with { }` of een relatiesoort in de specificatie.
- De legenda (`NotationPanel`) toont alleen elementen en staat standaard uit (`enableNotations`).

## Vergelijking: CodeBoarding

Onderzocht op verzoek van de gebruiker vóór de keuze over een rechtstreekse relatie naast een samengevoegde pijl. Bron: https://github.com/CodeBoarding/CodeBoarding, commit `13adc4a0` (2026-10-27), MIT. Paden hieronder zijn relatief aan die repository; alleen gelezen, niet uitgevoerd.

### Elementen en identiteit

- Geen C4: één boom van componenten (root → component → bestanden), zonder personen, externe systemen of containerniveau. Diepte volgt uit omvanglimieten, niet uit abstractieniveaus (`static_analyzer/clustering/names/draft.py:40-80`, `diagram_analysis/run_context.py:7-11`).
- De indeling is deterministisch: regels op mappadprefixen plus een woordstemming, bewaard als `tree_spec` in `analysis.json` (`docs/design/name-tree.md:33-41`). Een component-id is het regel-id (`diagram_analysis/scope_assembly.py:50-55`); het taalmodel kiest alleen naam, beschrijving en sleutelentiteiten, en bij een naamconflict valt de naam terug op de regelnaam (`scope_assembly.py:127-137`).
- Volgende runs spelen de bewaarde regels opnieuw af; gemeten verplaatsing van ongewijzigde bestanden: 0,00% over 27 repositories (`name-tree.md:270-272`). Zonder bewaarde `tree_spec` geen incrementele run (`name-tree.md:298-300`).
- Een bestand kan in het datamodel bij meerdere componenten horen (`diagram_analysis/file_index.py:84, 102-104`); bij meerdere eigenaren is de toewijzing leeg (`agents/component_ownership.py:40`).
- Verwijzingen die het taalmodel noemt maar die niet in de statische analyse bestaan, worden verwijderd (`diagram_analysis/reference_resolver.py:47-52, 73-114`).

### Relaties en samenvoegen

- Relaties komen uit de statische aanroepgraaf, per componentpaar gegroepeerd (`diagram_analysis/cluster_relations.py:50-87`). Het taalmodel geeft ze een label op basis van de onderliggende aanroepen; paren zonder label krijgen `"calls"` (`agents/prompts/shared.py:45`, `infra/constants.py:20`).
- Een relatie die alleen het taalmodel voorstelt, blijft alleen bestaan met tekstueel bewijs én herleidbare aanroepen (`diagram_analysis/scope_assembly.py:198-205`).
- Elke relatie bewaart haar onderliggende aanroepen met bestand en regel (`key_edges`, `all_edges`) en een vlag `is_static` (`agents/agent_responses.py:163-270`).
- Labels per niveau: het taalmodel labelt relaties binnen elke scope. Elke bladrelatie erft het label van de diepste door het taalmodel gelabelde relatie die haar omvat (`diagram_analysis/cluster_relations.py:123-135, 181-205`).
- Uitzoomen: elke bladrelatie wordt naar de dichtstbijzijnde zichtbare voorouder getild en per paar samengevoegd (`output_generators/rendering.py:23-60`). Het label van de eerste bladrelatie in sorteervolgorde `(src_id, dst_id, label)` blijft staan; de andere labels vallen weg (`agents/relation_edges.py:11-25`; vastgelegd in `tests/output_generators/test_rendering.py:85-105`). Er is geen samenvattend label en geen onderscheid tussen rechtstreeks en afgeleid.
- Documentatie is geen bron voor elementen of relaties; er bestaat geen status vergelijkbaar met _gedocumenteerd_.
- Weergave: Mermaid (Markdown/MDX/Sphinx) of Cytoscape (HTML). Pijlen tonen alleen het label; doorklikken naar onderliggende aanroepen bestaat niet, wel per component naar code met regelbereik (`output_generators/html.py:25-113`, `output_generators/markdown.py:20-34, 92-116`).

### Ter vergelijking: C4 en Structurizr

- C4 schrijft geen samenvoegalgoritme voor; de methode is notatie-onafhankelijk. Wel eist zij dat elke lijn een label heeft dat past bij richting en bedoeling van de relatie, zo specifiek mogelijk, liefst niet alleen "Uses" (https://c4model.com/diagrams/notation, https://c4model.com/diagrams/checklist).
- Structurizr kopieert bij een afgeleide relatie omschrijving en technologie van de eerste onderliggende relatie (`AbstractImpliedRelationshipsStrategy.createImpliedRelationship`). Bestaat er al een relatie tussen de ouders, dan wordt er geen afgeleide gemaakt (`CreateImpliedRelationshipsUnlessAnyRelationshipExistsStrategy`; https://github.com/structurizr/java).

## Hervatpunt

Het domeinmodel is nog niet als geheel goedgekeurd. Rij 26–29 beslissen identiteit, pijllabels en status bij gemengde bronnen; rij 31 beslist één softwaresysteem per `map`-run. Hoe `map` de structuur bouwt (componentindeling, code-relaties, eventueel CodeBoarding-engine) loopt in de aparte designsessie `map-structuur-design` (rij 30); de opslag van volledige bronnen hoort daar ook bij. De domeinmodelpoort is voorgelegd; open voor de ontwerpfase: de zichtbare vorm van _gedocumenteerd_; "zonder dossier" als open punt in de spec. Er is nog geen goedgekeurde C4-specificatie of implementatieplan. Stel reeds besloten keuzes niet opnieuw ter discussie; de Astro/Vite-upgrade blijft in de worktree `autodoc-c4-map`.
