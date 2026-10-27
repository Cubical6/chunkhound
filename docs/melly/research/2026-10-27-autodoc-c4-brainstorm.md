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

## Hervatpunt

Het samengestelde domeinmodel is voorgelegd, maar nog niet afzonderlijk als geheel goedgekeurd. Er is nog geen goedgekeurde C4-specificatie of implementatieplan. Hervat de Superpowers-brainstorm bij de eerste onvoltooide gate en stel reeds besloten individuele keuzes niet opnieuw ter discussie. Nieuwe ontwerpkeuzes horen in de nieuwe design-worktree; de Astro/Vite-upgrade blijft in de oorspronkelijke worktree.
