# Onderzoek: het v4-model van de COGNiam-toolkit als basis voor §1

Datum: 2026-11-12. Inventaris door een subagent. Alle paden staan onder `melly/COGNiam/packages/cogniam/`, en `M` staat voor `src/core/model.ts`. Waar de subagent iets afleidde in plaats van het te lezen, staat "afgeleid".

Doel: weten hoe het dossiermodel (schemaVersion 4) eruitziet, want ChunkHound exporteert later naar dat model (§8). Het is geen basis voor §1 (B10).

## Vorm van het dossier

- JSON, gevalideerd met zod. De typenamen en veldnamen zijn Engels. De foutmeldingen en de inhoud van de fixtures zijn Nederlands.
- Op schijf staat een map `.cogniam/` met de verwijzing `HEAD.json`. Elke revisie heeft een eigen map, `revisions/r<N>-<uuid>/revision.json`, met het hele model in één bestand plus BPMN-bestanden (`storage.ts:225-263`).
- Controle: `checkStructure` (`validation.ts:19`) geeft diagnoses `{severity, code, message, entityId}`. Er zijn ongeveer 35 codes, onder meer `duplicate-id`, `missing-reference`, `template-placeholder`, `cardinality` en `population-closure`. Een JSON Schema ontstaat via `z.toJSONSchema`; een los schemabestand is er niet.

## Elementen

Elk element heeft `id`, `name`, `status`, `sourceIds[]`, `dependsOn[]`, `reviewRequired` en `notes?` (M:13-23).

| Nederlands | v4-identifier | Belangrijkste velden |
|---|---|---|
| begrip | `Concept` | `definition`, `identification[]`, `valueType` (object, text, number, date, datetime, boolean), maten `maxLength`, `digits` en `decimals` (M:224) |
| feittype | `FactType` | `reading` (vrije tekst), `roles[] {name, conceptId, derivedBy?}`, `templates[] {id, text}` (M:237) |
| verwoording | `reading`, `templates`, `Verbalization` | Een template gebruikt rolplaatsen `{Rolnaam}`. De controle legt elke rolplaats naast een rolnaam (`validation.ts:134`). |
| voorbeeldfeit | `Fact`, `ObjectEntity`, `Population` | `Fact.roles` koppelt een rolnaam aan een object-id (M:262-276) |
| beperkingsregel | `Rule` | `modality`, `expression`, `applicability?`, `parameters?`, `meaning?` (M:488) |
| afleidingsregel | `Rule` met `modality: "derivation"` | Een rol verwijst ernaar via `derivedBy` |
| gebeurtenisregel | geen eigen element | `states` (M:519) en `transitions` (M:527: `fromStateId`, `toStateId`, `actorId`, `ruleIds`, `message?`, `readFactTypeIds?`, `producedFactTypeIds?`) |
| kennisgebied | `Submodel` | `conceptIds[]`, `factTypeIds[]` (M:376) |
| identificatie | `Identification` | `conceptId`, `kind` (primary of alternative), `parts[]` (M:279) |
| bron | `Source` | `uri`, `excerpt?`, `hash?`, `location?` (M:541) |

Regels:
- **Eén regel per beperking**, niet gegroepeerd per feittype.
- **Soorten uitdrukking** (M:58-87): `cardinality`, `compare`, `set-compare` (subset of equal), `unique`, `and`, `or`, `not`, `implies`, `quantified`, `predicate` (vrije tekst met verwijzingen) en `allowed-values`.
- **Geen eigen soort voor verplicht of uitsluiting.** Verplicht is `cardinality` met minimaal 1 (afgeleid). Uitsluiting is een combinatie met `not` (afgeleid).
- **Modaliteit**: necessity, obligation, permission, prohibition of derivation.

## Overige punten

- **Voorbeeldfeiten zijn optioneel.** De controle bewaakt alleen samenhang (`population-closure`). Het echte Micromundo-dossier heeft geen voorbeeldfeiten.
- **Id's zijn vrij gekozen, leesbare slugs** volgens `/^[A-Za-z][A-Za-z0-9_.-]{0,127}$/` (M:3), bijvoorbeeld `R.business.number.unique` of `ft.investor.registeredWith`. Een rol wordt aangewezen met zijn naam.
- **Statussen** (M:5-12): hypothesis, source-statement, derived, design-decision, validated, open.
- **Niveaus van de kennisdriehoek** staan niet expliciet in het schema. Afgeleid: niveau 1 zijn objecten, feiten en populaties; niveau 2 zijn begrippen, feittypen, regels en identificaties; het schema zelf is niveau 3.
- **Het echte Micromundo-model** staat in de revisies, niet in `inspectie.json`. Het heeft schemaVersion 2, 30 begrippen, 48 feittypen, 37 regels en 4 submodellen.

## Gebruik

Volgens B10 is dit model geen voorbeeld voor §1: het metamodel volgt alleen het CogNIAM-boek. Deze notitie dient als achtergrond voor de export naar het dossier (§8) en voor de dossierlezer na versie 1. Waar het metamodel uit §1 afwijkt van v4, moet de export dat verschil overbruggen.
