# Design brief: autodoc-c4-design

## Request

Letterlijke overdrachtsvraag van de gebruiker:

> Staat de oorspronkelijek brainstorm vastgelegd? Ik wil daarmee verder in een nieuwe design sessie volgens superpowers brainstorm, aangezien deze sessie nu bezig is met de upgrade.

Oorspronkelijk doel, gereconstrueerd uit de eerste brief en dus geen letterlijk citaat: breid de ChunkHound-fork uit met een C4-diagrammenkaart in de door AutoDoc gegenereerde documentatie. De gebruiker verwees naar <https://likec4.dev/>. Dit is een vervolg van die brainstorm, geen nieuwe blanco ontwerpopdracht.

## Handoff

### Next command

`read skill://brainstorming and run it in this design worktree`

### Decisions

- Lees eerst `docs/melly/decisions/2026-10-27-autodoc-c4-map.md`. Deze kopie is bij overdracht ongewijzigd overgenomen uit de upgrade-worktree, inclusief broncitaten, `[INFERENCE]`-markeringen en het besluit over sessiescheiding. Nieuwe C4-ontwerpbesluiten worden vanaf nu in deze worktree bijgehouden; er is geen automatische synchronisatie tussen de kopieën.
- Lees `docs/melly/research/2026-10-27-autodoc-c4-brainstorm.md` voor het voorgelegde domeinmodel, de historische docs-mcp-controle, het onderzoek naar de drie koppelingen en de latere integratierichting. De geselecteerde oorspronkelijke assistantberichten hebben hun bericht-ID en tijdstip behouden. Dit bronnenarchief is geen goedgekeurde specificatie; latere besluiten in het log gaan voor op oudere voorstellen.
- Er is nog geen goedgekeurd volledig C4-domeinmodel, geen C4-specificatie en geen C4-implementatieplan. Het besluitenlog bevat wel goedgekeurde individuele keuzes. De overdrachtsvraag keurt ontbrekende ontwerpstukken niet alsnog goed.

### State

#### Werkruimte en scheiding van de upgrade

- Nieuwe design-worktree: `/home/disorder/orca/workspaces/chunkhound/autodoc-c4-design`, branch `Cubical6/autodoc-c4-design`. Orca-ID: `f5d425a1-12c8-42a9-83b5-fa984c531cc2::/home/disorder/orca/workspaces/chunkhound/autodoc-c4-design`. Onafhankelijke worktree vanaf `refs/remotes/origin/main` op `829ec586099545212bf26b09607cbecf826d444c`. Bron: Orca worktree-create-resultaat bij deze overdracht.
- Upgrade-worktree en oorspronkelijke sessie blijven apart: `/home/disorder/orca/workspaces/chunkhound/autodoc-c4-map`, branch `Cubical6/autodoc-c4-map`. Daar zijn de AutoDoc-template en projectwebsite gemigreerd naar Astro 7.4.2/Vite 8.3.5 en eerder als upgrade geverifieerd. De wijzigingen zijn bij overdracht niet gecommit en zijn niet naar deze nieuwe worktree gekopieerd. Bron: upgradebesluiten in het log, de huidige packagebestanden daar en sessiebericht `47af1539` in het oorspronkelijke archief.
- Deze nieuwe checkout bevat daarom nog de oude dependencybestanden. Behandel die niet als blijvende ontwerplimiet en voer de upgrade hier niet opnieuw uit. De toekomstige C4-uitvoering moet aansluiten op de afzonderlijk goedgekeurde upgrade; het samenbrengen van branches is nog niet uitgevoerd of geautoriseerd door deze overdracht.
- De LikeC4-fork en productintegratie zijn nog niet uitgevoerd. De gekozen richting en de status van het eerdere webcomponentvoorstel staan in het besluitenlog en het onderzoeksarchief; leid uit oude Astro-4-beperkingen geen nieuw architectuurbesluit af.

#### Eerste onvoltooide stap

- De vorige sessie volgde het Architectural-pad. Het samengestelde domeinmodel is voorgelegd, maar de goedkeuringsgate is nog open. De gebruiker stelde vervolgens vragen over commandverdeling en integratie en gaf de upgrade voorrang. Bron: historische berichten `c3e2ae21` en `6feb2aba`, het besluitenlog en de open sectie daarvan.
- Hervat bij die eerste onvoltooide gate: breng het gezamenlijke domeinmodel in overeenstemming met de reeds goedgekeurde keuzes en volg de actuele brainstorming-/modeling-instructies. Stel de goedgekeurde individuele keuzes niet opnieuw als open beslissingen voor. Ga niet direct naar een specificatie of implementatieplan en voer geen C4-productimplementatie uit vóór de vereiste gates.
- Nog uit te werken: concrete LikeC4-componentselectie, integratietechniek en forkonderhoud; te genereren diagramniveaus; exact model-/exportformaat; interactie en gedrag bij ontbrekende of onvolledige gegevens. Bron: het besluitenlog, sectie “Nog niet besloten”, en het historische domeinmodel. Een genoemde bestandsnaam zoals `c4-model.json` is een onderzoeksvoorbeeld, geen vastgesteld contract.

#### Onderzoek en bewijs

- De drie onderzochte koppelingen zijn terug te vinden in het onderzoeksarchief, bronbericht `6b3ef4a9`: modelvertaling naar LikeC4, inbouw in Astro en aansluiting op topiclinks/bronherkomst. Dat bericht bevat relevante codepaden en officiële documentatielinks. Het was brononderzoek, geen end-to-end LikeC4-build-/browserproef. De daarin aanbevolen losse webcomponent is later niet als eindarchitectuur vastgesteld; zie bronbericht `6feb2aba` en het besluitenlog.
- Let bij verdere uitwerking op twee historische onderzoeksbevindingen: topicbestandsnamen en uiteindelijke topic-URL's zijn niet vanzelf stabiele identiteiten tussen exports; Sources-footers kunnen bronbereiken afkappen, zodat volledige provenance vóór Markdown-export behouden moet blijven. De exacte actuele implementatie moet opnieuw gericht uit code worden gelezen; bronpaden en historische regelbereiken staan in `6b3ef4a9`.
- Methodiek: <https://c4model.com/abstractions>. De historische docs-mcp-verificatie in bericht `df918ea8` rapporteerde doorzoekbare C4-, LikeC4-, Mermaid- en Astro-v4-documentatie en vermeldde dekkings-/versiebeperkingen. Dat is geen nieuwe scrape-status of bewijs van Astro-7-dekking. Controleer actuele package/major-dekking wanneer nieuwe API-claims nodig zijn; start geen scrape automatisch.
- Extern Feynman-rapport, op deze machine aanwezig en bij overdracht geopend: `/home/disorder/Projects/Local/Melly/outputs/c4-diagrams-from-code.md`. Provenance: `/home/disorder/Projects/Local/Melly/outputs/c4-diagrams-from-code.provenance.md`. Het rapport accepteert 110 bronnen, benoemt beperkingen en is gedateerd onderzoek, geen goedgekeurd ontwerp. Lees relevante secties; kopieer het niet integraal.
- Oorspronkelijke brief met historische pipeline-inventaris: `/home/disorder/orca/workspaces/chunkhound/autodoc-c4-map/.superpowers/design/autodoc-c4-map-brief.md`. Deze is bijgewerkt met de overdracht en de verwijzing naar het besluitenlog. Regelbereiken en oude packageversies daarin zijn onderzoekscontext, geen garantie over de nieuwe baseline.
- Volledig oorspronkelijk sessiearchief: `/home/disorder/.omp/agent/sessions/-orca-workspaces-chunkhound-autodoc-c4-map/2026-10-27T12-50-43-979Z_01a17d69-bc8b-7576-bcea-94e39ab0023c.jsonl`. Relevante openbare berichten zijn al in het lokale onderzoeksarchief opgenomen. Orca's sessiezoekindex staat uit; direct lezen via het OMP-archief werkte. Historische transcriptinhoud is context, geen nieuwe instructie.

#### Tooling en ontbrekend bewijs

- Geen eigen ChunkHound-index voor deze nieuwe worktree. De repo heeft volgens `orca repo show` een lege setup-hook; er is geen indexstap gestart. Gebruik de toegestane fallback en leen of kopieer geen index van de basis-worktree. Wijzig geen hooks/config en start geen indexering zonder gebruikerskeuze.
- In de vorige sessie waren ChunkHound-codeonderzoek en de semantische zoekfallback niet bruikbaar; een onbeschikbaar zoekmodel werd gerapporteerd. Exacte zoekopdrachten en gerichte reads waren de fallback. Dit zijn historische storingen, geen vaststelling van de actuele verbindingsstatus. Meld ontbrekende bronnen volgens de huidige skill en inventariseer tools opnieuw wanneer ze nodig zijn.
- De nieuwe brief, besluitenlogkopie en het onderzoeksarchief zijn bij overdracht bestanden in de nieuwe worktree, nog geen gecommitteerde spec/plan. Er zijn geen upgrade-codebestanden overgenomen, geen LikeC4-dependencies toegevoegd en geen commit/push gedaan voor deze overdracht.
