# Onderzoek: het metamodel volgens het CogNIAM-boek (basis voor §1)

Datum: 2026-11-12. Volgens B10 bepaalt alleen het boek de methodiek.

Bron is de ongecorrigeerde OCR van het boek. Paginanummers zijn gedrukte pagina's. Een subagent heeft de inventaris gemaakt. Wat ik zelf tegen de OCR heb nagelezen, staat als **nagelezen**. De rest is nog te controleren tegen de scans voordat de §1-spec erop bouwt. Citaten zijn kort gehouden; de rest is in eigen woorden.

## Kennisdriehoek en kennisklassen (nagelezen)

Hoofdstuk 1, p.5-6, figuur 1.1 en 1.3:
- **Niveau I** bevat de feiten (*ground facts*).
- **Niveau II** bevat de domeinspecifieke regelgeving.
- **Niveau III** bevat de generieke regelgeving.

Op niveau II en III onderscheidt het boek zeven kennisklassen:

| Code | Kennisklasse | Functie (in eigen woorden) | Voorbeeld in code (eigen inschatting) |
|---|---|---|---|
| BO | Begripsomschrijvingen | Elk woord in de feiten is helder gedefinieerd | Docblocks, domeinwoordenlijsten, naamgeving |
| VAR | Variabelen of invulplaatsen | De plaatsen in een feit die een waarde krijgen | Kolommen, velden, parameters |
| ZS | Zinsjablonen (feittypeformuleringen) | Zinnen voor communicatie per doelgroep | Modellen, tabellen en relaties, met een verwoording erbij |
| VR | Validatieregels (beperkingsregels) | Beperken welke verzamelingen feiten en welke overgangen daartussen zinvol zijn | Validators, `CHECK`, `UNIQUE`, `NOT NULL`, guards |
| AR | Afleidingsregels | Geaggregeerde feiten afleiden | Berekende velden, accessors, query's |
| UR | Uitwisselingsregels | Hoe feiten uit de omgeving worden toegevoegd, verwijderd of gewijzigd | Controllers, endpoints, commands, repositories |
| ER | Eventregels | Wanneer een uitwisselings- of afleidingsregel start | Event listeners, observers, jobs, webhooks |

Vier andere kennisklassen zijn uit te drukken in deze zeven (p.6):
- *rules of governance*: wat er van mensen wordt gevraagd;
- bedrijfsprocessen en activiteiten;
- beslissingen in die processen;
- berichten tussen taakuitvoerders.

## Overige bevindingen (subagent, nog na te lezen)

- **Begrippenlijst** (bijlage B, p.315-322):
  - alfabetisch, met per begrip een term, het meervoud en eventueel een afkorting;
  - in een definitie staat het begrip zelf tussen accolades en staan verwijzingen naar andere begrippen tussen vierkante haken;
  - soms een synoniem.
- **Feittypen** (hoofdstuk 11 en 12, p.187-189 en 218):
  - een zinsjabloon heeft rolplaatsen `<Rol>` en een nummer;
  - een feittype mag meerdere synonieme zinsjablonen hebben;
  - een objecttype heeft een identificerend zinsjabloon;
  - een feittypediagram toont datatype, verplichte rollen, populatie, zinsjablonen en regels.
- **Voorbeelden**: de methode werkt vanuit concrete voorbeelden, die met de domeindeskundige worden gevalideerd (hoofdstuk 13, p.225-226). Een harde eis van voorbeelden per feittype is niet gevonden.
- **Regel-id's**: elke regel heeft een eigen id met een voorvoegsel per soort, bijvoorbeeld `ps` (identificatie), `dv` (deelverzameling), `gl` (gelijkheid), `wr` (waarderestrictie), `ar` (afleiding) en `er` (event). De nummers lijken in blokken per soort te staan, zoals `wr5001`. De betekenis van `as` en `abr` is niet gevonden.
- **Verplichte rollen** zijn een markering in het diagram, geen regel met een eigen id.
- **Toestanden** zijn waarden van een statusbegrip, elk gedefinieerd door de gebeurtenis die ertoe leidt. Het boek stelt een toestandsdiagram gelijk aan een validatieregel (p.167). De dynamiek zit in BPMN.
- **Termen die het boek niet gebruikt**: "totaliteitsregel", "uitsluitingsregel" en "gebeurtenisregel"; het boek zegt "eventregel". Ook "kennisgebied" definieert het niet formeel.
- **Gestructureerd Nederlands** (bijlage D, p.327-332): per item een definitie, een referentieschema en een noodzakelijkheid.

## Verschil met de huidige lijst in §1

| Huidige lijst in §1 | Volgens het boek |
|---|---|
| kennisgebied | Geen formeel begrip in het boek |
| begrip | BO |
| feittype (rollen, objecttypen, verwoordingen) | ZS en VAR |
| voorbeeldfeit | Feiten op niveau I |
| beperkingsregel | VR, validatieregel |
| afleidingsregel | AR |
| gebeurtenisregel | ER, eventregel |
| ontbreekt | UR, uitwisselingsregel |
