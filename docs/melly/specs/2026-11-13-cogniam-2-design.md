# Spec: §2 Vaste structuurextractie

- Datum: 2026-11-13 · Branch: `worktree-cogniam-plan` (HEAD bij start `02d5664a`)
- **Status:** concept, wacht op goedkeuring van de gebruiker. Deze spec geeft geen toestemming voor implementatie, voor een provider-run of voor een push naar `main`.
- Bron: [routekaart §2](../plans/2026-11-12-cogniam-routekaart.md#2-vaste-structuurextractie), besluiten B26 tot en met B33 in het [besluitenlog](../decisions/2026-11-12-cogniam-model.md), en de [spec van §1](2026-11-13-cogniam-1-design.md) voor het contract.
- Aanhaakpunten zijn op `02d5664a` gelezen, niet gedraaid. Uitzondering: de grammaticaproeven in §6.1 zijn wel gedraaid.
- Verwijzingen naar "§1-spec §x" gaan naar de spec van §1. Verwijzingen zonder toevoeging gaan naar deze spec.

## 1. Probleem

Het model van §1 heeft een vorm, maar nog geen inhoud uit code. Een groot deel van die inhoud staat letterlijk in de bron: tabellen, kolommen, sleutels, *foreign keys*, vaste waarden en de lijst van ingangen (routes, endpoints, commands). Dat deel hoort niet door een LLM te gaan (U3): het is goedkoper, herhaalbaar en zonder verzinsels te lezen.

De bestaande onderdelen lezen dit niet. De SQL-mapping telt alleen kolommen (`chunkhound/parsers/mappings/sql.py:232-236`). `.xml` en `.graphql` worden als platte tekst geïndexeerd (`chunkhound/core/types/common.py:337`, `:339`), en `.prisma` en `.graphqls` helemaal niet. Niets in `chunkhound/` herkent een framework, een route of een command.

## 2. Doel en afbakening

**Doel:** één pure functie die een projectmap leest en zonder LLM teruggeeft:
- kandidaat-elementen in de vorm van §1 (begrippen, feittypen, rollen en validatieregels), allemaal met status `extracted`;
- de ingangen van het systeem als ankers, met aanwijzingen voor §3 (B27);
- markeringen en afwijkende uitspraken, zodat §3, §4 en §7 weten wat technisch, van derden, onzeker of niet opgelost is.

**In scope:**
- het uitvoercontract van §2 (§4);
- de vertaling van een tabel naar §1-elementen (§5);
- de lezers per brontype, met fixtures (§6 en §7);
- het samenvoegen van overlappende bronnen (§8);
- de ingang `chunkhound domain <hoofdmap> --extract-structure` (§9);
- de verruiming van de sjabloonregel van §1 (§10, B26);
- tests (§13) en fasering (§14).

**Buiten scope:**
- zinnen, definities, afleidings-, uitwisselings- en eventregels (§3). §2 levert daarvoor alleen ankers en mechanische sjablonen;
- samenvoegen met menselijke invoer, hernoemen, domein en techniek scheiden (§4). §2 markeert alleen;
- koppelen over repositories heen (§5);
- opslaan van de uitvoer, het lockbestand en de dev-cache (§8).

**Invarianten:**
1. **Geen LLM, geen netwerk, geen database.** De extractie leest alleen bestanden en vraagt Git om de commit.
2. **Geen bijwerking (U5).** De extractie schrijft niets. De extensielijst van de index verandert niet: `.prisma` en `.graphqls` worden gelezen, niet geïndexeerd. De uitvoer van `index`, `map` en `autodoc` blijft byte-gelijk.
3. **Deterministisch.** Dezelfde bestanden en dezelfde commit geven byte-gelijke JSON. Er staan geen tijdstippen en geen absolute paden in.
4. **Het modeldeel is geldig volgens §1.** Het doorstaat `parse_model` (`chunkhound/domain_model/loader.py:178`). Elk element heeft status `extracted`, minstens één citatie en geen `human_sources`.
5. **Geen element zonder bron (U2).** Ook elk anker, elke markering en elke afwijkende uitspraak heeft minstens één citatie.
6. **Niets valt stil weg.** Wat §2 herkent maar niet kan volgen, wordt een markering met een citatie (B27, B32). Wat §2 niet herkent, blijft buiten de uitvoer.
7. **§2 raadt niet.** Een naam wordt alleen afgeleid met een regel uit deze spec. Lukt dat niet, dan volgt een markering in plaats van een gok.
8. **§2 kiest niet bij tegenspraak (B31).** De hoogste bron vult het model; wat een lagere bron anders zegt, blijft als afwijkende uitspraak staan.
9. **Lezen blijft binnen de hoofdmap.** Elk bestand gaat door `read_source` (`chunkhound/services/extraction/sources.py:19`), dat paden buiten de hoofdmap weigert.
10. **XML wordt niet uitgevoerd.** De lezer lost geen entiteiten op en haalt niets op (§6.1).
11. **Eén lezer die faalt, stopt de run niet.** Een onleesbaar bestand wordt een markering; de andere lezers gaan door.

## 3. Overzicht

```
bestanden ──► lezers voor opslag ──► schema in het geheugen ──► vertaling (§5) ──┐
          ──► lezers voor modellen en API-vorm ──► uitspraken ──► samenvoegen (§8) ─┼─► StructureExtraction
          ──► lezers voor ankers ──► ankers met aanwijzingen ────────────────────┘
```

- Een **lezer** kent één brontype. Hij leest bestanden en levert bewerkingen op het schema, uitspraken of ankers. Hij maakt zelf geen §1-elementen.
- Het **schema in het geheugen** is de neutrale tussenvorm van alle opslagbronnen: tabellen, kolommen en beperkingen, elk met de plaats in de bron (B32).
- De **vertaling** maakt van het schema de §1-elementen. Zo is de regel uit B26 op één plek geschreven en geldt hij voor elke bron.

Module: `chunkhound/domain_model/structure/`.

| Bestand | Inhoud |
|---|---|
| `contract.py` | De datavormen van §4, `parse_structure` en `dump_structure` |
| `schema.py` | Het schema in het geheugen en zijn bewerkingen (§5.1) |
| `translate.py` | Schema naar §1-elementen (§5), samenvoegen van bronnen (§8) |
| `technical.py` | De lijsten van technische tabellen (§5.8) |
| `anchors.py` | Ankers bouwen en aanwijzingen koppelen (§4.1, §7) |
| `files.py` | Bestandsselectie, repositories en commits (§9.2) |
| `extract.py` | `extract_structure`, de lijst van lezers |
| `readers/*.py` | Eén bestand per lezer (§6, §7) |

## 4. Uitvoercontract

De datavormen zijn pydantic-modellen met `frozen=True` en `extra="forbid"`, net als in §1 (`chunkhound/domain_model/model.py:16-17`). Het contract van §1 blijft ongewijzigd, op de sjabloonregel na (§10). Alles wat geen §1-element is, staat ernaast.

```python
STRUCTURE_SCHEMA_VERSION = 1

class RepositoryRef(BaseModel):
    key: str                 # repositorysleutel (§1-spec §6.1)
    path: str                # pad relatief aan de hoofdmap, "." voor de hoofdmap
    commit: str              # HEAD van deze repository, volledig
    dirty: bool              # een gelezen bestand wijkt af van die commit

class Handler(BaseModel):
    symbol: str              # zoals in de bron, bijvoorbeeld "App\\Http\\Controllers\\TeamMemberController@store"
    citation: Citation | None   # de regels van de handler; None als het bestand niet gevonden is

class Hint(BaseModel):
    kind: Literal["operation", "model", "input_type", "input_rule", "enum"]
    name: str | None         # veldnaam, klassenaam of typenaam
    value: str | None        # zoals in de bron
    values: tuple[str, ...]  # alleen bij "enum"
    fact_type: str | None    # feittype-id als de aanwijzing aan een feittype te koppelen is
    role: str | None         # rol-id als de veldnaam met een rol overeenkomt (B31)
    citation: Citation

class Anchor(BaseModel):
    id: str                  # §4.1
    repository: str
    kind: Literal["http", "graphql", "command", "action"]
    method: str | None       # http: GET, POST, …; graphql: query, mutation, subscription
    path: str                # http: het pad; graphql: "Mutation.addTeamMember"; command: de naam
    handler: Handler | None
    source: str              # naam van de lezer, bijvoorbeeld "laravel_routes"
    citations: tuple[Citation, ...]   # de plaats van de registratie, minstens één
    hints: tuple[Hint, ...]

class Finding(BaseModel):
    kind: Literal["technical", "third_party", "uncertain", "unresolved", "external_reference"]
    subject: str | None      # id van een element of anker; None als er niets gemaakt kon worden
    reason: str              # vaste code (§4.2)
    detail: str | None       # naam, pakket of verwijzing, zoals in de bron
    citations: tuple[Citation, ...]   # minstens één

class DivergentClaim(BaseModel):
    subject: str             # rol-id of regel-id waar de uitspraak over gaat
    property: Literal["mandatory", "allowed_values", "superset"]
    value: str | bool | tuple[str, ...]
    source: str              # naam van de lezer
    citation: Citation

class StructureExtraction(BaseModel):
    schema_version: Literal[1]
    repositories: tuple[RepositoryRef, ...]
    model: DomainModel       # alleen concepts, fact_types, roles en validation_rules zijn gevuld
    anchors: tuple[Anchor, ...]
    findings: tuple[Finding, ...]
    divergent_claims: tuple[DivergentClaim, ...]
```

`dump_structure` schrijft `model` met `dump_model` (`loader.py:460`) en de rest met dezelfde regels: vaste sleutelvolgorde, `ensure_ascii=False`, `indent=2` en een regeleinde aan het eind. De lijsten staan gesorteerd: `repositories` op `key`, `anchors` op `id`, `findings` op `(kind, subject, reason, detail, eerste citatie)` en `divergent_claims` op `(subject, property, source, citation)`. `parse_structure` controleert daarnaast dat elk `subject`, elke `fact_type` en elke `role` in een aanwijzing naar een bestaand element of anker wijst.

### 4.1 Id van een anker

`anchor:<repo>/<kind>/<slug>-<hash>`

- `<slug>` is `key_segment(method + " " + path)` (`chunkhound/domain_model/identity.py:22`), zonder `method` als die ontbreekt.
- `<hash>` bestaat uit de eerste 8 hex-tekens van SHA-256 over `method + " " + path`, precies zoals in de bron.
- Voorbeeld: `POST /teams/{team}/members` in `backend` wordt `anchor:backend/http/post-teams-team-members-<hash>`.

De hash is nodig omdat `key_segment` de `/` weghaalt: `/a/b` en `/a-b` zouden anders hetzelfde id krijgen. Het id hangt niet van andere ankers af, dus het blijft gelijk als er een route bijkomt. Staat dezelfde ingang twee keer in de bron, dan is er één anker met twee citaties.

### 4.2 Markeringen (B33: één vorm)

| `kind` | Betekenis | `subject` | `reason` (vaste codes) |
|---|---|---|---|
| `technical` | Het feittype is techniek, geen domein (B33, U4). §4 sluit uit. | feittype | `framework_table` (met in `detail` de lijst, zoals `laravel`), `configured` |
| `third_party` | Het element komt alleen uit code van derden (B28). | element | `vendor_table_extended`, `vendor_table_referenced`; `detail` is pakket en versie |
| `uncertain` | §2 kon de bron niet volledig volgen; de inhoud kan afwijken (B32). | feittype | `raw_sql`, `conditional_schema`, `unknown_schema_call`, `unparsed_statement`, `table_created_twice`, `entity_table_missing`, `column_only_in_lower_source` |
| `unresolved` | §2 herkende iets, maar kon het niet afmaken (B27). | anker, element of `None` | `dynamic_registration`, `handler_not_found`, `non_literal_argument`, `model_table_unknown`, `key_collision`, `unreadable_source`, `source_too_large`, `vendor_missing` |
| `external_reference` | Een verwijzing naar een tabel zonder feittype (B28). | feittype | `table_not_found`, `vendor_not_followed`; `detail` is `"(kolommen) -> tabel(kolommen)"` |

Regels:
- `technical` en `uncertain` staan op het feittype en gelden voor zijn rollen en regels.
- `third_party` staat per element, op elk element waarvan alle citaties in `vendor/` liggen. Een rol die een eigen module aan een kerntabel toevoegt, krijgt de markering dus niet, het feittype zelf wel.
- Een verwijzing naar buiten kan geen `subset`-regel zijn, want die zou in de lader `dangling_reference` geven (`loader.py:249-250`). Daarom is ze een markering.
- Een nieuwe `reason` toevoegen vraagt geen nieuwe versie; een nieuwe `kind` wel.

### 4.3 Afwijkende uitspraken (B31)

Een lagere bron die iets anders zegt dan de bron die het model vult, kan niet in het model staan: de plek is bezet. Twee `value`-regels op dezelfde rol hebben bijvoorbeeld hetzelfde id (§1-spec §6.2). De uitspraak blijft daarom als `DivergentClaim` staan, met de bron en de citatie. §2 vergelijkt alleen of de waarden gelijk zijn; wat het verschil betekent, bepalen §4 en §7.

Datatypen van een lagere bron worden niet vergeleken en niet bewaard, omdat ze niet genormaliseerd zijn (§5.5).

## 5. Van tabel naar §1-elementen (B26)

### 5.1 Schema in het geheugen

```python
class Span:        path: str; start_line: int; end_line: int; reader: str
class Column:      name: str; datatype: str | None; mandatory: bool | None; origin: tuple[Span, ...]; defined_at: Span
class Constraint:  kind: Literal["primary", "unique", "foreign", "value", "check"]
                   name: str | None; columns: tuple[str, ...]
                   ref_table: str | None; ref_columns: tuple[str, ...]   # alleen bij "foreign"
                   allowed_values: tuple[str, ...]                       # alleen bij "value"
                   statement: str | None                                 # alleen bij "check"
                   spans: tuple[Span, ...]
class Table:       name: str; columns: tuple[Column, ...]; constraints: tuple[Constraint, ...]
                   defined_at: Span; model_class: str | None; uncertain: tuple[tuple[str, Span], ...]
```

Bewerkingen (B32): tabel aanmaken, hernoemen en verwijderen; kolom toevoegen, verwijderen, hernoemen en wijzigen; beperking toevoegen en verwijderen. Een bewerking die niet past (een kolom toevoegen aan een onbekende tabel, een tabel twee keer aanmaken) maakt de tabel `uncertain` en verandert verder niets. `Span` wordt bij de vertaling een `Citation`, met de repository en de commit uit §9.2.

### 5.2 Namen

§2 leidt namen mechanisch af. De namen zijn die van de code; §3 en §4 stellen later domeinnamen voor, en §4 herkent dat als hernoeming (B21).

| Element | Naam | Voorbeeld |
|---|---|---|
| Feittype | De tabelnaam zoals in de bron, zonder schemanaam en zonder aanhalingstekens | `team_user` → `fact_type:backend/team-user` |
| Begrip | De naam van de gekoppelde modelklasse, in losse woorden en kleine letters; zonder modelklasse de tabelnaam | `TeamMember` → `team member`; anders `users` |
| Rol | De kolomnaam in de database | `user_id` → `role:backend/team-user/user-id` |
| Koppeling van het feittype | `target` is de tabelnaam | `team_user` |
| Koppeling van de rol | `target` is `<tabel>.<kolom>` | `team_user.user_id` |

- **Geen enkelvoud of meervoud raden.** `plural` blijft `None`, net als `definition`; `synonyms` is leeg.
- **De rol heet naar de kolom.** B12 en B26 zeggen dat de rol naar het begrip heet. Vast afleiden kan dat niet: een kolom zonder *foreign key* heeft geen bekend begrip, en twee verwijzingen naar dezelfde tabel (`sender_id`, `receiver_id`) zouden dezelfde naam krijgen. De kolomnaam is altijd uniek en verandert niet tussen runs. Het begrip staat in `Role.concept`. Dit is een voorstel dat de letter van B12 en B26 raakt (§12).
- **Botsende sleutels.** Geven twee tabellen of twee kolommen hetzelfde `key_segment` (`user_id` en `user-id`), dan krijgt de tweede in bronvolgorde geen element, maar een markering `unresolved` met `key_collision`.

### 5.3 Sleutelrollen, begrip en `identifies`

- De **sleutelrollen** zijn de rollen van de primaire sleutel. Zonder primaire sleutel zijn het de rollen van de uniciteit met de minste kolommen (bij gelijkstand de eerste in bronvolgorde). Zonder uniciteit zijn er geen sleutelrollen.
- Een tabel krijgt een **begrip** als hij een primaire sleutel heeft die niet alleen uit *foreign-key*-kolommen bestaat. Het feittype krijgt dan `identifies` met het id van dat begrip (aanname bij B26). Een zuivere koppeltabel en een tabel zonder sleutel krijgen geen begrip.
- `Role.concept`:
  - de rol van een primaire sleutel van één kolom wijst naar het begrip van de eigen tabel;
  - de rol van een *foreign key* van één kolom wijst naar het begrip van de tabel waarnaar hij verwijst, als die er een heeft;
  - elke andere rol heeft `None`.

### 5.4 Sjablonen

§2 schrijft mechanische sjablonen. Ze zijn herkenbaar geen zinnen, zodat §3 weet dat er nog een zin moet komen.

| Sjabloon | Vorm | Voorbeeld |
|---|---|---|
| Identificerend | `<tabel>(<sleutel 1>, <sleutel 2>)` | `team_user(<id>)` |
| Per rol die geen sleutelrol is | `<tabel>(<sleutels>) has <kolom> <kolom>` | `team_user(<id>) has role <role>` |
| Zonder sleutelrollen, per rol | `<tabel> has <kolom> <kolom>` | `audit_line has note <note>` |

Volgorde: eerst het identificerende sjabloon, daarna de rollen in de volgorde van de bron. `FactType.roles` staat in dezelfde volgorde: eerst de sleutelrollen, dan de rest.

Het begrip "hoofdsjabloon" uit B25, punt 1 vervalt. Daarvoor komt één afspraak: bij een feittype met `identifies` is het eerste sjabloon het identificerende. De lader controleert dat niet. Dit werkt de aanname bij B26 uit (§12).

### 5.5 Verplicht en datatype

`mandatory` is `True` bij `NOT NULL` of een primaire sleutel, `False` bij een kolom die leeg mag zijn, en `None` als de bron het niet zegt.

`datatype` blijft in de notatie van de bron (§1-spec §4.2). §2 brengt die notatie alleen in een vaste vorm per lezer, zodat ze tussen runs gelijk is. Er komt in versie 1 geen gemeenschappelijk type over stacks heen.

| Lezer | Vorm | Voorbeeld |
|---|---|---|
| SQL | Het type in kleine letters, spaties samengevoegd, met lengte en `unsigned` | `bigint unsigned`, `varchar(255)` |
| Laravel-migratie | De Blueprint-methode, met letterlijke argumenten na de naam | `string(100)`, `foreignId`, `decimal(8,2)` |
| `db_schema.xml` | `xsi:type`, met lengte of precisie en `unsigned` | `int unsigned`, `decimal(12,4)` |
| Prisma | Het scalaire type, met het `@db`-attribuut als dat er staat | `String`, `String @db.VarChar(255)` |
| TypeORM | De optie `type` als die letterlijk is, anders de TypeScript-annotatie | `varchar`, `string` |
| EAV | De waarde van `type` | `varchar`, `static` |
| GraphQL | Het type zonder `!` | `String`, `[ID]` |

### 5.6 Regels

| Beperking | §1-element | Citatie |
|---|---|---|
| Primaire sleutel | `uniqueness` op de sleutelrollen | De plaats van de sleutel |
| `UNIQUE`, ook over meerdere kolommen | `uniqueness` op die rollen | De plaats van de beperking |
| *Foreign key* naar een tabel met feittype | `subset`, met `superset_fact_type` en `superset_roles` | De plaats van de *foreign key* |
| *Foreign key* naar een tabel zonder feittype | Geen regel; markering `external_reference` | Idem |
| Vaste waarden (`enum`, `CHECK (x IN (…))`) | `value` op die rol, met `allowed_values` in bronvolgorde | De plaats van de waarden |
| Andere `CHECK` | `other`, met `statement` de tekst uit de bron | De plaats van de `CHECK` |

De naam van een `other`-regel is de naam van de beperking. Zonder naam is het `check-<kolom>` bij een `CHECK` op één kolom, en anders `check-<hash>` met 8 hex-tekens van SHA-256 over de tekst.

Twee *foreign keys* op dezelfde kolommen naar verschillende tabellen zouden hetzelfde id geven (§1-spec §6.2). De eerste in bronvolgorde wordt de `subset`-regel; de tweede wordt een `DivergentClaim` met `property` `superset`.

### 5.7 Citaties bij nagespeelde migraties (B32)

- **Feittype:** de aanroep die de tabel aanmaakt. Een latere hernoeming van de tabel komt erbij.
- **Rol:** elke bewerking die de kolom nu nog bepaalt, in afspeelvolgorde: aanmaken, en elke latere wijziging of hernoeming. De koppeling van de rol wijst naar de laatste daarvan.
- **Regel:** de bewerking die de beperking toevoegde.
- Een verwijderde kolom of beperking laat niets achter.

### 5.8 Technische tabellen (B33)

De lijst hangt aan de lezer, niet aan het hele project. Een domeintabel `jobs` in een Prisma-project blijft zo buiten schot.

| Lijst | Geldt voor tabellen uit | Namen |
|---|---|---|
| `laravel` | Laravel-migraties en `database/schema/*.sql` | `migrations`, `jobs`, `failed_jobs`, `job_batches`, `cache`, `cache_locks`, `sessions`, `password_reset_tokens`, `password_resets`, `telescope_entries`, `telescope_entries_tags`, `telescope_monitoring`, `pulse_aggregates`, `pulse_entries`, `pulse_values` |
| `magento` | `db_schema.xml` | `*_idx`, `*_tmp`, `*_replica`, `*_cl`, `*_entity_int`, `*_entity_decimal`, `*_entity_varchar`, `*_entity_text`, `*_entity_datetime`, `cron_schedule`, `setup_module`, `patch_list`, `cache`, `cache_tag`, `session`, `indexer_state`, `mview_state` |
| `migration_tools` | Alle lezers | `_prisma_migrations`, `typeorm_metadata`, `flyway_schema_history`, `knex_migrations`, `knex_migrations_lock`, `databasechangelog`, `databasechangeloglock` |
| `typeorm` | TypeORM-entities en losse SQL | `migrations` |
| `graphql` | GraphQL-typen die een feittype worden (§7.3) | `*Connection`, `*Edge`, `PageInfo`, `PaginatorInfo`, `SimplePaginatorInfo` |

`*` staat voor nul of meer tekens. Een koppeltabel zoals `team_user` staat nergens op.

Configuratie, in `.chunkhound.json`:

```json
{"domain": {"technical_tables": {"add": ["audit_*"], "remove": ["sessions"]}}}
```

`add` geldt voor alle lezers en geeft `reason` `configured`; `remove` haalt een naam of patroon van elke lijst. Dat wordt een nieuw model `DomainConfig` in `chunkhound/core/config/domain_config.py`, als veld `domain` op `Config` naast de andere secties (`chunkhound/core/config/config.py:134-143`).

### 5.9 Voorbeeld

Bron, in repository `backend`:

```php
// backend/database/migrations/2024_01_10_000000_create_team_user_table.php
Schema::create('team_user', function (Blueprint $table) {            // regel 12
    $table->id();                                                    // 13
    $table->foreignId('team_id')->constrained('teams');              // 14
    $table->foreignId('user_id')->constrained('users');              // 15
    $table->enum('role', ['member', 'lead'])->default('member');     // 16
    $table->unique(['team_id', 'user_id']);                          // 17
});                                                                  // 18
```

De tabellen `teams` en `users` staan in eerdere migraties, elk met `id()`. Uitvoer voor `team_user`, ingekort: elk element heeft ook `repository`, `status: "extracted"`, `citations` en lege `human_sources`, en het feittype en de rollen hebben een koppeling (`target` `team_user` op regels 12-18, `team_user.role` op regel 16, enzovoort).

```json
{
  "concepts": [
    {"id": "concept:backend/team-user", "term": "team_user", "plural": null, "definition": null, "synonyms": []}
  ],
  "fact_types": [
    {"id": "fact_type:backend/team-user", "name": "team_user",
     "templates": [
       "team_user(<id>)",
       "team_user(<id>) has team_id <team_id>",
       "team_user(<id>) has user_id <user_id>",
       "team_user(<id>) has role <role>"
     ],
     "roles": ["role:backend/team-user/id", "role:backend/team-user/team-id", "role:backend/team-user/user-id", "role:backend/team-user/role"],
     "identifies": "concept:backend/team-user"}
  ],
  "roles": [
    {"id": "role:backend/team-user/id", "name": "id", "concept": "concept:backend/team-user", "datatype": "id", "mandatory": true},
    {"id": "role:backend/team-user/team-id", "name": "team_id", "concept": "concept:backend/teams", "datatype": "foreignId", "mandatory": true},
    {"id": "role:backend/team-user/user-id", "name": "user_id", "concept": "concept:backend/users", "datatype": "foreignId", "mandatory": true},
    {"id": "role:backend/team-user/role", "name": "role", "concept": null, "datatype": "enum", "mandatory": true}
  ],
  "validation_rules": [
    {"id": "validation_rule:backend/team-user/subset/team-id", "rule_kind": "subset", "superset_fact_type": "fact_type:backend/teams", "superset_roles": ["role:backend/teams/id"]},
    {"id": "validation_rule:backend/team-user/subset/user-id", "rule_kind": "subset", "superset_fact_type": "fact_type:backend/users", "superset_roles": ["role:backend/users/id"]},
    {"id": "validation_rule:backend/team-user/uniqueness/id", "rule_kind": "uniqueness"},
    {"id": "validation_rule:backend/team-user/uniqueness/team-id+user-id", "rule_kind": "uniqueness"},
    {"id": "validation_rule:backend/team-user/value/role", "rule_kind": "value", "allowed_values": ["member", "lead"]}
  ]
}
```

De volledige vorm staat als fixture in `tests/domain_model/structure/fixtures/example/expected.json`, geschreven door `dump_structure`.

## 6. Lezers voor opslag

Elke lezer hieronder levert bewerkingen op het schema van §5.1. De vertaling naar §1-elementen is voor alle lezers die van §5. Per lezer staat wat hij leest, hoe de bronvorm vertaalt, wat hij markeert, en wat de fixture moet aantonen. Fixtures staan in `tests/domain_model/structure/fixtures/<lezer>/`.

### 6.1 Bestanden lezen en ontleden

- **Bestandsselectie:** `collect_scope_files` (`chunkhound/code_mapper/scope.py:8`), met eigen `include_patterns` per lezer. De standaard volgt `.gitignore`. Alleen de Magento-lezer geeft voor `vendor/` `ignore_sources=[]` mee (B28, §6.5).
- **Lezen:** `read_source(project_root, path, strict=False)` (`sources.py:19`). Het geeft de regels terug zoals de citaties ze tellen. Een bestand boven 10 MB wordt overgeslagen met `unresolved` en `source_too_large`.
- **Ontleden:** de grammatica's uit `tree_sitter_language_pack`, opgehaald zoals `chunkhound/parsers/mappings/html.py:29-30` dat doet. PHP en TypeScript lopen ook via `ParserFactory` (`chunkhound/parsers/parser_factory.py`); voor XML, Prisma en GraphQL heeft ChunkHound geen `Language`, en dat blijft zo (invariant 2).

Gedraaide proeven op `02d5664a`, met kleine voorbeelden:

| Grammatica | Uitkomst | Gevolg |
|---|---|---|
| `xml` | Foutloos op een `db_schema.xml`-vorm; elementen en attributen met regelnummers | XML gaat via tree-sitter. Die lost geen entiteiten op, dus er is geen nieuwe afhankelijkheid en geen risico van externe entiteiten (invariant 10) |
| `prisma` | Foutloos; `model_block`, `model_field`, `enum_block` | Geen eigen parser nodig |
| `php` | Foutloos op `Schema::create` en `Route::post` | – |
| `sql` | Kolommen, `PRIMARY KEY`, `UNIQUE KEY`, `ENGINE=` en `ALTER TABLE … ADD CONSTRAINT` gaan goed. **Fout** op een benoemde beperking binnen `CREATE TABLE`: `CONSTRAINT fk FOREIGN KEY …` en `CONSTRAINT uq UNIQUE …` | Dat is precies de vorm van `mysqldump`, dus van een Laravel-schemadump. De SQL-lezer vertrouwt voor de inhoud van `CREATE TABLE` niet op de boom (§6.2) |
| `graphql` | Velden, argumenten en directives gaan goed. **Fout** binnen een tekst met `\\`, zoals `@resolver(class: "Acme\\Model\\Resolver")` | De fout blijft binnen de knoop `string_value`. De lezer neemt de tekst van die knoop uit de bron en haalt de aanhalingstekens en `\\` zelf weg (§7.3) |

### 6.2 SQL: DDL en losse migraties (B32)

**Leest:** `**/*.sql`.

| Bronvorm | Bewerking |
|---|---|
| `CREATE TABLE [IF NOT EXISTS] t (…)` | Tabel aanmaken. Met `IF NOT EXISTS` op een bestaande tabel: niets |
| Kolom met type, `NOT NULL`, `NULL`, `PRIMARY KEY`, `UNIQUE`, `REFERENCES u(id)`, `CHECK (…)` | Kolom, met de beperkingen als losse beperkingen |
| `PRIMARY KEY (…)`, `UNIQUE [KEY naam] (…)`, `[CONSTRAINT naam] FOREIGN KEY (…) REFERENCES u (…)`, `[CONSTRAINT naam] CHECK (…)` | Beperking |
| Type `enum('a','b')`; `CHECK (x IN ('a','b'))`; een kolom van een `CREATE TYPE … AS ENUM` | Beperking `value` |
| `ALTER TABLE t ADD [COLUMN]`, `DROP [COLUMN]`, `RENAME COLUMN`, `RENAME TO`, `MODIFY`, `CHANGE`, `ALTER COLUMN … TYPE`, `SET NOT NULL`, `DROP NOT NULL` | De bijbehorende bewerking |
| `ALTER TABLE t ADD CONSTRAINT …`, `ADD PRIMARY KEY`, `ADD UNIQUE`, `ADD FOREIGN KEY`, `DROP CONSTRAINT`, `DROP FOREIGN KEY`, `DROP PRIMARY KEY`, `DROP INDEX` | Beperking erbij of eraf |
| `CREATE UNIQUE INDEX naam ON t (…)`, `DROP INDEX naam` | Uniciteit erbij of eraf |
| `DROP TABLE`, `RENAME TABLE` | Tabel verwijderen of hernoemen |

- **Inhoud van `CREATE TABLE`:** tree-sitter levert de grenzen van de instructies en de regelnummers. De lezer splitst de inhoud tussen de buitenste haakjes zelf op komma's op het bovenste niveau, en herkent elk deel aan zijn eerste woorden. Zo hangt hij niet af van het gat uit §6.1.
- **Volgorde (B32):** binnen één map op natuurlijke volgorde van de bestandsnaam: cijferreeksen tellen als getal, dus `V2__x.sql` komt voor `V10__y.sql`. Voor namen met een tijdstempel is dat gelijk aan de gewone volgorde. Mappen gaan in volgorde van het pad. Bestanden die met `U` plus een versienummer beginnen (Flyway-undo) tellen niet mee.
- **Namen:** de schemanaam (`public.users`) en aanhalingstekens vallen weg.
- **Niet gelezen:** `INSERT`, `UPDATE`, views, triggers, procedures en gewone indexen.
- **Markeert:** een instructie op een bekende tabel die de lezer niet begrijpt, maakt die tabel `uncertain` met `unparsed_statement`. Twee keer `CREATE TABLE` voor dezelfde naam zonder `IF NOT EXISTS` geeft `table_created_twice`.

**Fixture `sql/`:** een `schema.sql` in de vorm van `mysqldump` (backticks, `ENGINE=`, benoemde `CONSTRAINT … FOREIGN KEY`, `UNIQUE KEY`, `enum(…)`), een map `migrations/` met `V1__`, `V2__` en `V10__` (kolom erbij, kolom hernoemd, uniciteit eraf), één PostgreSQL-bestand (`REFERENCES` op de kolom, `CHECK … IN`, `CREATE TYPE … AS ENUM`) en één `ALTER TABLE` met een onbekende vorm. Moet aantonen: de benoemde *foreign key* wordt een `subset`-regel; `V10` is na `V2` gespeeld; de hernoemde kolom heeft twee citaties; de onbekende vorm geeft `uncertain`.

### 6.3 Laravel-migraties (B32)

**Leest:** `**/database/migrations/*.php` en `**/database/schema/*.sql`.

| Bronvorm in `up()` | Bewerking |
|---|---|
| `Schema::create('t', function (Blueprint $table) {…})` | Tabel aanmaken |
| `Schema::table('t', …)` | Bewerkingen op een bestaande tabel |
| `Schema::rename`, `Schema::drop`, `Schema::dropIfExists` | Hernoemen, verwijderen |
| `$table->string('email', 100)` en de andere kolommethoden | Kolom; standaard verplicht |
| `$table->id()`; `timestamps()`; `softDeletes()`; `rememberToken()`; `morphs('x')` | `id` als primaire sleutel; `created_at` en `updated_at`; `deleted_at`; `remember_token`; `x_type` en `x_id`. Wat Laravel leeg toelaat, is niet verplicht |
| `->nullable()`, `->unique()`, `->primary()`, `->unsigned()`, `->change()` | Niet verplicht; uniciteit; primaire sleutel; in het datatype; kolom wijzigen |
| `$table->enum('c', ['a','b'])`, `set(…)` | Kolom plus beperking `value` |
| `$table->primary([…])`, `unique([…])` | Beperking |
| `$table->foreign('c')->references('id')->on('t')`; `foreignId('c')->constrained('t')` | *Foreign key* |
| `foreignId('user_id')->constrained()` zonder argument | *Foreign key* naar de tabel met de regelmatige meervoudsvorm (§8.2), als die tabel in het schema staat; anders `external_reference` met `table_not_found` |
| `dropColumn`, `renameColumn`, `dropUnique`, `dropForeign`, `dropPrimary` | Verwijderen of hernoemen. Een beperking op naam wordt gevonden via de naam die Laravel zelf maakt (`<tabel>_<kolommen>_unique`, `…_foreign`) |
| `->default()`, `->index()`, `->after()`, `->comment()`, `->useCurrent()` en `$table->index(…)` | Genegeerd |

- **Volgorde:** natuurlijke volgorde van de bestandsnaam. `down()` telt niet mee.
- **Schemadump:** bestaat `database/schema/*.sql`, dan speelt de SQL-lezer die eerst. De regels `INSERT INTO migrations` in de dump noemen de migraties die er al in zitten; die bestanden worden overgeslagen. Staat er geen zulke regel in, dan worden alle migraties na de dump gespeeld.
- **Markeert:**
  - `DB::statement`, `DB::unprepared` of `DB::raw` in `up()`: de tabellen die de migratie raakt worden `uncertain` met `raw_sql`. Raakt de migratie geen tabel met een Schema-aanroep, dan is het een markering zonder `subject`;
  - een Schema-aanroep binnen `if`, `foreach` of een andere voorwaarde of lus: `conditional_schema`;
  - een onbekende methode op `$table`: `unknown_schema_call`. De lezer werkt met een lijst van bekende kolom- en beperkingsmethoden en beschouwt een onbekende methode niet stil als kolom;
  - een tabelnaam of kolomnaam die geen letterlijke tekst is: `unresolved` met `non_literal_argument`.

**Fixture `laravel_migrations/`:** de migraties van het voorbeeld uit §5.9, een migratie die een kolom toevoegt en een die hem hernoemt, een migratie met `DB::statement`, een migratie met `if (Schema::hasColumn(…))`, en de tabellen `jobs` en `sessions`. Een tweede map heeft een schemadump met drie `INSERT INTO migrations` en één nieuwere migratie. Moet aantonen: de uitvoer van §5.9; `raw_sql` en `conditional_schema` op de juiste tabel; `technical` op `jobs` en `sessions`; alleen de nieuwere migratie is na de dump gespeeld.

### 6.4 Eloquent-modellen

Een model is een lagere bron (B31). Het levert geen bewerkingen op het schema, maar uitspraken voor §8.

**Leest:** PHP-klassen die `Illuminate\Database\Eloquent\Model` uitbreiden, direct of via een klasse in hetzelfde project (`SourceInspector.find_type_bases`, `chunkhound/code_mapper/c4/codeboarding/source_inspector.py:1152`).

| Bronvorm | Uitspraak |
|---|---|
| De klasse zelf | Koppeling van model aan tabel (§8.2). De klasse wordt een citatie van het begrip en een tweede koppeling van het feittype, met `target` de klassenaam |
| `belongsTo(Team::class)`, ook met een letterlijk tweede argument | `subset` van de kolom (`team_id`, of het tweede argument) naar de tabel van `Team` |
| `$casts` of `casts()` met een PHP-enum met waarden | `value` op die kolom, met de waarden van de enum |
| `hasMany`, `hasOne`, `belongsToMany`, `morphTo` | Niets in versie 1 |

- **Geen feittype uit een model alleen.** Een Eloquent-model noemt zijn kolommen niet. Een model zonder tabel in het schema krijgt `unresolved` met `model_table_unknown`, en verder niets.
- **Klasse naar bestand:** via de `use`-regels en de PSR-4-tabel uit `autoload` en `autoload-dev` in `composer.json`. `ImportResolverService` volgt voor PHP alleen `require` en `include` (`chunkhound/parsers/mappings/php.py:759`), dus dit is een kleine eigen opzoeking, gedeeld met §7.

**Fixture `eloquent/`:** de migraties van §6.3 plus `User`, `Team` (met `$table`), een model `TeamMember` met `belongsTo` en een enum-cast die dezelfde waarden heeft als de migratie, een model met een enum-cast die een waarde minder heeft, en een model zonder tabel. Moet aantonen: de begripsterm is `team member`; de `subset`-regel heeft twee citaties; de gelijke enum is een extra citatie op de `value`-regel; de afwijkende enum is een `DivergentClaim`; het model zonder tabel is `unresolved`.

### 6.5 Magento: `db_schema.xml` en modules (B28)

**Module:** een map met `registration.php` en `etc/module.xml`. Een module is **eigen** als hij niet onder een map `vendor/` staat; dat dekt `app/code` en elke andere plek. Een module onder `vendor/` is **van derden**.

**Leest:** `etc/db_schema.xml` van elke eigen module, volledig.

| Bronvorm | Bewerking |
|---|---|
| `<table name="t">` | Tabel aanmaken, of uitbreiden als hij al bestaat. Magento voegt de declaraties van alle modules samen, dus dat is hier geen `table_created_twice` |
| `<column xsi:type="…" name="c" nullable="false" unsigned="true" length="…" precision="…" scale="…" identity="true">` | Kolom; `nullable` ontbreekt betekent niet verplicht onbekend (`None`) |
| `<constraint xsi:type="primary">` met `<column name>` | Primaire sleutel |
| `<constraint xsi:type="unique">` | Uniciteit |
| `<constraint xsi:type="foreign" column="c" referenceTable="u" referenceColumn="id">` | *Foreign key* |
| `disabled="true"` op een tabel, kolom of beperking | Verwijderen |
| `<index>` | Genegeerd |

**Uit `vendor/`, één stap diep:** een tabel uit `vendor/` komt mee als een eigen module hem uitbreidt (een `<table>` met dezelfde naam), ernaar verwijst met een *foreign key*, of er een EAV-attribuut aan toevoegt (§6.6). De lezer zoekt de declaraties in `vendor/*/*/etc/db_schema.xml`, zonder `.gitignore` te volgen, en voegt alle declaraties van die tabel samen. De *foreign keys* van zo'n tabel naar andere tabellen in `vendor/` worden niet gevolgd: dat zijn markeringen `external_reference` met `vendor_not_followed`.

- **Markering `third_party`:** op het feittype en op elk element waarvan alle citaties in `vendor/` liggen. `detail` is de naam en de versie uit de `composer.json` van de module, zoals `magento/module-catalog 104.0.7`.
- **Commit:** een bestand in `vendor/` staat niet in Git. De citatie draagt de commit van de repository; de markering `third_party` zegt dat de inhoud daar niet in zit.
- **Ontbreekt `vendor/`:** één markering `unresolved` met `vendor_missing` voor de run, en per verwijzing een `external_reference` met `table_not_found`.

**Fixture `magento_schema/`:** de module `app/code/Acme/Notes` (eigen tabel `acme_note` met een *foreign key* naar `customer_entity`, en een extra kolom op `sales_order`), een module `packages/acme-audit` buiten `app/code`, en een kleine `vendor/magento/module-customer` en `module-sales` met `composer.json`. `vendor/` staat in de `.gitignore` van de fixture. Een tweede variant heeft geen `vendor/`. Moet aantonen: `customer_entity` en `sales_order` zijn `third_party` met pakket en versie; de eigen kolom op `sales_order` is dat niet; een tabel uit `vendor/` die niemand aanraakt, ontbreekt; de module buiten `app/code` is gelezen; zonder `vendor/` zijn er `vendor_missing` en `external_reference`.

### 6.6 Magento: EAV-attributen (B29)

**Leest:** `Setup/Patch/Data/*.php` van eigen modules: aanroepen van `addAttribute(<entiteit>, '<code>', [ … ])` op een `EavSetup` of een afgeleide zoals `CustomerSetup`.

| Bronvorm | Bewerking |
|---|---|
| Entiteit: een letterlijke tekst, of een constante `Product::ENTITY`, `Category::ENTITY`, `Customer::ENTITY` of `AddressMetadataInterface::ENTITY_TYPE_ADDRESS` | De entiteitstabel: `catalog_product_entity`, `catalog_category_entity`, `customer_entity` of `customer_address_entity` |
| De attribuutcode | Kolom op die tabel. De koppeling heeft `target` `eav:<entiteit>.<code>` |
| `'type' => 'varchar'` | Datatype |
| `'required' => true` of `false` | Verplicht; ontbreekt de sleutel, dan `False` (de standaard van Magento) |
| `'unique' => true` | Uniciteit op die rol |
| `'source' => X::class`, waarbij `X` in een eigen module staat en `getAllOptions()` een letterlijke lijst teruggeeft | Beperking `value` met de waarden van `value` |

- De entiteitstabel komt uit `vendor/` mee (§6.5). Ontbreekt hij, dan maakt de lezer het feittype met alleen de attribuutrollen, zonder sleutelrollen, en markeert het `uncertain` met `entity_table_missing`.
- Een entiteit of code die geen letterlijke tekst of bekende constante is, geeft `unresolved` met `non_literal_argument`.
- Een source model buiten de eigen modules, of met opties die niet letterlijk zijn, geeft geen regel en geen markering: §3 kan het lezen via de citatie.

**Fixture `magento_eav/`:** een data patch met drie attributen op `catalog_product` (verplicht en uniek; met een eigen source model; met een source model uit `vendor/`), één attribuut met een variabele als code, en `vendor/magento/module-catalog` met `catalog_product_entity`. Moet aantonen: drie rollen op `fact_type:root/catalog-product-entity`, elk met een eigen sjabloon; uniciteit en `value`-regel; `unresolved` voor de variabele; de rollen zijn niet `third_party`, het feittype wel.

### 6.7 Prisma (B30)

**Leest:** `**/*.prisma`.

| Bronvorm | Bewerking |
|---|---|
| `model User { … }`, met `@@map("users")` | Tabel; de naam is de waarde van `@@map`, anders de modelnaam. De modelnaam is de modelklasse (§5.2) |
| Scalair veld `email String`, met `@map("e_mail")` | Kolom; de naam is de waarde van `@map`, anders de veldnaam |
| `String?` | Niet verplicht; zonder `?` verplicht |
| `@id`, `@@id([…])` | Primaire sleutel |
| `@unique`, `@@unique([…])` | Uniciteit |
| `team Team @relation(fields: [teamId], references: [id])` | *Foreign key* van `teamId` naar de tabel van `Team`. Het relatieveld zelf is geen kolom |
| Veld met een `enum`-type | Kolom plus beperking `value` met de waarden van het `enum`-blok |
| Lijstveld (`Post[]`), `@ignore`, `@@ignore`, `@default`, `@updatedAt`, `@@index` | Geen kolom, of genegeerd |

**Fixture `prisma/`:** `User`, `Team` en `TeamMember` met `@@map`, `@map`, `@@unique`, een relatie, een enum en `_prisma_migrations` als model. Moet aantonen: de rolnaam is de kolomnaam uit `@map`; de begripsterm is `team member`; de relatie is een `subset`-regel; `_prisma_migrations` is `technical`.

### 6.8 TypeORM (B30)

**Leest:** TypeScript-klassen met `@Entity`. Decorators komen uit `extract_decorators` (`chunkhound/parsers/mappings/typescript.py:537`) of uit dezelfde boom.

| Bronvorm | Bewerking |
|---|---|
| `@Entity('team_user')`, `@Entity({ name: … })` | Tabel; zonder naam de klassenaam in *snake case*, zoals de standaardstrategie van TypeORM. De klassenaam is de modelklasse |
| `@Column({ type, length, name, nullable, unique })`, `@CreateDateColumn`, `@UpdateDateColumn`, `@DeleteDateColumn`, `@VersionColumn` | Kolom; de naam is de optie `name`, anders de naam van de eigenschap. Zonder `nullable: true` verplicht |
| `@PrimaryGeneratedColumn`, `@PrimaryColumn` | Kolom plus primaire sleutel |
| `@Unique([…])`, `@Index([…], { unique: true })` op de klasse | Uniciteit |
| `@ManyToOne(() => Team)` of `@OneToOne(() => Team)` met `@JoinColumn({ name })` | Kolom (de naam uit `@JoinColumn`, anders `<eigenschap>Id`) plus *foreign key* naar de tabel van `Team` |
| `@Column({ type: 'enum', enum: Role })`, met `Role` in hetzelfde bestand of in een relatief geïmporteerd bestand | Beperking `value` |
| `@OneToMany`, `@ManyToMany`, `@JoinTable` | Niets in versie 1 |

- Een optie die geen letterlijke waarde is, geeft `unresolved` met `non_literal_argument`.
- Een eigen naamstrategie (zoals `SnakeNamingStrategy`) leest §2 niet. De namen zijn dan die van de standaardstrategie; de koppeling aan een andere bron kan daardoor missen.

**Fixture `typeorm/`:** drie entities met een relatie, een samengestelde uniciteit, een enum uit een geïmporteerd bestand en een optie uit een variabele. Moet aantonen: tabelnaam in *snake case*; de kolom uit `@JoinColumn`; de `value`-regel uit het geïmporteerde enum; `unresolved` voor de variabele.

## 7. Ankers en API-vorm (B27, B30)

Een anker is één ingang. §2 maakt geen uitwisselingsregels; §3 maakt er één per anker, of legt vast dat het anker geen domeinuitwisseling is. Daardoor is de dekking te meten.

**Aanwijzingen**, voor alle lezers gelijk:

| `kind` | Wanneer | Inhoud |
|---|---|---|
| `operation` | De methode zegt iets over de bewerking | `value`: `add` (POST), `change` (PUT, PATCH), `remove` (DELETE) of `read` (GET, HEAD, een GraphQL-query) |
| `model` | Een model- of entityklasse in de signatuur van de handler | `name`: de klasse; `fact_type` als het model aan een tabel gekoppeld is |
| `input_type` | Een invoerklasse of invoertype | `name`: `FormRequest`-klasse, DTO, Zod-schema of GraphQL-`input` |
| `input_rule` | Eén gevalideerd veld | `name`: het veld; `value`: de regel zoals in de bron (`required\|email`, `z.string().min(1)`, `@IsEmail()`) |
| `enum` | Een enum in de invoer | `name` en `values` |

`role` in een `input_rule` wordt gevuld als de veldnaam gelijk is aan de naam van precies één rol in de feittypen van de `model`-aanwijzingen van hetzelfde anker (B31). Anders blijft het `None`. Invoervalidatie maakt nooit een feittype.

**Handler:** `handler` is `None` als de bron geen handler noemt. Noemt de bron er een die niet te vinden is, dan blijft `symbol` gevuld, is `citation` `None` en komt er een markering `unresolved` met `handler_not_found`.

### 7.1 Laravel: routes en commands

**Leest:** `routes/**/*.php`, en klassen die `Illuminate\Console\Command` uitbreiden.

| Bronvorm | Anker |
|---|---|
| `Route::get`, `post`, `put`, `patch`, `delete`, `options` met een letterlijk pad | `http`, met die methode |
| `Route::match(['get','post'], …)`, `Route::any(…)` | Eén anker per methode; `any` geeft `method` `ANY` |
| Handler `[Ctrl::class, 'store']`, `'Ctrl@store'`, `Ctrl::class` (invokable) of een closure | `symbol` `Ctrl@store`, `Ctrl@__invoke` of `closure`; de citatie is de methode of de closure |
| `Route::resource('teams', Ctrl::class)`, `apiResource`, met letterlijke `only` of `except` | De standaardacties, elk als eigen anker (`index`, `store`, `show`, `update`, `destroy`; bij `resource` ook `create` en `edit`) |
| `Route::prefix('x')->group(…)`, `Route::controller(Ctrl::class)->group(…)`, ook genest | Het voorvoegsel en de controller gelden voor de routes erin |
| `Route::view`, `Route::redirect` | Geen anker |
| `protected $signature = 'teams:sync {team}'` in een command-klasse | `command`, `path` `teams:sync`, handler `Klasse@handle` |
| `Artisan::command('naam', function …)` | `command`, met de closure als handler |

- **Pad:** zoals in het routebestand, met de voorvoegsels van de groepen. Een voorvoegsel dat elders wordt gezet (zoals `/api` voor `routes/api.php`) leest §2 niet; het routebestand staat in de citatie.
- **Aanwijzingen:** `operation`; `model` voor elke parameter van de handler met een modelklasse als type; `input_type` en `input_rule` voor een parameter met een `FormRequest` waarvan `rules()` een letterlijke lijst teruggeeft; `input_rule` voor `$request->validate([…])` en `Validator::make($x, […])` met een letterlijke lijst in de handler.
- **Markeert:** een route met een pad of handler dat geen letterlijke waarde is, en een route binnen `foreach` of een andere lus: `unresolved` met `dynamic_registration`, zonder `subject`.

**Fixture `laravel_routes/`:** `routes/api.php` met elke vorm uit de tabel, een geneste groep, een `apiResource` met `only`, een route in een `foreach`, een controller met een `FormRequest` en een modelparameter, en één command. Moet aantonen: het aantal ankers en hun paden; de aanwijzingen op `POST /teams/{team}/members`, met `role` gevuld voor het veld dat met een rol overeenkomt; `dynamic_registration` voor de lus. De fixture toont ook dat `SourceInspector` (`source_inspector.py:531`) deze vormen aankan, of dat de lezer de boom zelf loopt.

### 7.2 Magento: `webapi.xml` en `routes.xml`

**Leest:** van eigen modules `etc/webapi.xml`, `etc/frontend/routes.xml` en `etc/adminhtml/routes.xml`, `etc/di.xml` en de controllers onder `Controller/`.

| Bronvorm | Anker |
|---|---|
| `<route url="/V1/notes" method="POST"><service class="…\NoteRepositoryInterface" method="save"/>` | `http`, met het pad en de methode. `symbol` is `Interface@save` |
| `<preference for="…Interface" type="…">` in `di.xml` van een eigen module | De citatie van de handler wijst naar de methode in de implementatie; zonder `preference` naar de methode in de interface |
| `<route id="acme" frontName="acme"><module name="Acme_Notes"/>` plus `Controller/Note/Save.php` met `execute()` | `http`, pad `/acme/note/save`. `method` is `POST` of `GET` als de klasse `HttpPostActionInterface` of `HttpGetActionInterface` implementeert, anders `ANY` |

- **Aanwijzingen:** `operation`; `input_type` voor een parameter met een klasse uit `Api/Data` als type (uit het type of uit `@param`).
- `source` is `magento_webapi`, `magento_routes_frontend` of `magento_routes_adminhtml`.
- Ankers komen alleen uit eigen modules (B28).

**Fixture `magento_anchors/`:** de module van §6.5 met een `webapi.xml` (twee routes, één met `preference`), een `routes.xml` voor de winkel en een voor het beheer, en drie controllers. Moet aantonen: vijf ankers; de handler via `preference`; de methode uit de interface van de controller.

### 7.3 GraphQL-schemabestanden (alle stacks)

**Leest:** `**/*.graphql`, `**/*.graphqls` en `**/*.gql`; bij Magento alleen in eigen modules.

| Bronvorm | Uitkomst |
|---|---|
| Elk veld onder `Query`, `Mutation` en `Subscription`, ook in `extend type`, en onder de typen die `schema { query: … }` noemt | Anker `graphql`, `method` `query`, `mutation` of `subscription`, `path` `Mutation.addTeamMember` |
| Magento: `@resolver(class: "Acme\\Notes\\Model\\Resolver\\AddNote")` | Handler: de methode `resolve` van die klasse |
| Lighthouse: `@field(resolver: "App\\GraphQL\\Mutations\\AddMember@handle")` | Handler: die methode |
| Lighthouse: `@all`, `@find`, `@first`, `@paginate`, `@create`, `@update`, `@upsert`, `@delete` | `symbol` is de directive, zonder citatie en zonder markering. Aanwijzing `operation` (`read`, `add`, `change`, `remove`) en `model` uit het argument `model` of uit het teruggegeven type |
| Lighthouse zonder directive | Handler `App\GraphQL\Queries\<Veld>` of `Mutations\<Veld>`, methode `__invoke`, als dat bestand bestaat |
| Argument met een `input`-type | `input_type`, en per veld een `input_rule` met het type als `value` (Lighthouse: de waarde van `@rules`) |
| Argument of invoerveld met een `enum`-type | `enum` |
| Geen handler gevonden | `unresolved` met `handler_not_found` |

**GraphQL-type als feittype (B31).** Een `type` wordt gekoppeld aan een bestaand feittype als zijn naam, als `key_segment`, gelijk is aan de term van een begrip in dezelfde repository. Dan is het een lagere bron: velden met dezelfde naam als een rol leveren een uitspraak over `mandatory` (`!`) en, bij een `enum`-type, over de waarden (§8). Is er geen koppeling, dan is het type zelf de hoogste bron en wordt het een tabel in het schema: een kolom per veld met een scalair of `enum`-type, de primaire sleutel op het veld `id` als dat het type `ID` heeft, en een *foreign key* voor een veld met een objecttype dat zelf een sleutel heeft. Niet gelezen als feittype: `Query`, `Mutation`, `Subscription`, `input`-typen, interfaces en unions.

**Fixtures `graphql_magento/`, `graphql_lighthouse/` en `graphql_plain/`:** een Magento-`schema.graphqls` met `@resolver` en `\\`, een Lighthouse-schema met `@create`, `@field` en `@rules`, en een los schema zonder handlers met een type `Team` dat aan een tabel koppelt, een type `Invoice` zonder tabel en een type `TeamConnection`. Moet aantonen: de handler van de Magento-resolver is gevonden ondanks het gat uit §6.1; `@create` geeft `operation` `add` zonder markering; het losse schema geeft `handler_not_found`; `Team` geeft een extra citatie of een `DivergentClaim`; `Invoice` wordt een feittype; `TeamConnection` is `technical`.

### 7.4 NestJS en class-validator

**Leest:** TypeScript-klassen met `@Controller` of `@Resolver`.

| Bronvorm | Anker |
|---|---|
| `@Controller('teams')` plus `@Get(':id')`, `@Post()`, `@Put`, `@Patch`, `@Delete`, `@All` op een methode | `http`; het pad is het voorvoegsel plus het pad van de methode, met `/` ervoor |
| `@Resolver()` plus `@Query()`, `@Mutation()`, `@Subscription()`, met of zonder naam | `graphql`, `path` `Mutation.<naam>`; zonder naam de naam van de methode |

- Bestaat het anker al uit een schemabestand (§7.3), dan is het hetzelfde id: de methode wordt de handler en de decorator een tweede citatie.
- **Aanwijzingen:** `operation`; `input_type` voor een parameter met `@Body()` of `@Args()` en een klasse als type; per eigenschap van die klasse een `input_rule` per decorator van class-validator (`@IsEmail()`, `@Length(1, 20)`); `enum` bij `@IsEnum(X)` als `X` te vinden is. De klasse wordt gevonden in hetzelfde bestand of via een relatieve import.
- **Markeert:** een pad dat geen letterlijke waarde is: `unresolved` met `dynamic_registration`. TypeScript zonder decorators (een *resolver map*) wordt niet herkend; een veld uit het schema houdt dan `handler_not_found` (B30).

**Fixture `nestjs/`:** een controller met vier methoden en een DTO in een ander bestand, een resolver die bij een schemabestand hoort, en een resolver zonder schemabestand. Moet aantonen: paden met voorvoegsel; de regels van de DTO als aanwijzingen; één anker, met twee citaties, voor het veld dat in beide bronnen staat.

### 7.5 Next.js en Zod

**Leest:** `app/**/route.{ts,js}` en `pages/api/**/*.{ts,js}`, ook onder `src/`, en bestanden die met `'use server'` beginnen.

| Bronvorm | Anker |
|---|---|
| `export async function POST(…)` of `export const GET = …` in `app/api/teams/[id]/route.ts` | `http`, pad `/api/teams/[id]`, één anker per geëxporteerde methode. Routegroepen `(naam)` vallen uit het pad |
| De standaardexport van `pages/api/teams/[id].ts` | `http`, pad `/api/teams/[id]`, `method` `ANY` |
| Een geëxporteerde `async`-functie in een bestand dat met `'use server'` begint | `action`, `path` `<bestand>#<naam>` |

- **Aanwijzingen:** `operation`; `input_type` voor `X.parse(…)` of `X.safeParse(…)` in de handler, als `X` een `z.object({ … })` is in hetzelfde bestand of in een relatief geïmporteerd bestand; per sleutel een `input_rule` met de keten als `value`.
- Een Zod-schema dat geen handler gebruikt, leest §2 niet. Het wordt nooit een feittype (B31).

**Fixture `nextjs/`:** twee `route.ts`-bestanden (één in een routegroep), één bestand onder `pages/api`, één bestand met `'use server'` en twee functies, en een Zod-schema in een ander bestand. Moet aantonen: de paden; `ANY`; twee ankers `action`; de aanwijzingen uit het geïmporteerde schema.

## 8. Overlappende bronnen (B31)

### 8.1 Rangorde

1. **Opslag:** SQL en migraties, `db_schema.xml`, EAV, Prisma, TypeORM. Binnen deze rang geldt deze volgorde.
2. **Model:** Eloquent.
3. **API-vorm:** GraphQL-type.

De hoogste bron die een tabel beschrijft, bepaalt het feittype, de rollen, verplicht en datatype. Voor elke uitspraak van een bron daaronder geldt:

| De lagere bron zegt | Gevolg |
|---|---|
| Hetzelfde als het model | Een extra citatie op hetzelfde element |
| Iets wat het model nog niet heeft (een relatie, een enum) | Een eigen regel, met alleen de citatie van die bron |
| Iets anders over een plek die al bezet is | Een `DivergentClaim`; het element blijft ongewijzigd |

Twee `value`-regels zijn gelijk als ze dezelfde waarden hebben, ongeacht de volgorde. Datatypen worden niet vergeleken (§4.3).

Hoe de bronnen binnen de rang opslag samenkomen:

- Elke opslaglezer bouwt per repository zijn eigen schema. Losse SQL is één schema; Laravel-migraties met hun schemadump zijn één schema (de SQL-lezer slaat `database/schema/*.sql` dan over); alle `db_schema.xml`-bestanden zijn één schema.
- EAV is geen overlap maar een aanvulling: het voegt kolommen toe aan de entiteitstabel van `db_schema.xml` (§6.6).
- Beschrijven twee opslaglezers dezelfde tabel, dan vult de eerste in de volgorde het model. De tabel van de tweede wordt omgezet in uitspraken: per kolom een uitspraak over `mandatory`, per beperking een uitspraak over de regel. Daarna geldt de tabel hierboven. Een kolom die alleen de tweede lezer kent, wordt geen rol: een rol toevoegen is aan de hoogste bron. Het feittype krijgt dan de markering `uncertain` met `column_only_in_lower_source` en de kolomnaam in `detail`.
- Hetzelfde mechanisme zet een gekoppeld GraphQL-type om in uitspraken (§7.3).

### 8.2 Een model aan een tabel koppelen

In deze volgorde; de eerste die slaagt, geldt:

1. een letterlijke naam in de bron: `protected $table = '…'` (Eloquent), `@Entity('…')` (TypeORM) of `@@map("…")` (Prisma);
2. de klassenaam in *snake case*, als een tabel precies zo heet;
3. alleen voor Eloquent: de klassenaam in *snake case* met een regelmatig Engels meervoud (`s`; `es` na `s`, `x`, `z`, `ch` of `sh`; `ies` voor een `y` na een medeklinker), als een tabel precies zo heet.

Lukt geen van de drie, dan is er geen koppeling en volgt `unresolved` met `model_table_unknown`. Onregelmatige meervouden (`person`, `people`) vragen dus een `$table`. Dezelfde regel 3 geldt voor `constrained()` zonder argument (§6.3).

## 9. Ingang en omgeving

### 9.1 Functie en CLI

```python
def extract_structure(project_root: Path, config: Config | None) -> StructureExtraction: ...
```

De kern is puur: hij krijgt de bestandslijst en de `RepositoryRef`-rijen en vraagt Git niets. Het lezen van Git gebeurt eromheen, zoals bij `build_contract` (`chunkhound/code_mapper/c4/contract.py:7-8`). Tests van lezers draaien de kern met een vaste commit.

CLI: een vierde vlag in de groep van `chunkhound domain` (`chunkhound/api/cli/parsers/domain_parser.py:15-18`):

```
chunkhound domain <hoofdmap> --extract-structure
```

- Schrijft de JSON van `dump_structure` naar stdout en niets anders. Opent geen database (de tak komt vóór `create_services` in `chunkhound/api/cli/commands/domain.py:90`).
- Exitcode 0 bij een uitvoer, ook als die markeringen bevat. Exitcode 2 met een melding op stderr bij een fout van de run (§9.2).
- Zonder vlag blijft de melding `extraction is not available yet` staan (`domain.py:40-42`): de volledige run komt pas met §4.
- §3 en §4 roepen de functie aan; ze lezen geen bestand. Opslaan en cachen is §8 (U8): de extractie leest alleen bestanden en is snel genoeg om elke run te draaien.

### 9.2 Repositories en commits

- **Repository van een pad:** `repository_lookup` (`contract.py:498`), dus de diepste map met `.git` op de route. De sleutel komt uit `repository_key` (`identity.py:34`).
- **`repository_key_collision`:** geven twee repositories dezelfde sleutel, dan stopt de run (§1-spec §6.1).
- **Commit:** `git rev-parse HEAD` per repository, via `run_git` (`chunkhound/utils/git_safe.py:80`). Een citatie eist een commit (`model.py:26`). Heeft een repository er geen, dan stopt de run met `repository_without_commit`.
- **`dirty`:** `True` als `git status --porcelain` een gelezen bestand noemt. De regelnummers komen dan uit de werkmap en kunnen van de commit afwijken.
- Een element hoort bij de repository van het bestand dat zijn tabel aanmaakt. Een *foreign key* naar een tabel in een andere repository is een `external_reference` met `table_not_found`; de koppeling is werk voor §5.

## 10. Verruiming van de sjabloonregel van §1 (B26)

`template_issues` (`loader.py:120-146`) eist nu dat elke rol in elk sjabloon staat (regels 137-145). Nieuwe regel:

- een invulplaats hoort bij een rol van het feittype, en een rol staat hooguit één keer in een sjabloon (ongewijzigd, regels 124-136);
- een sjabloon mag een deel van de rollen bevatten;
- alle sjablonen van een feittype dekken samen alle rollen. Ontbreekt een rol in elk sjabloon, dan is dat `template_role_mismatch` op het feittype, met de rol in de melding.

De functie wordt gedeeld met de schrijfdienst, dus de regel geldt ook voor `domain_write`. Wat nu geldig is, blijft geldig; er is geen migratie. De tekst van de §1-spec §4.2 is al aangepast. De beschrijving van `domain_write` (`chunkhound/mcp_server/tools.py:364`) noemt de nieuwe regel in één zin.

## 11. Gevolgen voor de andere secties

| Sectie | Wat §2 levert of verandert |
|---|---|
| §1 | Alleen de sjabloonregel verandert (§10). Er komen geen nieuwe elementsoorten, statussen of laadfouten bij. `DomainConfig` is nieuw en heeft in §2 één veld |
| §3 | Krijgt de kandidaten, de ankers met aanwijzingen en de markeringen. §3 schrijft de zinnen die de mechanische sjablonen vervangen, stelt domeinnamen voor, en maakt per anker één uitwisselingsregel of legt vast dat het anker geen domeinuitwisseling is. Een feittype met `uncertain` leest §3 zelf na via de citatie |
| §4 | Sluit `technical` uit, beslist over `third_party`, herkent een domeinnaam als hernoeming van de codenaam (B21), en weegt elke `DivergentClaim`. De run zonder vlag (`chunkhound domain <hoofdmap>`) komt in §4 |
| §5 | Krijgt per repository de `external_reference`-markeringen met `table_not_found` als kandidaten voor een koppeling over repositories heen |
| §7 | Kan dekking meten zonder LLM: ankers met en zonder uitwisselingsregel, tabellen met en zonder feittype in het model, en het aantal markeringen per `kind` en `reason` |
| §8 | Beslist of de uitvoer van §2 in de cache of het lockbestand komt. §2 bewaart niets |

## 12. Voorstellen in deze spec

Deze punten staan niet letterlijk in B26 tot en met B33. De eerste zes raken een eerder besluit; bij goedkeuring van deze spec komen ze als B34 in het besluitenlog.

| # | Voorstel | Waar | Raakt | Waarom |
|---|---|---|---|---|
| 1 | De rol heet naar de kolom, niet naar het begrip | §5.2 | B12, B26 | Een kolom zonder *foreign key* heeft geen bekend begrip, en twee verwijzingen naar dezelfde tabel zouden dezelfde naam krijgen. De kolomnaam is uniek en stabiel; het begrip staat in `Role.concept` |
| 2 | Het begrip "hoofdsjabloon" vervalt; bij `identifies` is het eerste sjabloon het identificerende | §5.4 | B25 punt 1, B26 | Met een sjabloon per kolom is er geen sjabloon met alle rollen meer |
| 3 | Een Eloquent-model zonder tabel in het schema levert geen feittype | §6.4 | B31 | Het model noemt zijn kolommen niet. Een feittype zonder rollen is geen kandidaat, en raden mag niet (invariant 7) |
| 4 | Magento-servicecontracten (`Api/Data/*Interface.php`) zijn alleen een aanwijzing `input_type`; validatie in `ui_component` wordt niet gelezen | §7.2, §15 | B31 | Getters zeggen niets over verplicht of sleutels. De tabel uit `db_schema.xml` is altijd de hogere bron |
| 5 | Ankersoort `action` voor Next.js Server Actions | §4, §7.5 | B27, B30 | Een Server Action is een ingang zonder pad of methode; zonder eigen soort valt hij buiten de dekking |
| 6 | De technische lijsten zijn langer dan de voorbeelden in B33 | §5.8 | B33 | Zelfde regel, meer namen: `password_resets`, Telescope en Pulse, `cache`, `session`, `indexer_state` en `mview_state` van Magento, Knex en Liquibase, en de omhullende GraphQL-typen |
| 7 | Een eigen uitvoervorm `StructureExtraction` naast `DomainModel`, met ankers, markeringen en afwijkende uitspraken | §4 | – | Het contract van §1 blijft ongewijzigd. Wat geen element is, hoort niet in het model |
| 8 | Elke opslaglezer levert bewerkingen op één tussenvorm; de vertaling staat op één plek | §3, §5.1 | – | De regel van B26 geldt zo voor elke bron, en een nieuwe lezer is klein |
| 9 | XML, Prisma en GraphQL gaan via de grammatica's die al meekomen met `tree_sitter_language_pack` | §6.1 | – | Geen nieuwe afhankelijkheid, regelnummers zonder extra werk, en geen entiteiten in XML |
| 10 | De inhoud van `CREATE TABLE` leest §2 met een eigen kleine lezer, niet met de SQL-grammatica en niet met `sqlglot` | §6.2 | – | De grammatica faalt op de vorm van `mysqldump`. `sqlglot` is een nieuwe afhankelijkheid voor één instructie |
| 11 | Regelmatig Engels meervoud bij het koppelen van een Eloquent-model en bij `constrained()`, alleen als de tabel bestaat | §8.2 | – | Het is de conventie van Laravel zelf. De controle op een bestaande tabel maakt er een regel van, geen gok |
| 12 | Volgorde binnen de rang opslag: SQL en migraties, `db_schema.xml`, Prisma, TypeORM | §8.1 | – | Wat het dichtst bij de database staat, gaat voor |
| 13 | Een GraphQL-type zonder gekoppelde tabel wordt zelf een feittype | §7.3 | – | B31 noemt de API-vorm als bron. Zonder hogere bron is hij de hoogste |
| 14 | Twee fouten stoppen de run: `repository_without_commit` en `repository_key_collision` | §9.2 | – | Zonder commit is geen citatie mogelijk; met gelijke sleutels zijn ids niet uniek |
| 15 | Een bestand uit `vendor/` krijgt de commit van de repository, plus de markering `third_party` | §6.5 | – | `Citation.commit` is verplicht. De markering zegt dat de inhoud niet in die commit zit |
| 16 | De ingang is een vlag `--extract-structure` die JSON naar stdout schrijft; er is geen MCP-tool | §9.1 | – | Genoeg om §2 te bekijken en te testen. §3 en §4 roepen de functie aan |
| 17 | Lezers worden gekozen op bestandspatroon, niet op een herkend framework | §6, §7 | – | Een lezer die niets vindt, kost bijna niets. Frameworkherkenning zou een tweede plek zijn waar iets stil kan missen |
| 18 | Grens van 10 MB per bestand | §6.1 | – | Een grote dump mag de run niet ophouden; de markering maakt het zichtbaar |

## 13. Testen

Tests staan in `tests/domain_model/structure/`. Ze draaien de pure kern op een fixturemap met een vaste commit, zonder Git, netwerk of database. Een test kijkt naar benoemde feiten in de uitvoer (dit id bestaat, deze markering staat erbij), niet naar de hele JSON. Alleen het voorbeeld uit §5.9 heeft een volledige verwachte uitvoer.

| Test | Contract |
|---|---|
| `test_templates_may_cover_a_subset_of_roles` | Een feittype met een sjabloon per rol laadt en is te schrijven met `domain_write` (§10) |
| `test_role_missing_from_every_template_is_rejected` | `template_role_mismatch` als een rol in geen enkel sjabloon staat (§10) |
| `test_structure_round_trips` | `parse_structure(dump_structure(x))` geeft `x`; een `subject` naar een onbekend id wordt geweigerd (§4) |
| `test_model_part_is_a_valid_domain_model` | Voor elke fixture: het modeldeel doorstaat `parse_model`, alles is `extracted`, met minstens één citatie (invariant 4) |
| `test_every_citation_points_at_existing_lines` | Voor elke fixture: elke citatie wijst naar regels die in het bestand bestaan (invariant 5) |
| `test_extraction_is_deterministic` | Twee runs geven byte-gelijke JSON, zonder absolute paden (invariant 3) |
| `test_extraction_writes_nothing` | De fixturemap is na de run ongewijzigd; er is geen `.chunkhound`-map en geen database (invariant 2) |
| `test_worked_example_matches_expected_json` | De uitvoer van §5.9 is gelijk aan `fixtures/example/expected.json` |
| `test_table_without_key_gets_no_concept`, `test_join_table_gets_no_concept` | De regels van §5.3 |
| `test_key_collision_is_reported` | Twee kolommen met hetzelfde `key_segment` geven één rol en één markering (§5.2) |
| Eén testbestand per lezer (`test_sql.py`, `test_laravel_migrations.py`, …) | De punten onder "Moet aantonen" van die lezer in §6 en §7, elk als eigen test met een contractnaam, zoals `test_named_foreign_key_in_dump_becomes_subset_rule` |
| `test_lower_source_agreeing_adds_a_citation`, `test_lower_source_disagreeing_becomes_divergent_claim`, `test_lower_source_adding_becomes_own_rule` | De drie gevallen van §8.1 |
| `test_technical_tables_follow_config` | `add` markeert een eigen patroon; `remove` haalt `sessions` van de lijst (§5.8) |
| `test_unreadable_file_does_not_stop_the_run` | Een bestand dat geen UTF-8 is of te groot is, geeft een markering; de andere lezers leveren hun uitvoer (invariant 11) |
| `test_repository_without_commit_stops_the_run`, `test_repository_key_collision_stops_the_run` | De twee fouten van §9.2, met een echte tijdelijke Git-repository |
| `test_cli_extract_structure_prints_json` | `chunkhound domain <map> --extract-structure` geeft geldige JSON op stdout, exitcode 0, en opent geen database (§9.1) |
| `test_cli_without_mode_still_reports_not_available` | Zonder vlag blijven de melding en exitcode 2 |

Bestaande tests van `index`, `map` en `autodoc` blijven ongewijzigd groen; dat dekt de tweede helft van invariant 2. De smoke-test en `uv run mypy chunkhound` draaien na elke fase.

## 14. Fasering

Elke fase is één pi-bolt-sessie op een eigen branch, met een eigen fixture en een eigen testbestand. Het plan werkt dit uit.

| Fase | Inhoud | Spec | Hangt af van | Model |
|---|---|---|---|---|
| 1 | Sjabloonregel van §1 verruimen | §10 | – | `gpt-6.1-terra` / `medium` |
| 2 | Uitvoercontract, bestanden, repositories en commits, `extract_structure` met een lege lijst lezers, CLI-vlag | §4, §6.1, §9 | – | `gpt-6.1-sol` / `medium` |
| 3 | Schema in het geheugen, vertaling naar §1-elementen, SQL-lezer voor `CREATE TABLE` | §5.1–§5.7, §6.2 | 1, 2 | `gpt-6.1-sol` / `high` |
| 4 | SQL: `ALTER` en de andere instructies, afspeelvolgorde, `uncertain`; technische lijsten en configuratie | §6.2, §5.8 | 3 | `gpt-6.1-sol` / `medium` |
| 5 | Laravel-migraties en schemadump; het voorbeeld van §5.9 | §6.3, §5.9 | 4 | `gpt-6.1-sol` / `high` |
| 6 | Eloquent-modellen, PSR-4-opzoeking, samenvoegen van bronnen | §6.4, §8 | 5 | `gpt-6.1-sol` / `high` |
| 7 | Magento: modules, `db_schema.xml`, `vendor/` één stap diep | §6.5 | 4 | `gpt-6.1-sol` / `medium` |
| 8 | Magento: EAV-attributen | §6.6 | 5, 7 | `gpt-6.1-sol` / `medium` |
| 9 | Prisma | §6.7 | 4 | `gpt-6.1-terra` / `medium` |
| 10 | TypeORM | §6.8 | 4 | `gpt-6.1-sol` / `medium` |
| 11 | Laravel-ankers: routes, commands, aanwijzingen uit `FormRequest` | §7 inleiding, §7.1 | 6 | `gpt-6.1-sol` / `high` |
| 12 | Magento-ankers: `webapi.xml`, `routes.xml` | §7.2 | 7, 11 | `gpt-6.1-sol` / `medium` |
| 13 | GraphQL-schemabestanden: ankers, handlers voor Magento en Lighthouse, type als feittype | §7.3 | 11, 12 | `gpt-6.1-sol` / `high` |
| 14 | NestJS (REST en GraphQL) en class-validator | §7.4 | 10, 13 | `gpt-6.1-sol` / `medium` |
| 15 | Next.js en Zod | §7.5 | 14 | `gpt-6.1-sol` / `medium` |

- Fasen 1 en 2 kunnen naast elkaar. Na fase 4 kunnen 5, 7, 9 en 10 naast elkaar, elk in een eigen worktree.
- Het enige gedeelde bestand is de lijst van lezers in `extract.py`: één regel per lezer, dus een conflict bij het samenvoegen is klein.
- Fase 12 hangt van 11 af omdat de vorm van ankers en aanwijzingen daar ontstaat. Fase 8 hangt van 5 af omdat de hulpfuncties voor PHP daar ontstaan.
- Na elke fase is `--extract-structure` bruikbaar voor de brontypen die er dan zijn.

## 15. Bewust niet

- **Geen gemeenschappelijk datatype over stacks heen.** `datatype` blijft de notatie van de bron (§5.5).
- **Geen uitwisselings-, afleidings- of eventregels, geen definities en geen zinnen.** Dat is §3 (B27).
- **Geen keuze bij tegenspraak en geen uitsluiting van techniek.** §2 markeert; §4 beslist (B31, B33).
- **Geen opslag van de uitvoer, geen cache en geen lockbestand.** Dat is §8.
- **Geen MCP-tool voor de extractie.**
- **Geen frameworkherkenning.** Lezers kiezen op bestandspatroon.
- **SQL:** geen views, triggers, procedures of gewone indexen; geen dialect dat niet in §6.2 staat.
- **Laravel:** geen voorvoegsel dat buiten het routebestand wordt gezet; geen `hasMany`, `belongsToMany` of polymorfe relaties; geen migraties uit pakketten in `vendor/`.
- **Magento:** geen bereik (*scope*) van een EAV-attribuut; geen attributen die de kern zelf aanmaakt; geen commands, cron of observers als anker; geen `Api/Data`-interface als feittype; geen `ui_component`; geen tweede stap in `vendor/` (B28).
- **TypeScript:** geen `@OneToMany`, `@ManyToMany` of `@JoinTable`; geen eigen naamstrategie; geen Express, Fastify, tRPC, Pothos of Nexus; geen *resolver map* zonder decorators; geen Zod-schema dat geen handler gebruikt.
- **GraphQL:** geen interfaces en unions als feittype; geen federatie-directives.
- **Geen andere stacks** dan PHP met Laravel, Magento, en TypeScript met NestJS of Next.js (routekaart, bereik van versie 1).


