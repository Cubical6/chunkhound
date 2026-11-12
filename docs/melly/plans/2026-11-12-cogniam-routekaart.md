# Routekaart: Cogniam-kennismodel uit code

- Datum: 2026-11-12 · Basis: `main` op `f89044d9` · Branch: `worktree-cogniam-plan`
- **Status:** concept. Sectie 0 is de eerstvolgende stap. Deze routekaart geeft geen toestemming voor implementatie, providerruns of een push naar `main`.
- Besluitenlog: [2026-11-12-cogniam-model.md](../decisions/2026-11-12-cogniam-model.md)

## Doel

ChunkHound leidt uit één of meer codebases een Cogniam-kennismodel af. Het model bevat begrippen, feittypen met verwoordingen, voorbeeldfeiten, beperkingsregels, afleidingsregels en gebeurtenisregels, elk met een bronverwijzing.

Developers gebruiken het model om:
- regels terug te vinden;
- de impact van een wijziging te bepalen;
- inconsistenties tussen services te zien;
- vooraf testspecificaties en een regeldekkingsrapport te maken.

Het model is een concept dat mensen valideren. Het claimt geen volledigheid.

## Werkwijze

Elke sectie (§0 tot en met §10) is één werkpakket en kan als handoff naar een nieuwe sessie. Een sectie doorloopt vijf stappen:

1. **open**: nog niet begonnen.
2. **ontwerp**: alleen nog onbesliste, materiële vragen, één per beurt, in het Nederlands. Antwoorden gaan naar het besluitenlog.
3. **spec**: `docs/melly/specs/<datum>-cogniam-<sectie>-design.md` met aanhaakpunten als `file:regel`, invarianten en testcontracten.
4. **plan**: `docs/melly/plans/<datum>-cogniam-<sectie>.md` volgens `~/.claude/templates/PLAN.md`. Elke fase blijft onder ~150k pi-context en ~20 minuten werk en heeft een eigen testcommando.
5. **gereed**: de gebruiker heeft spec en plan goedgekeurd. De sectie is dan implementatiegereed.

Regels:
- Werk na elke stap de statustabel bij.
- Een sectie gaat pas naar *spec* als haar afhankelijkheden minstens de status *spec* hebben, want de contractvorm moet vastliggen. §10 is een uitzondering (zie daar).
- Een besluit dat een andere sectie raakt, gaat in het log en wordt in die sectie hieronder vermeld.

## Status

| § | Sectie | Hangt af van | Status | Spec | Plan |
|---|---|---|---|---|---|
| 0 | Kader en besluiten | – | gereed | n.v.t. | n.v.t. |
| 1 | Metamodel en contract | 0 | ontwerp | – | – |
| 2 | Vaste structuurextractie | 1 | open | – | – |
| 3 | LLM-extractie | 1 (2 voor ankers) | open | – | – |
| 4 | Consolidatie en identiteit | 2, 3 | open | – | – |
| 5 | Meerdere repositories en koppeling met C4 | 4 | open | – | – |
| 6 | Modelcontroles en conflicten | 4 | open | – | – |
| 7 | Testspecificaties en regeldekking | 5, 6 | open | – | – |
| 8 | Uitvoer: AutoDoc, lockbestand, drift en export | 1, 4 | open | – | – |
| 9 | MCP-ontsluiting | 8 | open | – | – |
| 10 | Evaluatie: goudmodel en meetrun | 1 | open | – | – |

Kritiek pad (B4): §0 → §1 → §2 en §3 parallel → §4 → §5 en §6 parallel → §7. §8 en §10 lopen ernaast.

Prioriteit volgens B2 (testspecificaties en regeldekking eerst):
- §8 in versie 1 alleen het lockbestand, en JSON als uitvoer van §7;
- AutoDoc-pagina's, drift en export daarna;
- §9 (MCP) als laatste.

## Uitgangspunten (bevestigd, B7)

- **U1 Concept, geen volledigheid.** Elk element heeft twee eigenschappen.
  - Wie ervoor instaat: `extracted` (vast afgeleid), `proposed` (LLM) of `confirmed` (mens). Alleen een mens zet `confirmed`.
  - Of het in de code is gevonden: *gepland* (alleen in het modelbestand) of *gerealiseerd* (met een citatie uit code).
- **U2 Geen element zonder bron.** Elk element heeft minstens één bron: een citatie uit code (repository, pad, regelbereik en commit), of een regel in het modelbestand. Bij een regel in het modelbestand blijkt de auteur uit Git.
- **U3 Vast gaat voor LLM.** Spreekt een LLM-uitkomst een vaste uitkomst tegen, dan wordt dat een conflict, geen vervanging.
- **U4 Domein, geen techniek.** Technische regels (retry, cache, logging, infrastructuur) komen niet in het model, of staan er apart gemarkeerd in.
- **U5 Opt-in zonder bijwerking.** Cogniam heeft een eigen opdracht (B5). Zonder die opdracht blijft de uitvoer van `map` en `autodoc` byte-gelijk.
- **U6 Hergebruik.** LLM-aanroepen gaan via de gedeelde extractielaag. Er komt geen eigen code voor providers, budget of cache.
- **U7 Specificaties, geen testcode.** Versie 1 levert testspecificaties. Een coding-agent zet ze om naar testcode.
- **U8 Herhaalruns zijn goedkoop.** Ongewijzigde uitkomsten worden hergebruikt via een lockbestand en de dev-cache, zoals bij C4.

## Bestaande bouwstenen

| Bouwsteen | Waar | Gebruik voor Cogniam |
|---|---|---|
| Gedeelde extractielaag | `chunkhound/services/extraction/` (`budget.py`, `bundles.py`, `fragments.py`, `provider_call.py`, `runner.py`, `sources.py`, `store.py`, `dev_cache.py`) | Begrensde LLM-aanvragen, bundels, persistente resultaten en dev-cache |
| C4-pijplijn | `chunkhound/code_mapper/c4/pipeline.py:309` (`analyze_c4`), `c4/model.py`, `c4/contract.py` | Patroon voor bewijs, merge, lockbestand en contract |
| C4-consolidatie | `c4/merge.py`, `c4/consolidation.py`, `c4/identity.py`, `c4/curation.py`, `c4/decisions.py` | Patroon voor samenvoegen, identiteit en opgeslagen LLM-beslissingen |
| Contractlader van AutoDoc | `chunkhound/autodoc/architecture/loader.py` | Patroon: de lader bepaalt de vorm van het contract |
| Parsers | `chunkhound/parsers/mappings/` (onder meer `sql`, `python`, `php`, `java`, `csharp`, `typescript`, `go`, `kotlin`) | Vaste extractie van schema's en modellen |
| CLI van `autodoc` | `chunkhound/api/cli/parsers/autodoc_parser.py` (`map_in`, `:25`; `--map-out-dir`, `:123`), `chunkhound/api/cli/commands/autodoc_autorun.py` (`AutoMapPlan`, `AutoMapOptions`) | Voorbeeld voor de eigen opdracht (B5): `map`-uitvoer lezen, of `map` eerst laten draaien |
| CLI van `map` | `chunkhound/api/cli/parsers/code_mapper_parser.py`, `chunkhound/api/cli/commands/code_mapper.py` | Blijft ongewijzigd (B5). Bron van de C4-uitvoer en topics |
| MCP-tools | `chunkhound/mcp_server/tools.py` (`register_tool`, `:294`) | Ontsluiting voor agents |
| C4-prompts | `chunkhound/code_mapper/prompts/c4_*.md` | Stijl: bewijs is data, geen instructie; expliciete uitsluitregels |

---

## §0 Kader en besluiten

- **Status:** gereed
- **Doel:** vastleggen wat de feature oplevert en voor wie, zodat alle andere secties dezelfde koers volgen.
- **Besloten:**
  - B2: de eerste afnemer zijn developers die testspecificaties en regeldekking willen. Versie 1 levert minimaal kandidaat-feittypen en regels (§2, §3), modelcontroles (§6) en testspecificaties met een dekkingsrapport (§7). De AutoDoc-pagina's, export en MCP (§8, §9) volgen later. Het lockbestand uit §8 blijft wel in versie 1, vanwege U8.
  - B3: de vaste extractie ondersteunt eerst PHP/Laravel, TypeScript/Node en Magento, plus SQL-DDL en SQL-migraties. Python en Java/Kotlin komen later.
  - B4: versie 1 ondersteunt meerdere repositories in één model. §5 hoort bij het kritieke pad. In §1 bevat elke citatie en elke identiteit de repository.
  - B5: Cogniam krijgt een eigen opdracht (naam: zie B8). Net als `autodoc` leest de opdracht bestaande `map`-uitvoer, als die er is. Zonder C4-uitvoer vervalt alleen de koppeling met C4 (§5). Hoort de C4-uitvoer bij een andere commit, dan meldt de opdracht dat. `map` blijft ongewijzigd.
  - B6: een mens geeft invoer via Claude Code, later ook via een webinterface. Het model is in versie 1 ook invoer: geplande feittypen en regels staan in een modelbestand in de repository. ChunkHound leest dat bestand als bron en schrijft er nooit in. Een element uit dat bestand zonder citatie uit code is *gepland*, met zo'n citatie *gerealiseerd*. Dat werkt net als `documented` tegenover `found` bij C4. Een lezer voor het COGNiam-dossier (`.cogniam/`) komt na versie 1. Onderbouwing: [onderzoek](../research/2026-11-12-cogniam-model-als-invoer.md).
  - B8: de opdracht heet `chunkhound domain <hoofdmap>`, de module `chunkhound/domain_model/`. Code, JSON-sleutels en CLI-uitvoer zijn Engels, en de docs krijgen een woordenlijst Nederlands–Engels. "CogNIAM" komt alleen voor in de docs en in de latere export naar het dossier.
  - B9: het goudmodel voor §10 is de praktijkcasus Micromundo uit het CogNIAM-boek (microleningen). Code voor Micromundo bestaat nog niet. §10 schrijft daarom een referentie-implementatie, verdeeld over minstens twee repositories.
  - B10: alleen het CogNIAM-boek bepaalt de methodiek. melly en melly-slim zijn geen voorbeeld voor het metamodel, het goudmodel of de conventies. Het v4-dossier telt alleen voor de latere export en de dossierlezer.
- **Te beslissen:**
  1. ~~Eerste afnemer~~ (besloten, B2).
  2. ~~Eerste talen en frameworks~~ (besloten, B3).
  3. ~~Meerdere repositories in versie 1~~ (besloten, B4). ~~Referentiecodebases voor §10~~ (besloten, B9: Micromundo; de verdere uitwerking staat in §10).
  4. ~~CLI-vorm~~ (besloten, B5: eigen opdracht).
  5. ~~Model als invoer in versie 1~~ (besloten, B6: beperkt, via een modelbestand; dossierlezer later).
  6. ~~Bevestiging van U1 tot en met U8~~ (besloten, B7).
  7. ~~Naamgeving in code en uitvoer~~ (besloten, B8: `chunkhound domain`, Engelse termen).
- **Gereed als:** de besluiten staan in het log en deze routekaart is bijgewerkt: scope, volgorde en de vragen per sectie. §0 krijgt geen spec en geen plan.

## §1 Metamodel en contract

- **Status:** ontwerp · **Hangt af van:** §0
- **Doel:** de datavorm van het kennismodel. Alle andere secties bouwen hierop.
- **Basis (B10):** het metamodel volgt het CogNIAM-boek. Het [onderzoek naar het v4-dossiermodel](../research/2026-11-12-cogniam-v4-metamodel.md) is geen voorbeeld voor §1. Het is alleen achtergrond voor de export in §8.
- **Inhoud:**
  - Elementen:
    - kennisgebied;
    - begrip: term, definitie, synoniemen;
    - feittype: rollen, objecttypen, verwoordingen;
    - voorbeeldfeit;
    - beperkingsregel: uniciteit, totaliteit, waardebeperking, subset, gelijkheid, uitsluiting;
    - afleidingsregel;
    - gebeurtenisregel: toestand, overgang, aanleiding;
    - citatie: repository, pad, regelbereik, commit;
    - status en herkomst: vast, LLM of mens.
  - Stabiele identiteiten tussen runs. Les uit C4: bestandsnamen en URL's zijn geen stabiele identiteit.
  - Een JSON-contract met schemaversie, en een lader die de vorm bepaalt (patroon `autodoc/architecture/loader.py`).
- **Te beslissen:**
  - granulariteit: één regel per beperking, of beperkingen gegroepeerd per feittype;
  - vorm van een verwoording: een zin met rolplaatsen (FCO-IM-stijl) of vrije tekst;
  - zijn voorbeeldfeiten verplicht of optioneel per feittype;
  - hoe de niveaus van de kennisdriehoek in het model terugkomen;
  - het modelbestand voor menselijke invoer (B6): naam, plek per repository, en de vorm. Een mens schrijft het niet zelf maar via Claude Code, en later via een webinterface. Het moet daarom een schema hebben dat een agent kan lezen, en een controle met precieze foutmeldingen waarmee de agent zichzelf kan verbeteren. YAML of JSON?
  - twee assen per element: wie ervoor instaat (U1) en of het in de code is gevonden (gepland of gerealiseerd);
  - de Engelse termen en de woordenlijst Nederlands–Engels (B8): begrip, feittype, verwoording, voorbeeldfeit, beperkingsregel, afleidingsregel, gebeurtenisregel en kennisgebied. Liefst de termen die de Engelstalige CogNIAM- en FCO-IM-literatuur zelf gebruikt.
- **Gereed als:**
  - de spec bevat dataclasses, een JSON-voorbeeld, een voorbeeld van het modelbestand, identiteitsregels en laadfouten;
  - het plan heeft fasen voor model, lader en contracttests.

## §2 Vaste structuurextractie

- **Status:** open · **Hangt af van:** §1
- **Doel:** kandidaat-feittypen en beperkingsregels zonder LLM afleiden uit schema's en modellen.
- **Bronnen per stack (B3):**

  | Stack | Feittypen | Beperkingsregels | Ook nuttig voor |
  |---|---|---|---|
  | SQL | `CREATE TABLE`, kolommen | `PRIMARY KEY`, `UNIQUE`, `NOT NULL`, `FOREIGN KEY`, `CHECK` | – |
  | Laravel | Migraties (`Schema::create`, Blueprint-kolommen), Eloquent-modellen en relaties (`hasMany`, `belongsTo`) | Blueprint-modifiers (`->unique()`, `->nullable()`, `->foreign()`), validatieregels in `FormRequest::rules()` en `Validator::make` (`required\|email\|unique:users`), PHP-enums | §7: validatieregels zijn direct bruikbaar als testgevallen |
  | TypeScript/Node | Prisma-schema, TypeORM-entities | Opties in `@Column({ unique, nullable })`, Zod-schema's (`z.string().min(1)`), enums en literal-uniontypes | – |
  | Magento 2 | `etc/db_schema.xml` (declaratief schema), EAV-attributen in data patches (`Setup/Patch/Data/*.php`, `EavSetup::addAttribute`), service contracts (`Api/Data/*Interface.php`) | `nullable`, `length` en constraints in `db_schema.xml`; `required` en `unique` bij EAV-attributen; source models als waardebeperking; validatie in `ui_component/*.xml` | §3: `etc/events.xml` en observers voor gebeurtenisregels. §5: `etc/webapi.xml` als servicegrens |

- **Bevinding (2026-11-12):**
  - `.xml` wordt als platte tekst geïndexeerd (`chunkhound/core/types/common.py:339`).
  - `.prisma` staat niet in de extensielijst en wordt dus niet geïndexeerd.
  - Gevolg: §2 kan niet op de geïndexeerde chunks bouwen. Het leest de bronbestanden zelf:
    - XML met een veilige XML-parser, zonder externe entiteiten;
    - PHP en TypeScript met de tree-sitter-grammatica's die al meegeleverd worden;
    - Prisma met een eigen kleine parser, of als tekst voor §3.
- **Uitgangspunt:** `chunkhound/parsers/mappings/sql.py`, `php.py` en `typescript.py`.
- **Te beslissen:**
  - Magento: alleen eigen modules (`app/code`) of ook kernmodules en modules van derden in `vendor/`;
  - Magento EAV: wordt elk attribuut een eigen feittype, of komt er één generiek feittype "entiteit heeft attribuutwaarde";
  - TypeScript: welke ORM en welke validatiebibliotheken eerst (Prisma, TypeORM, Zod, class-validator);
  - wat te doen als bronnen elkaar tegenspreken, bijvoorbeeld een migratie tegenover een model of `FormRequest`;
  - de volgorde van migraties: welke migratie geeft de huidige toestand (ook bij `dropColumn` en hernoemingen);
  - hoe technische tabellen worden herkend: migratieadministratie, jobs, caches, sessies, Magento-indexers. De uitsluiting zelf gebeurt in §4.
- **Gereed als:**
  - de spec bevat per brontype de vertaling naar §1-elementen, met fixtures;
  - het plan heeft één fase per brontype.

## §3 LLM-extractie

- **Status:** open · **Hangt af van:** §1, en §2 voor ankers
- **Doel:** extraheren wat niet vast af te leiden is:
  - begrippen en definities;
  - verwoordingen;
  - afleidingsregels;
  - gebeurtenisregels;
  - voorbeeldfeiten uit tests en documentatie.
- **Uitgangspunt:**
  - de gedeelde extractielaag (`services/extraction/`): begrensde aanvragen, bundels, persistente opslag en dev-cache;
  - prompts in de stijl van `code_mapper/prompts/c4_*.md`.
- **Te beslissen:**
  - bronselectie per regelsoort: hergebruik van het HyDE-plan en de topics van `map`, of een eigen selectie;
  - hoe de uitvoer van §2 als anker in de prompts komt;
  - waar technische regels worden uitgesloten: in de prompt of in §4;
  - een kostengrens per run.
- **Gereed als:**
  - de spec bevat per prompt een contract (invoer, schema, weigerregels), plus bronselectie en budget;
  - het plan heeft één fase per regelsoort, met tests tegen een nep-provider.

## §4 Consolidatie en identiteit

- **Status:** open · **Hangt af van:** §2, §3
- **Doel:** van losse kandidaten één samenhangend model maken.
- **Inhoud:**
  - dubbele feittypen samenvoegen;
  - synoniemen herkennen (verschillende namen, zelfde begrip) en homoniemen (zelfde naam, ander begrip);
  - domein en techniek scheiden (U4);
  - eigenaarschap vastleggen;
  - status per element bijhouden;
  - conflicten markeren in plaats van er stil een te kiezen.
- **Uitgangspunt:** C4 `merge.py`, `consolidation.py`, `identity.py`, `curation.py` en `decisions.py`. Dat laatste bestand slaat LLM-beslissingen op via `DecisionStore`.
- **Te beslissen:**
  - welke beslissingen vast gebeuren (op naam of structuur) en welke via de LLM;
  - hoe menselijke correcties (bevestigd, verworpen, samengevoegd) worden opgeslagen, zodat ze een nieuwe run overleven, bijvoorbeeld in een curatiebestand;
  - of een bevestigd element verhuist naar het modelbestand (B6), zodat alle kennis waar een mens voor instaat op één plek in Git staat, of als oordeel in het curatiebestand blijft;
  - hoe een gepland element uit het modelbestand wordt gekoppeld aan de code die het later implementeert.
- **Gereed als:**
  - de spec bevat de regels voor samenvoegen, de opslag van correcties en het gedrag bij een conflict;
  - het plan heeft fasen voor vaste consolidatie, LLM-beslissingen en curatie.

## §5 Meerdere repositories en koppeling met C4

- **Status:** open · **Hangt af van:** §4
- **Doel:** één model over services heen, en per C4-relatie welke feittypen erover gaan.
- **Inhoud:**
  - `repository_id` per bron. Die bestaat al in het C4-contract (`repository_lookup`, `with_git_data` in `c4/contract.py`).
  - Koppeling van feittype aan C4-element: welke container is bron of eigenaar.
  - API-schema's als grens: OpenAPI, AsyncAPI, protobuf, eventschema's.
  - Hetzelfde begrip in meerdere services.
- **Bevinding (2026-11-12, uit de code gelezen, niet gedraaid):** ChunkHound werkt met meerdere repositories via een hoofdmap.
  - Er is één index per hoofdmap (`config.target_dir`). Meerdere losse indexen samenvoegen kan niet.
  - Onder de hoofdmap wordt elke Git-repository herkend aan een `.git`-map of -bestand (`chunkhound/utils/ignore_engine.py:246`). Submodules en worktrees vallen daar dus ook onder. De hoofdmap hoeft zelf geen repository te zijn.
  - Elke repository is een grens voor `.gitignore`-regels: regels van de bovenliggende map gelden er niet (`ignore_engine.py:345`, `:378`). De bestanden worden per repository opgehaald (`services/indexing_coordinator.py:2468-2481`).
  - `search` en `code_research` kunnen met `path` tot één repository beperkt worden (`mcp_server/tools.py:676`, `:793`).
  - C4 wijst elk pad toe aan de diepste repository op zijn route (`repository_lookup`, `c4/contract.py:498`). Per repository legt het een eigen HEAD-commit en remote vast (`with_git_data`, `:601`; `:588`).
- **Eerste stap:** een `map`-run op een hoofdmap met twee of meer repositories, om te zien of C4 dit van begin tot eind goed doet.
- **Te beslissen:**
  - hoe repositories worden aangeleverd: één index met meerdere roots, of meerdere indexen;
  - of API-schema's in versie 1 in scope zijn;
  - ~~of §5 een C4-run vereist~~ (B5: zonder C4-uitvoer vervalt alleen de koppeling met C4);
  - hoe de opdracht vaststelt dat de C4-uitvoer verouderd is, bijvoorbeeld via de HEAD-commit per repository uit `with_git_data` of een vingerafdruk uit het lockbestand van `map`;
  - of de opdracht aanbiedt om `map` eerst te draaien als er geen C4-uitvoer is, zoals `autodoc` dat doet.
- **Gereed als:**
  - de spec bevat de koppelregels, het gedrag zonder C4 en fixtures met twee repositories;
  - het plan bevat fasen voor koppeling en API-schema's.

## §6 Modelcontroles en conflicten

- **Status:** open · **Hangt af van:** §4
- **Doel:** vaste controles die fouten en inconsistenties zichtbaar maken.
- **Inhoud:**
  - Structurele controles:
    - elk feittype heeft een uniciteitsregel;
    - elke regel verwijst naar bestaande feittypen;
    - een verwoording dekt alle rollen;
    - elke citatie klopt nog tegen de huidige bron (zoals invariant 4 van de extractielaag).
  - Inhoudelijke conflicten:
    - dezelfde regel met een andere waarde in twee services;
    - documentatie of specificatie tegenover code;
    - een gepland element (B6) dat nog niet in de code staat. Dat is een bevinding, geen fout.
- **Te beslissen:**
  - welke controles fouten zijn en welke waarschuwingen;
  - of een conflict de publicatie blokkeert;
  - hoe het rapport eruitziet.
- **Gereed als:**
  - de spec bevat de lijst met controles, met ernst en voorbeelden;
  - het plan heeft een fase voor de controles en een fase voor het rapport.

## §7 Testspecificaties en regeldekking

- **Status:** open · **Hangt af van:** §5, §6
- **Doel:** per regel een testspecificatie, en per regel of er al een test bestaat.
- **Inhoud:**
  - Een sjabloon per regelsoort:

    | Regel | Testvorm |
    |---|---|
    | Uniciteit | Duplicaat aanbieden, afwijzing verwachten |
    | Totaliteit | Verplichte waarde weglaten, afwijzing verwachten |
    | Waardebeperking | Grenswaarden net binnen en net buiten |
    | Subset en uitsluiting | Verboden combinaties aanbieden |
    | Afleidingsregel | Voorbeeldinvoer met verwachte uitkomst |
    | Gebeurtenisregel | Toegestane en verboden toestandsovergangen |

  - Given/When/Then met concrete data uit voorbeeldfeiten. Een testspecificatie is een concreet voorbeeld met een verwachte uitkomst: geldig, of welke regel het overtreedt. Zo doet het boek het ook (p.234).
  - Ook voor geplande regels (B6): de testspecificatie bestaat voordat de code er is.
  - Voorstel: het id van de regel staat in de testnaam, zodat de dekking per regel te meten is.
  - Koppeling van bestaande tests aan regels.
  - Een regeldekkingsrapport.
  - Contracttestspecificaties per C4-relatie.
- **Te beslissen:**
  - uitvoerformaat: Markdown, Gherkin (`.feature`) of JSON voor agents;
  - hoe "regel gedekt" wordt vastgesteld (tests die de implementerende code aanroepen, of een LLM-oordeel) en hoe zeker dat is;
  - hoe de cirkelredenering wordt zichtbaar gemaakt: tests die uit code zijn afgeleid, bevestigen ook de bugs in die code.
- **Gereed als:**
  - de spec bevat sjablonen met voorbeelden, de dekkingsmethode en het rapportformaat;
  - het plan heeft fasen voor sjablonen, dekking en contracttests.

## §8 Uitvoer: AutoDoc, lockbestand, drift en export

- **Status:** open · **Hangt af van:** §1, §4
- **Doel:** het model zichtbaar en vergelijkbaar maken.
- **Inhoud:**
  - AutoDoc-pagina's: begrippenlijst, feittypen per kennisgebied, regels, dekking.
  - Een lockbestand, zodat een volgende run alleen gewijzigde delen opnieuw doet (patroon `c4/lockfile.py`).
  - Drift tussen twee runs of commits, bijvoorbeeld "deze PR wijzigt regel R12".
  - Export: JSON in versie 1. ORM/NORMA-XML of SBVR later, afhankelijk van §0.
- **Te beslissen:**
  - de paginastructuur in AutoDoc;
  - of drift een eigen opdracht wordt of een rapport bij elke run;
  - de exportformaten, waaronder het COGNiam-dossier (B8, B10). De vertaling van de statussen ligt dan voor de hand: `extracted`/`proposed` → `hypothesis`, `confirmed` → `validated` (zie [onderzoek](../research/2026-11-12-cogniam-model-als-invoer.md) en [het v4-model](../research/2026-11-12-cogniam-v4-metamodel.md)).
- **Gereed als:**
  - de spec bevat de pagina's, het lockformaat, de driftuitvoer en de export;
  - het plan heeft fasen per uitvoersoort.

## §9 MCP-ontsluiting

- **Status:** open · **Hangt af van:** §8
- **Doel:** coding-agents vragen regels op tijdens hun werk.
- **Inhoud:**
  - Vragen als:
    - "regels voor begrip X";
    - "regels in bestand Y";
    - "testspecificaties voor regel Z".
  - De tool leest het contract en doet geen LLM-aanroep.
  - Registratie via `register_tool` (`mcp_server/tools.py:294`).
  - Geen `print()` in MCP-code (AGENTS.md).
- **Te beslissen:**
  - één tool met filters, of meerdere tools;
  - hoe de server het contract vindt;
  - hoe een verouderd model wordt gemeld.
- **Gereed als:**
  - de spec bevat de toolschema's, voorbeeldantwoorden en het gedrag zonder model;
  - het plan heeft één fase.

## §10 Evaluatie: goudmodel en meetrun

- **Status:** open · **Hangt af van:** §1. Mag starten zodra de contractvorm in de §1-spec vastligt en loopt daarna parallel.
- **Doel:** meten of de feature werkt.
- **Inhoud:**
  - Goudmodel (B9, B10): de praktijkcasus Micromundo, rechtstreeks uit het CogNIAM-boek opgebouwd. De bronnen zijn:
    - hoofdstuk 14, §14.1 tot en met §14.4 (casustekst en 18 bedrijfsregels, a tot en met r);
    - hoofdstuk 15 (notatie);
    - bijlage B (begrippenlijst), C (regelgevingdiagram) en D (gestructureerd Nederlands).
    De OCR van het boek is niet gecorrigeerd, dus elk item krijgt een paginabron en wordt tegen de scan gecontroleerd. Melly heeft al een afgeleid register en dossier van deze casus. Die zijn volgens B10 geen bron.
  - Een referentie-implementatie van Micromundo in de stacks van B3, verdeeld over minstens twee repositories (B4). Code die het model implementeert, bestaat nog niet.
  - Precisie en recall per elementsoort, alleen over de items die de referentie-implementatie echt bevat. Items die alleen in het modelbestand staan, testen de as gepland/gerealiseerd van U1.
  - Eén providerrun, alleen met toestemming van de gebruiker.
- **Te beslissen:**
  - de verdeling over repositories. De casus vormt één samenhangend vocabulaire, dus een splitsing per deelgebied is kunstmatig. Een splitsing per laag ligt meer voor de hand, bijvoorbeeld een Laravel-backend voor aanvraag, lening en aflossing (met migraties) en een TypeScript/Node-service voor investeerders of betalingen;
  - Nederlandse of Engelse domeinnamen in de referentiecode. Bij Engelse namen heeft de meting een koppeltabel naar de Nederlandse namen uit het boek nodig;
  - waar het goudmodel en de referentiecode staan. Het boek heeft geen licentievermelding, en het goudmodel bevat begrippen en regels uit het boek. Advies: zet ze niet in de publieke ChunkHound-repository, maar in een privérepository. Neem in ChunkHound alleen het meetscript en de scores op, plus een eigen samenvatting met verwijzing naar het boek;
  - de omvang: de hele casus of een deel. Een deel is genoeg, als elke elementsoort van §1 erin voorkomt;
  - het meetscript, bijvoorbeeld naar het voorbeeld van `make bench-cluster`.
- **Gereed als:**
  - het goudmodel staat in het contractformaat;
  - er is een meetopdracht;
  - het meetplan is goedgekeurd.

---

## Buiten scope (voor nu)

- Koppeling aan wetgeving en beleid. Kan alleen als die documenten mee geïndexeerd zijn; later.
- Testcode genereren in doelrepositories (U7).
- Grafische feittypediagrammen in ORM-notatie.
- Een webinterface voor menselijke invoer (B6). Die volgt later en leest en schrijft hetzelfde modelbestand. Het is nog niet besloten of dat een eigen interface wordt of de browser van de COGNiam-toolkit.
- Een lezer voor het COGNiam-dossier (`.cogniam/`, alleen-lezen) als tweede bron (B6).
- Het COGNiam-dossier als bron van waarheid waartegen de code wordt getoetst.

## Handoff-opdracht per sectie

Start een nieuwe sessie voor sectie N met:

> Lees `AGENTS.md`, `docs/melly/plans/2026-11-12-cogniam-routekaart.md` (Werkwijze, Uitgangspunten, §N) en `docs/melly/decisions/2026-11-12-cogniam-model.md`. Werk alleen §N uit, van de huidige status tot *gereed*. Stel alleen onbesliste, materiële ontwerpvragen, één per beurt, in het Nederlands, en leg elk antwoord vast in het besluitenlog. Schrijf daarna de spec en het plan op de paden uit de Werkwijze en werk de statustabel bij. Begin niet met implementatie.
