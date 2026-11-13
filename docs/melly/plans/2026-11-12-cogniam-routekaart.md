# Routekaart: Cogniam-kennismodel uit code

- Datum: 2026-11-12 · Basis: `main` op `f89044d9` · Branch: `worktree-cogniam-plan`
- **Status:** concept. §0 en §1 zijn gereed. De gebruiker keurde de spec en het plan van §1 op 2026-11-13 goed, na B11 tot en met B25. §1 is geïmplementeerd volgens het [plan](2026-11-13-cogniam-1.md), op de branch `cogniam1/integration` (draft-PR #30 op de fork). §2 is in ontwerp (B26, B27). Deze routekaart zelf geeft geen toestemming voor implementatie, providerruns of een push naar `main`.
- Besluitenlog: [2026-11-12-cogniam-model.md](../decisions/2026-11-12-cogniam-model.md)

## Doel

ChunkHound leidt uit één of meer codebases een Cogniam-kennismodel af. Het model volgt de zeven kennisklassen van het CogNIAM-boek (B11): begripsomschrijvingen, invulplaatsen, zinsjablonen (feittypen), validatieregels, afleidingsregels, uitwisselingsregels en eventregels, plus voorbeeldfeiten. Elk element heeft een bronverwijzing.

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
| 1 | Metamodel en contract | 0 | gereed | [spec](../specs/2026-11-13-cogniam-1-design.md) | [plan](2026-11-13-cogniam-1.md) |
| 2 | Vaste structuurextractie | 1 | ontwerp | – | – |
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
- §9 (MCP) als laatste. De MCP-tools voor het schrijven (B17) en lezen (B24) van menselijke invoer komen wel in versie 1, als onderdeel van §1.

## Uitgangspunten (bevestigd, B7)

- **U1 Concept, geen volledigheid.** Elk element heeft twee eigenschappen.
  - Wie ervoor instaat: `extracted` (vast afgeleid), `proposed` (LLM) of `confirmed` (mens). Alleen een mens zet `confirmed`. Via Claude Code geldt een opdracht van de mens als bevestiging; de agent schrijft die, en niets controleert dat een mens echt bevestigde (B19).
  - Of het in de code is gevonden: *gepland* (alleen als menselijke invoer in de database, B15) of *gerealiseerd* (met een citatie uit code).
- **U2 Geen element zonder bron.** Elk element heeft minstens één bron: een citatie uit code (repository, pad, regelbereik en commit), of een record met menselijke invoer in de database van ChunkHound (B15). Zo'n record heeft een auteur (de Git-identiteit van de machine), een tijdstip en een ingang (B18). Gewijzigd door B15; volgens B7 was dit een regel in het modelbestand, met de auteur uit Git.
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
  - B6: een mens geeft invoer via Claude Code, later ook via een webinterface. Het model is in versie 1 ook invoer: geplande feittypen en regels staan in een modelbestand in de repository. ChunkHound leest dat bestand als bron en schrijft er nooit in. Een element uit dat bestand zonder citatie uit code is *gepland*, met zo'n citatie *gerealiseerd*. Dat werkt net als `documented` tegenover `found` bij C4. Een lezer voor het COGNiam-dossier (`.cogniam/`) komt na versie 1. Onderbouwing: [onderzoek](../research/2026-11-12-cogniam-model-als-invoer.md). **Gewijzigd door B15:** er is geen modelbestand. De menselijke invoer staat in de database van ChunkHound, en ChunkHound schrijft haar zelf, in opdracht van Claude Code. Gepland tegenover gerealiseerd blijft gelden.
  - B8: de opdracht heet `chunkhound domain <hoofdmap>`, de module `chunkhound/domain_model/`. Code, JSON-sleutels en CLI-uitvoer zijn Engels, en de docs krijgen een woordenlijst Nederlands–Engels. "CogNIAM" komt alleen voor in de docs en in de latere export naar het dossier.
  - B9: het goudmodel voor §10 is de praktijkcasus Micromundo uit het CogNIAM-boek (microleningen). Code voor Micromundo bestaat nog niet. §10 schrijft daarom een referentie-implementatie, verdeeld over minstens twee repositories.
  - B10: alleen het CogNIAM-boek bepaalt de methodiek. melly en melly-slim zijn geen voorbeeld voor het metamodel, het goudmodel of de conventies. Het v4-dossier telt alleen voor de latere export en de dossierlezer.
- **Te beslissen:**
  1. ~~Eerste afnemer~~ (besloten, B2).
  2. ~~Eerste talen en frameworks~~ (besloten, B3).
  3. ~~Meerdere repositories in versie 1~~ (besloten, B4). ~~Referentiecodebases voor §10~~ (besloten, B9: Micromundo; de verdere uitwerking staat in §10).
  4. ~~CLI-vorm~~ (besloten, B5: eigen opdracht).
  5. ~~Model als invoer in versie 1~~ (besloten, B6: beperkt; dossierlezer later. B15: de invoer staat in de database, niet in een modelbestand).
  6. ~~Bevestiging van U1 tot en met U8~~ (besloten, B7).
  7. ~~Naamgeving in code en uitvoer~~ (besloten, B8: `chunkhound domain`, Engelse termen).
- **Gereed als:** de besluiten staan in het log en deze routekaart is bijgewerkt: scope, volgorde en de vragen per sectie. §0 krijgt geen spec en geen plan.

## §1 Metamodel en contract

- **Status:** gereed, goedgekeurd op 2026-11-13 (review verwerkt in B24 en B25): [spec](../specs/2026-11-13-cogniam-1-design.md) en [plan](2026-11-13-cogniam-1.md) · **Hangt af van:** §0
- **Doel:** de datavorm van het kennismodel. Alle andere secties bouwen hierop.
- **Basis (B10):** het metamodel volgt het CogNIAM-boek, zie het [onderzoek naar het metamodel in het boek](../research/2026-11-12-cogniam-boek-metamodel.md): zeven kennisklassen (BO, VAR, ZS, VR, AR, UR, ER) plus de feiten op niveau I. Het [onderzoek naar het v4-dossiermodel](../research/2026-11-12-cogniam-v4-metamodel.md) is geen voorbeeld voor §1. Het is alleen achtergrond voor de export in §8.
- **Praktijkvoorbeeld (B11):** de [CEM-werkwijze van de gebruiker](../research/2026-11-12-cem-werkwijze.md) laat zien hoe de methode op software landt:
  - een invulplaats in een zinsjabloon draagt de naam van een veld in de code;
  - een samengesteld feittype is één tabel;
  - "bestaande tabel" tegenover een nieuwe tabel is *gerealiseerd* tegenover *gepland*;
  - de validatieregels zijn uniciteit, deelverzameling, waardenregel, verplichte rol en datatype, genummerd in blokken per soort;
  - populaties met varianten toetsen de regels.
- **Besloten:**
  - B11: de elementsoorten zijn de zeven kennisklassen plus voorbeeldfeiten, met de namen uit het boek. Kennisgebied is geen element. Governance, processen, beslissingen en berichten komen niet in versie 1.
  - B12: een invulplaats heet naar het begrip (de rol) en is uniek binnen haar sjabloon. De koppeling naar het codeveld staat apart, per repository en met citatie. Een gepland element heeft nog geen koppeling.
  - B13: elke validatieregel is een eigen element met een eigen id. Verplicht en datatype zijn kenmerken van de invulplaats. §7 test ze toch, met een afgeleid id.
  - B14: een feittype mag zonder voorbeeldfeit, behalve als een mens het op `confirmed` zet. §6 meldt een feittype zonder voorbeeldfeit als waarschuwing.
  - B15: menselijke invoer (geplande elementen, voorbeeldfeiten, bevestigingen en correcties) staat in de database van ChunkHound. Claude Code schrijft haar via ChunkHound. Er is geen modelbestand en geen curatiebestand. Dat wijzigt B6 en U2.
  - B16: die invoer staat in eigen tabellen in de index-database (`.chunkhound/db`), niet in een apart bestand. Compactie en migraties moeten de tabellen meenemen.
  - B17: één schrijfdienst in `chunkhound/domain_model/`, met twee ingangen: een MCP-tool (als de daemon draait) en een CLI-opdracht (zonder daemon: CI, scripts, §10). Draait de daemon wel, dan geeft de CLI de bestaande lockmelding.
  - B18: elk record met menselijke invoer krijgt een auteur, een tijdstip en de ingang. De auteur is de Git-identiteit van de machine (`user.name`, `user.email`), anders de gebruikersnaam van het besturingssysteem. Een agent kan de auteur niet invullen.
  - B19: de schrijftool accepteert ook `confirmed`; een opdracht van de mens in Claude Code geldt als bevestiging. De schrijfdienst controleert wel B14 (minstens één voorbeeldfeit).
  - B20: versie 1 heeft geen export en geen import van menselijke invoer. De gebruiker maakt zelf een back-up van `.chunkhound/db`. In CI is er geen menselijke invoer.
  - B21: het id is een sleutel uit soort, repository en naam, zoals bij C4, bijvoorbeeld `fact_type:backend/role-assignment`. Met de termen van B22 begint het id van een regel met `validation_rule:`; hoe de soort regel (zoals uniciteit) in de sleutel komt, volgt in de spec. Het is overal gelijk en komt in testnamen. Een hernoeming geeft een nieuw id, en §4 herkent dat als hernoeming. Een nummer per soort als label kan later bij de export.
  - B22: de Engelse termen komen uit de CogNIAM-literatuur; zie de woordenlijst hieronder.
  - B23: geen veld `level` (kennisdriehoek); gepland of gerealiseerd wordt afgeleid uit citaties; `CHECKPOINT` na elke schrijfactie met menselijke invoer; menselijke invoer in versie 1 alleen op DuckDB.
  - B24: naast `domain_write` komt de MCP-leestool `domain_read`, met dezelfde uitvoer als `chunkhound domain --list-input`. Zo kent een agent de bestaande id's terwijl de daemon de database op slot heeft.
  - B25: vier voorstellen uit de spec zijn aanvaard. Een feittype heeft een lijst `templates` (wijzigt B22). De CLI geeft bij een draaiende daemon een eigen lockmelding (wijzigt B17). Een niet-geplaatst gepland element krijgt de sleutel `root` (vult B21 in). Bevestigen van een feittype bevestigt ook de rollen, en voor B14 tellen alleen geldige voorbeeldfeiten uit de menselijke invoer.
  - B26 (uit §2, nog niet geïmplementeerd): de sjabloonregel wordt verruimd. Een sjabloon mag een deel van de rollen bevatten, en alle sjablonen van een feittype dekken samen alle rollen. De sjablonen zijn dan deelzinnen, geen synoniemen van één hoofdsjabloon (wijzigt B25, punt 1). De wijziging komt als fase in het plan van §2.
- **Woordenlijst (B8, B22):**

  | Boek (Nederlands) | Code en JSON |
  |---|---|
  | begripsomschrijving (BO) | `concept`, met `definition` |
  | variabele of invulplaats (VAR) | `role` |
  | zinsjabloon (ZS) | `fact_type`, met `templates`: een lijst (B25). Na B26 is elk sjabloon een deelzin over een deel van de rollen |
  | validatieregel (VR) | `validation_rule` |
  | afleidingsregel (AR) | `derivation_rule` |
  | uitwisselingsregel (UR) | `exchange_rule` |
  | eventregel (ER) | `event_rule` |
  | voorbeeldfeit (niveau I) | `ground_fact` |

  De Engelse Wikipedia-pagina over CogNIAM deelt de zeven categorieën anders in dan het boek (onder meer *process descriptions*, *actors* en *services*). De indeling volgt het boek (B10, B11); alleen de Engelse woorden komen uit de literatuur.
- **Inhoud:**
  - Elementsoorten (B11):
    - begripsomschrijving (BO): term, meervoud, definitie, synoniemen;
    - variabele of invulplaats (VAR): een rol in een feittype, met begrip, datatype en koppeling naar een codeveld;
    - zinsjabloon (ZS): het feittype met zijn invulplaatsen, en het identificerende sjabloon van een objecttype;
    - validatieregel (VR): onder meer uniciteit, deelverzameling, waardenregel en verplichte rol;
    - afleidingsregel (AR);
    - uitwisselingsregel (UR): hoe feiten worden toegevoegd, gewijzigd of verwijderd;
    - eventregel (ER): wanneer een uitwisselings- of afleidingsregel start;
    - voorbeeldfeit (niveau I): de populatie van een feittype.
  - Geen eigen elementsoort, maar eigenschappen van elk element:
    - citaties (repository, pad, regelbereik, commit);
    - de twee assen van U1.
  - Stabiele identiteiten tussen runs. Les uit C4: bestandsnamen en URL's zijn geen stabiele identiteit.
  - Een JSON-contract met schemaversie, en een lader die de vorm bepaalt (patroon `autodoc/architecture/loader.py`).
  - Opslag van menselijke invoer in de database (B15), met schrijfopdrachten die de invoer controleren.
- **Te beslissen:**
  - ~~welke elementsoorten~~ (besloten, B11);
  - ~~vorm van een zinsjabloon~~ (besloten, B12: invulplaats naar het begrip, koppeling naar het codeveld apart);
  - ~~granulariteit~~ (besloten, B13: één element per validatieregel; verplicht en datatype als kenmerk);
  - ~~zijn voorbeeldfeiten verplicht~~ (besloten, B14: alleen bij `confirmed`);
  - ~~vorm van het id~~ (besloten, B21: sleutel uit soort, repository en naam). Voor de spec blijft open: welke repository een gepland element in zijn id krijgt als nog niet vaststaat waar het komt, en hoe de sleutel van elke elementsoort precies is opgebouwd;
  - ~~hoe de niveaus van de kennisdriehoek in het model terugkomen~~ (besloten, B23), volgens het boek (p.5, figuur 1.1):
    - niveau I zijn de voorbeeldfeiten;
    - niveau II zijn de elementen van het model;
    - niveau III, de generieke regelgeving ("van een feittype wordt genoteerd welke variabele op welke positie staat"), is het schema van het contract met de controles van de lader en §6.

    Er komt dus geen veld `level` per element;
  - ~~het modelbestand voor menselijke invoer~~ (besloten, B15: geen bestand; de invoer staat in de database). Daaruit volgen deze vragen:
    - ~~**Waar in de database**~~ (besloten, B16: eigen tabellen in de index-database). De spec moet deze bevindingen in de code oplossen:
      - De compactie gooit onbekende tabellen weg, met opzet. Dat geldt voor de Python-route (`chunkhound/providers/database/duckdb_provider.py:1217`, `_compact_copy_data`) en voor de Rust-route (`src/db/duckdb_backend/compaction.rs:23`). Die kopiëren alleen `schema_version`, `files`, `chunks` en `embeddings_*`. Beide moeten de nieuwe tabellen meekopiëren, met een test die bewijst dat menselijke invoer een compactie overleeft. Voor de Rust-wijziging gelden de `RUST_RULES` uit `AGENTS.md`.
      - Compactie draait ook vanzelf: na een schrijfactie start ze met een kans van 1 op 100 (`chunkhound/providers/database/serial_executor.py:49` en `:106`). Zonder die wijziging gaat menselijke invoer dus bij gewoon indexeren verloren.
      - Bij het openen verwijdert ChunkHound een WAL-bestand dat ouder is dan 24 uur (`duckdb_provider.py:530`). Besloten (B23): na elke schrijfactie met menselijke invoer volgt een `CHECKPOINT`.
      - De nieuwe tabellen krijgen een migratie via `schema_version`.
      - ChunkHound heeft een tweede backend, LanceDB (`chunkhound/providers/database/lancedb_provider.py`). Besloten (B23): versie 1 ondersteunt menselijke invoer alleen op DuckDB, de standaard. Op LanceDB meldt `chunkhound domain` dat duidelijk.
      - `--force-reindex` laat de database staan (`chunkhound/pipeline_bridge.py:890`). Alleen wie `.chunkhound/` weggooit, verliest de invoer; daar is in versie 1 geen export voor (B20).
    - ~~**Schrijfroute**~~ (besloten, B17: een MCP-tool én een CLI-opdracht op één schrijfdienst). Achtergrond: Claude Code schrijft via een CLI-opdracht of een MCP-tool. Een draaiende daemon (MCP) houdt de exclusieve lock op de index-database, en de CLI weigert dan (`chunkhound/api/cli/commands/run.py:134`, `_handle_daemon_lock_conflict`). Dat geldt vandaag ook voor `map`, dat de database zelf opent (`chunkhound/api/cli/commands/code_mapper.py:499`). Geen CLI-opdracht stuurt werk door naar de daemon. De daemon spreekt MCP over een socket (`chunkhound/daemon/server.py:305`). MCP komt volgens B2 als laatste (§9).
    - **Controle bij het schrijven** (eis voor de spec, geen keuze). Een schema dat een agent kan lezen, en precieze foutmeldingen waarmee de agent zichzelf kan verbeteren.
    - ~~**Auteur en tijdstip** per record (U2)~~ (besloten, B18: de Git-identiteit van de machine, met tijdstip en ingang).
    - ~~**Wie `confirmed` zet**~~ (besloten, B19: één schrijftool; een opdracht van de mens in Claude Code geldt als bevestiging). Achtergrond: volgens U1 zet alleen een mens `confirmed`. Via de MCP-tool (B17) schrijft echter een agent. Hoe blijkt dat een mens bevestigde? Tijdens een Claude Code-sessie draait de daemon, dus bevestigen alleen via de CLI kan dan niet.
    - ~~**Delen en back-up**~~ (besloten, B20: geen export of import in versie 1; de gebruiker maakt zelf een back-up van `.chunkhound/db`);
  - ~~twee assen per element~~ (besloten, B23: wie ervoor instaat wordt opgeslagen; gepland of gerealiseerd wordt afgeleid uit de citaties uit code);
  - ~~de Engelse termen en de woordenlijst Nederlands–Engels~~ (besloten, B22; zie de woordenlijst).
- **Gereed als:**
  - de spec bevat dataclasses, een JSON-voorbeeld, identiteitsregels en laadfouten;
  - de spec bevat ook de opslag van menselijke invoer (B15): de tabellen, de schrijfopdrachten met een voorbeeld en hun foutmeldingen, en hoe de invoer compactie, herindexering en upgrades overleeft;
  - het plan heeft fasen voor model, lader, opslag van menselijke invoer en contracttests.

## §2 Vaste structuurextractie

- **Status:** ontwerp · **Hangt af van:** §1
- **Doel:** kandidaat-feittypen, invulplaatsen en validatieregels zonder LLM afleiden uit schema's en modellen.
- **Besloten:**
  - B26: een tabel of model wordt één samengesteld feittype, met één rol per kolom (genoemd naar het begrip, met een koppeling naar de kolom).
    - Sjablonen: per kolom één sjabloon met de sleutelrollen plus die rol, en één identificerend sjabloon met alleen de sleutelrollen, zoals bijlage C van het boek. §2 stelt ze mechanisch op; §3 maakt er zinnen van.
    - Regels: uniciteit (ook over meerdere kolommen), deelverzameling en waardenregel hangen aan het samengestelde feittype. Verplicht en datatype zijn kenmerken van de rol (B13).
    - Gevolg voor §1: de sjabloonregel wordt verruimd (een sjabloon bevat een deel van de rollen; samen dekken ze alle rollen). Dat is achterwaarts verenigbaar en wordt een kleine fase in het plan van §2.
    - Voor de spec: waar het identificerende sjabloon en `identifies` staan, en de volgorde van de sjablonen.
  - B27: §2 leest van uitwisselingsregels alleen de structuur, als ankers. §2 maakt zelf geen uitwisselingsregels; dat doet §3 per anker.
    - Een anker is één ingang (route, endpoint of command) met methode, pad, handler, bestand en regels.
    - Per anker komen de vast leesbare aanwijzingen mee: de HTTP-methode, de `FormRequest` en de modellen in de signatuur. Voor §3 zijn dat hints.
    - Bronnen: Laravel `routes/*.php` en commands, Magento `etc/webapi.xml` en `routes.xml`, en voor TypeScript de frameworks uit de vraag over TypeScript hieronder.
    - Voor de spec: de opslagvorm van ankers (een anker is geen §1-element), de markering "niet opgelost" bij dynamische registratie, en fixtures die de lijst toetsen.
- **Gevolg van B11:**
  - Uitwisselingsregels horen bij versie 1. Routes, controllers, endpoints en commands zijn daarvoor de bronnen. §2 leest hun structuur als ankers en §3 maakt de regels (B27).
  - De CEM-werkwijze ([onderzoek](../research/2026-11-12-cem-werkwijze.md)) laat zien wat vast te lezen is: uniciteit, deelverzameling (*foreign key*), waardenregel, verplichte rol en datatype. Vaste waarden in de code zijn kandidaten voor een waardenregel.
- **Bronnen per stack (B3):**

  | Stack | Feittypen | Validatieregels | Ook nuttig voor |
  |---|---|---|---|
  | SQL | `CREATE TABLE`, kolommen | `PRIMARY KEY`, `UNIQUE`, `NOT NULL`, `FOREIGN KEY`, `CHECK` | – |
  | Laravel | Migraties (`Schema::create`, Blueprint-kolommen), Eloquent-modellen en relaties (`hasMany`, `belongsTo`) | Blueprint-modifiers (`->unique()`, `->nullable()`, `->foreign()`), validatieregels in `FormRequest::rules()` en `Validator::make` (`required\|email\|unique:users`), PHP-enums | §7: validatieregels zijn direct bruikbaar als testgevallen |
  | TypeScript/Node | Prisma-schema, TypeORM-entities | Opties in `@Column({ unique, nullable })`, Zod-schema's (`z.string().min(1)`), enums en literal-uniontypes | – |
  | Magento 2 | `etc/db_schema.xml` (declaratief schema), EAV-attributen in data patches (`Setup/Patch/Data/*.php`, `EavSetup::addAttribute`), service contracts (`Api/Data/*Interface.php`) | `nullable`, `length` en constraints in `db_schema.xml`; `required` en `unique` bij EAV-attributen; source models als waardebeperking; validatie in `ui_component/*.xml` | §3: `etc/events.xml` en observers voor eventregels. §5: `etc/webapi.xml` als servicegrens |

- **Bevinding (2026-11-12):**
  - `.xml` wordt als platte tekst geïndexeerd (`chunkhound/core/types/common.py:339`).
  - `.prisma` staat niet in de extensielijst en wordt dus niet geïndexeerd.
  - Gevolg: §2 kan niet op de geïndexeerde chunks bouwen. Het leest de bronbestanden zelf:
    - XML met een veilige XML-parser, zonder externe entiteiten;
    - PHP en TypeScript met de tree-sitter-grammatica's die al meegeleverd worden;
    - Prisma met een eigen kleine parser, of als tekst voor §3.
- **Bevinding (2026-11-13), hergebruik:**
  - De C4-kaart en de research herkennen geen frameworks, routes, controllers of commands. Een zoektocht op Laravel, Magento, Eloquent, Prisma en NestJS in `chunkhound/` en `src/` gaf geen treffers.
  - Een losse aanroep zoals `Route::post(...)` wordt waarschijnlijk geen eigen chunk. Ook daarom leest §2 de bestanden zelf, zoals de statische scan van de C4-kaart doet.
  - De SQL-mapping telt alleen het aantal kolommen; kolomnamen, typen en constraints leest ze niet.
  - De enige XML-parser is die voor TwinCAT (`chunkhound/parsers/twincat/xml_extractor.py`), op de standaardbibliotheek en zonder beveiliging tegen kwaadaardige XML.
  - Niet getest: of `SourceInspector` de vormen in een Laravel-routebestand goed afhandelt. Dat hoort bij de fixtures in de spec.
- **Uitgangspunt:**
  - de mappings `chunkhound/parsers/mappings/sql.py`, `php.py` en `typescript.py` (de laatste heeft `extract_decorators`, bruikbaar voor NestJS);
  - bestandsselectie met gitignore en uitsluitingen: `list_scope_files` (`chunkhound/code_mapper/c4/files.py`) en `collect_scope_files` (`chunkhound/code_mapper/scope.py`);
  - bron lezen met hash en regels, binnen de projectmap: `read_source` (`chunkhound/services/extraction/sources.py`);
  - syntaxboom en queries per taal: `ParserFactory` (`chunkhound/parsers/parser_factory.py`) en `TreeSitterEngine.parse_to_ast` en `compile_query` (`chunkhound/parsers/universal_engine.py`);
  - aanroepen, basisklassen en symbolen met parameters: `SourceInspector` (`chunkhound/code_mapper/c4/codeboarding/source_inspector.py`), gebruikt door `_scan_references` (`chunkhound/code_mapper/c4/references.py`) voor Python, JS/TS en PHP;
  - een klasse naar een bestand herleiden: `ImportResolverService` (`chunkhound/services/research/shared/import_resolver.py`);
  - het framework vaststellen uit afhankelijkheden: `scan_runtime` (`chunkhound/code_mapper/c4/runtime.py`) leest `composer.json` en `package.json` al;
  - overslaan wat niet veranderd is: `source_manifest_version` (`chunkhound/services/extraction/dev_cache.py`).
- **Te beslissen:**
  - ~~hoe een tabel naar feittypen vertaalt~~ (besloten, B26: één samengesteld feittype per tabel);
  - ~~of §2 de structuur van uitwisselingsregels vast leest~~ (besloten, B27: §2 levert ankers, §3 maakt de regels);
  - Magento: alleen eigen modules (`app/code`) of ook kernmodules en modules van derden in `vendor/`;
  - Magento EAV: wordt elk attribuut een eigen feittype, of komt er één generiek feittype "entiteit heeft attribuutwaarde";
  - TypeScript: welke ORM en welke validatiebibliotheken eerst (Prisma, TypeORM, Zod, class-validator);
  - wat te doen als bronnen elkaar tegenspreken, bijvoorbeeld een migratie tegenover een model of `FormRequest`;
  - de volgorde van migraties: welke migratie geeft de huidige toestand (ook bij `dropColumn` en hernoemingen);
  - hoe technische tabellen worden herkend: migratieadministratie, jobs, caches, sessies, Magento-indexers. De uitsluiting zelf gebeurt in §4.
- **Gereed als:**
  - de spec bevat per brontype de vertaling naar §1-elementen, met fixtures;
  - het plan heeft één fase per brontype, ook voor de ankers (B27), plus een fase die de sjabloonregel van §1 verruimt (B26).

## §3 LLM-extractie

- **Status:** open · **Hangt af van:** §1, en §2 voor ankers
- **Doel:** extraheren wat niet vast af te leiden is:
  - begrippen en definities;
  - zinsjablonen;
  - afleidingsregels;
  - uitwisselingsregels, per anker uit §2 (B27);
  - eventregels;
  - voorbeeldfeiten uit tests en documentatie.
- **Gevolg van B26:** §2 levert per feittype mechanische sjablonen, één per kolom plus een identificerend sjabloon. §3 stelt per sjabloon een echte zin voor; de rollen van het sjabloon blijven gelijk.
- **Gevolg van B27:** §2 levert de lijst van ingangen als ankers, met aanwijzingen. §3 maakt per anker de uitwisselingsregel (naam, zin, bewerkingen, feittypen) en gebruikt de aanwijzingen als hint. Voor de spec: of elke ingang een regel of de markering "geen domeinuitwisseling" krijgt, zodat dekking meetbaar is.
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
  - hoe menselijke correcties (bevestigd, verworpen, samengevoegd) in de database staan (B15), zodat ze een nieuwe run overleven, ook als de gevonden elementen een andere vorm krijgen;
  - of een bevestiging een oordeel blijft over een gevonden element, of het element als menselijke invoer opslaat, zodat alle kennis waar een mens voor instaat op één plek staat;
  - hoe een gepland element uit de menselijke invoer wordt gekoppeld aan de code die het later implementeert;
  - hoe een hernoeming wordt herkend, zodat een nieuw id (B21) niet als een verwijderd en een nieuw element telt. Voorbeeld: `detect_renames` in `code_mapper/c4/identity.py:29`.
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
    - een zinsjabloon dekt alle invulplaatsen;
    - een feittype zonder voorbeeldfeit is een waarschuwing (B14). Voorstel: een `confirmed` feittype zonder voorbeeldfeit is een fout; of de lader of §6 dat afdwingt, volgt in de spec;
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
    | Verplichte rol (kenmerk, B13) | Verplichte waarde weglaten, afwijzing verwachten |
    | Waardebeperking | Grenswaarden net binnen en net buiten |
    | Subset en uitsluiting | Verboden combinaties aanbieden |
    | Afleidingsregel | Voorbeeldinvoer met verwachte uitkomst |
    | Uitwisselingsregel | Feit toevoegen, wijzigen of verwijderen, en de populatie daarna controleren |
    | Eventregel | Toegestane en verboden toestandsovergangen |

  - Given/When/Then met concrete data uit voorbeeldfeiten. Een testspecificatie is een concreet voorbeeld met een verwachte uitkomst: geldig, of welke regel het overtreedt. Zo doet het boek het ook (p.234).
  - Ook voor geplande regels (B6): de testspecificatie bestaat voordat de code er is. Geplande regels staan alleen in de lokale database (B15, B16); in CI zijn ze er niet (B20).
  - Voorstel: het id van de regel staat in de testnaam, zodat de dekking per regel te meten is. Voor verplicht en datatype (kenmerken, B13) is dat een afgeleid id: feittype, invulplaats en kenmerk.
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
  - AutoDoc-pagina's: begrippenlijst, feittypen per groep (label, B11), regels, dekking.
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
- **Al in versie 1 (B17, B24):** de schrijftool `domain_write` en de leestool `domain_read` voor menselijke invoer. Die horen bij §1 en wachten niet op §8. §9 gaat over het lezen van het hele model: gevonden en geplande elementen, regels en testspecificaties.
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
  - Precisie en recall per elementsoort, alleen over de items die de referentie-implementatie echt bevat. Items die alleen als menselijke invoer bestaan, testen de as gepland/gerealiseerd van U1. De meting schrijft die items daarom eerst via de schrijfopdrachten van §1 in een lege database (B15).
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
- Een webinterface voor menselijke invoer (B6). Die volgt later en leest en schrijft dezelfde menselijke invoer in de database (B15). Het is nog niet besloten of dat een eigen interface wordt of de browser van de COGNiam-toolkit.
- Een lezer voor het COGNiam-dossier (`.cogniam/`, alleen-lezen) als tweede bron (B6).
- Export en import van menselijke invoer, en het delen ervan met collega's of CI (B20).
- Het COGNiam-dossier als bron van waarheid waartegen de code wordt getoetst.

## Handoff-opdracht per sectie

Start een nieuwe sessie voor sectie N met:

> Lees `AGENTS.md`, `docs/melly/plans/2026-11-12-cogniam-routekaart.md` (Werkwijze, Uitgangspunten, §N) en `docs/melly/decisions/2026-11-12-cogniam-model.md`. Werk alleen §N uit, van de huidige status tot *gereed*. Stel alleen onbesliste, materiële ontwerpvragen, één per beurt, in het Nederlands, en leg elk antwoord vast in het besluitenlog. Schrijf daarna de spec en het plan op de paden uit de Werkwijze en werk de statustabel bij. Begin niet met implementatie.
