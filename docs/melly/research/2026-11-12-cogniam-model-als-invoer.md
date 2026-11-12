# Onderzoek: model als invoer (§0, vraag 5)

Vastgelegd op 2026-11-12 als onderbouwing van [B6](../decisions/2026-11-12-cogniam-model.md). Dit is een bronnenoverzicht, geen spec. Bron, interpretatie en voorstel zijn gescheiden. De citaten zijn op 2026-11-12 in de genoemde bestanden nagelezen.

## Vraag

Moet versie 1 het model ook als invoer accepteren? Dan voegt een mens eerst een gepland feittype of een geplande regel toe, en volgen de testspecificaties voordat de code bestaat. Het alternatief is dat versie 1 het model alleen uit code afleidt.

## Bron 1: het boek (Kennis Gebaseerd Werken, CogNIAM)

OCR zonder correctie: `/home/disorder/Projects/Github/melly/COGNiam/leesbaar/hoofdstukken/`. Scans zijn niet gecontroleerd.

| Onderwerp | Bron | Vindplaats |
|---|---|---|
| Model eerst | "13.3.3 Alle bedrijfsregels compleet vóór overdracht", omdat de regels "bijna altijd verre van compleet zijn" | `13-*.md:197-201`, p.226-227 |
| Model eerst | "M.a.w.: 'Het model is de applicatie'" | `17-*.md:138`, p.284 |
| Validatie | "[Een materie]deskundige zal immers goed in staat zijn om ground facts te valideren." | `03-*.md:618`, p.38-39 |
| Testgevallen | "[We] bevelen aan om vanaf het begin van de ontwikkelingscyclus van een bedrijfsproces[model] … concrete voorbeelden … test cases te gebruiken" | `14-*.md:97`, p.234 |
| Afleiden uit bestaande systemen | Alleen "archeologische ICT-diensten [zijn] niet langer noodzakelijk" | `11-*.md:1290`, p.~197 |

Wat het boek niet zegt:
- Het beschrijft geen methode om een model uit code of databases af te leiden.
- Het kent geen statussen of levenscyclus voor regels; "status" komt alleen voor als toestand van een bedrijfsobject.
- Het beschrijft niet hoe je controleert of een implementatie aan het model voldoet.

Dit is een negatief resultaat op gerichte zoektermen, geen volledige lezing.

Interpretatie: in het boek is de mens (de materiedeskundige) de autoriteit, en concrete voorbeelden zijn het middel om te valideren. Een model dat uit code is afgeleid, is in boektermen een hypothese totdat een deskundige het met voorbeelden heeft gevalideerd. De statussen van U1 zijn een eigen toevoeging.

## Bron 2: melly-slim en de COGNiam-toolkit

| Onderwerp | Bron | Vindplaats |
|---|---|---|
| Model eerst | "COGNiam als bron van het domeinmodel"; "Plan afgeleid van het model: klassen → bestanden en taken, regels → tests" | `melly-slim/docs/melly/specs/2026-10-06-superpowers-omp-modeling-design.md:43-46` |
| Regel naar test | Elke domeinregel krijgt een test met het id van de regel in de naam, of staat als `not in software` in het plan | `melly-slim/docs/melly/models/*.md`, tabellen "not in software" |
| Statussen in het dossier | `hypothesis`, `source-statement`, `derived`, `design-decision`, `validated`, `open` | `melly/COGNiam/packages/cogniam/src/core/model.ts:5-23` |
| Instemming | `decisions[].consent` legt het "ja" van de mens vast | `model.ts:581-606` (volgens het subagentrapport, niet nagelezen) |
| Dossier op schijf | Gecommitte JSON in `.cogniam/`, met revisies en `schemaVersion: 4`. Het dossier is opt-in. | `melly-slim/.cogniam/`; `melly-slim/docs/melly/decisions/2026-10-27-cogniam-dossier-opt-in.md` |
| Deze feature als werkhypothese | Uit code komt een "Hypothesemodel, status: afgeleid uit code". Een mens bevestigt de betekenis met voorbeelden. Drift is "een *bevinding*, nooit een automatische modelupdate". | `melly-slim/outputs/2026-10-27-cogniam-cem-roundtrip-verkenning.md:59-82` |
| Open punt | "Startrichting: code → model (bestaande projecten) of model → code (nieuwe features)?" | idem, `:100` |
| Kosten | Vrije notities gaven evenveel begrip als het volledige dossier, tegen 3–5× zoveel tokens voor het dossier. Automatisch onderhoud moet dus goedkoper zijn dan het huidige dossier. | idem, `:55-57` |

## Bron 3: ChunkHound

| Onderwerp | Bron | Vindplaats |
|---|---|---|
| Curatie corrigeert alleen | Met overrides kun je classificeren, plaatsen, hernoemen, beschrijven, verwijderen, samenvoegen en uit elkaar houden. Toevoegen kan niet. | `chunkhound/code_mapper/c4/model.py:153-162` |
| Gevonden of gedocumenteerd | Element-status `found` (citatie uit code of configuratie) of `documented` | `c4/model.py:14`, `c4/curation.py:257-259` |
| Handgeschreven invoer staat in een bestand | "Stable per-scope cache persistence without overwriting handwritten overrides." Het pad is `.chunkhound/map.lock.json`. | `c4/lockfile.py:1-10` |
| Database | De index staat onder `.chunkhound/`. Die map staat in `.gitignore`. | `.gitignore:290` |

## Afweging

| Optie | Boek | melly-slim | ChunkHound |
|---|---|---|---|
| Alleen uit code | Wijkt af van model eerst | Dekt geen geplande regels (regels → tests) | Past |
| Toevoegen in het curatiebestand | Past | Menselijke kennis staat op twee plekken (curatie en dossier) | Breekt het patroon: curatie corrigeert alleen |
| **Modelbestand als bron** | **Past** | **Past, en het dossier kan later een tweede bron worden** | **Past: zelfde idee als `documented` tegenover `found`** |
| Dossier als bron van waarheid | Het boek werkt het toetsen van code nergens uit | Het dossier is opt-in en duur | Dan hangt ChunkHound af van schema 4 van een externe TypeScript-toolkit |

Een bestand en geen database, omdat:
- menselijke invoer bronmateriaal is, geen afgeleide index;
- een bestand meegaat in Git, met review in de PR en herkomst via `git blame`;
- de database in de hoofdmap staat, en die is vaak zelf geen repository (B4);
- C4 en het dossier menselijke invoer al op deze manier opslaan.

## Voor latere secties

- §1: de statussen moeten te vertalen zijn naar het dossier: `extracted`/`proposed` → `hypothesis`, `confirmed` → `validated`.
- §7: een testspecificatie is een concreet voorbeeld met een verwachte uitkomst: geldig, of welke regel het overtreedt. Zo doen het boek (p.234) en de `tests` in het dossier het ook.
- §7: gebruik de conventie uit melly-slim, het id van de regel in de testnaam.
