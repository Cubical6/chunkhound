# Spec: §1 Metamodel en contract van het domeinmodel

- Datum: 2026-11-13 · Branch: `worktree-cogniam-plan` (HEAD bij start `f7a73dcb`)
- **Status:** concept, ter goedkeuring. De open punten uit de review zijn besloten (B24, B25, zie §10). Deze spec geeft geen toestemming voor implementatie of een push naar `main`.
- Bron: [routekaart §1](../plans/2026-11-12-cogniam-routekaart.md#1-metamodel-en-contract), besluiten B11 tot en met B25 in het [besluitenlog](../decisions/2026-11-12-cogniam-model.md), het [onderzoek naar het metamodel in het boek](../research/2026-11-12-cogniam-boek-metamodel.md) en de [CEM-werkwijze](../research/2026-11-12-cem-werkwijze.md).
- Aanhaakpunten zijn op `f7a73dcb` gelezen, niet gedraaid.

## 1. Probleem

Alle andere secties (§2 tot en met §10) hebben één datavorm nodig voor het kennismodel. Daarnaast moet een mens via Claude Code geplande elementen, voorbeeldfeiten en bevestigingen kunnen vastleggen (B15). Die invoer staat in de index-database (B16). Daar gaat ze vandaag verloren: de compactie gooit onbekende tabellen weg, in Python en in Rust.

## 2. Doel en afbakening

**Doel:** de datavorm van het model, stabiele id's, een lader die de vorm bewaakt, en een opslag voor menselijke invoer met één schrijfdienst. De opslag overleeft compactie, herindexering en upgrades.

**In scope:**
- de datavormen van de acht elementsoorten en het contract (§4, §5);
- de id's (§6);
- de lader met laadfouten (§7);
- de opslag van menselijke invoer (§8);
- de schrijfdienst met een CLI-opdracht en twee MCP-tools: `domain_write` om te schrijven en `domain_read` om te lezen (§9);
- tests (§12) en fasering (§13).

**Buiten scope:**
- het vinden van elementen in code (§2, §3);
- samenvoegen van gevonden elementen en menselijke invoer, en correcties zoals verwerpen, samenvoegen of hernoemen (§4). Deze spec levert wel de opslag waar die correcties later in komen;
- controles op het hele model (§6), testspecificaties (§7) en de plaats van het uitvoerbestand (§8);
- export en import van menselijke invoer (B20), en LanceDB (B23).

**Invarianten:**
1. **Geen bijwerking (U5).** Zolang niemand menselijke invoer schrijft, verandert er niets aan de database of aan de uitvoer van `map` en `autodoc`. De tabel ontstaat pas bij de eerste schrijfactie (§8.1).
2. **Geen element zonder bron (U2).** Elk element in het contract heeft minstens één citatie uit code of één record met menselijke invoer.
3. **`confirmed` alleen via een menselijk record (U1, B19).** Een element met status `confirmed` heeft een record met `op` `confirm`, of een `put` met status `confirmed`.
4. **Een bevestigd feittype heeft een voorbeeldfeit (B14).** Dat moet een geldig voorbeeldfeit zijn, dus een met lege `violates`. De schrijfdienst dwingt dit af en de lader controleert het.
5. **Het id volgt uit soort, repository en naam (B21).** Het is een pure functie en dus overal gelijk. De lader controleert elk id.
6. **Gerealiseerd betekent: minstens één citatie uit code (B23).** Dit wordt afgeleid en niet opgeslagen.
7. **Een schrijfactie is alles of niets.** Een afgewezen verzoek schrijft niets en geeft alle fouten terug, elk met een pad.
8. **Een schrijfactie is duurzaam zodra ze terugkomt.** Daarvoor volgt een `CHECKPOINT` (B23).
9. **De aanroeper kan de auteur niet invullen (B18).**
10. **Menselijke invoer overleeft** de compactie (Python en Rust), het verwijderen van een WAL-bestand, `--force-reindex` en een upgrade van ChunkHound.
11. **Serialisatie is deterministisch.** Een gelijk model geeft byte-gelijke JSON.
12. **Records worden gebundeld geschreven.** Er komen geen inserts van één rij in een lus (`AGENTS.md`).

## 3. Kennisdriehoek (B23)

Er komt geen veld `level`. De drie niveaus van het boek (p.5, figuur 1.1) zitten zo in het model:

| Niveau | In het model |
|---|---|
| I, feiten | `ground_facts` |
| II, domeinspecifiek | De zeven andere elementsoorten |
| III, generiek | Het schema van het contract met de controles van de lader (§7) en van §6 |

## 4. Datavormen

Module: `chunkhound/domain_model/`. De datavormen zijn pydantic-modellen met `frozen=True` en `extra="forbid"`, net als `c4/model.py:33-34`. Daarom zijn ze tegelijk dataclass en JSON-schema: de lader en de schrijfdienst krijgen er precieze foutpaden bij (`ValidationError.errors()[].loc`), en een agent kan het schema lezen (§9.4). Alle namen komen uit de woordenlijst van B22.

### 4.1 Gedeelde delen

```python
SCHEMA_VERSION = 1

Status = Literal["extracted", "proposed", "confirmed"]          # U1, eerste as
EntryPoint = Literal["cli", "mcp"]                              # B18
HumanOp = Literal["put", "confirm", "unconfirm", "delete"]

class Citation(BaseModel):          # U2
    repository: str                 # repositorysleutel (§6.1)
    path: str                       # POSIX, relatief aan de hoofdmap
    start_line: int                 # >= 1
    end_line: int                   # >= start_line
    commit: str                     # hex, 7 tot 40 tekens

class CodeBinding(BaseModel):       # B12: koppeling naar code
    repository: str
    target: str                     # tabel of model ("team_user"), of veld ("team_user.user_id")
    citation: Citation

class HumanSource(BaseModel):       # B18
    record: int                     # seq in domain_input (§8.1)
    op: HumanOp
    put_status: Literal["proposed", "confirmed"] | None   # alleen bij op == "put", anders None
    author_name: str
    author_email: str | None
    entry_point: EntryPoint
    recorded_at: str                # ISO 8601 in UTC, met "Z"
```

Elk element heeft deze velden:

| Veld | Type | Betekenis |
|---|---|---|
| `id` | `str` | Volgens §6 |
| `repository` | `str` | Repositorysleutel (§6.1) |
| `status` | `Status` | Wie ervoor instaat (U1) |
| `citations` | `tuple[Citation, ...]` | Bronnen in code |
| `human_sources` | `tuple[HumanSource, ...]` | Records met menselijke invoer sinds de laatste `delete` |

Gepland of gerealiseerd is een afgeleide eigenschap, geen veld: `is_realized = len(citations) > 0` (B23). Een citatie in een `CodeBinding` telt ook, omdat dezelfde citatie ook in `citations` staat.

### 4.2 Elementsoorten

| Soort (boek) | Klasse | Eigen velden |
|---|---|---|
| BO | `Concept` | `term: str`, `plural: str \| None`, `definition: str \| None`, `synonyms: tuple[str, ...]` |
| ZS | `FactType` | `name: str`, `templates: tuple[str, ...]` (minstens één; de eerste is het hoofdsjabloon, de rest zijn synoniemen), `roles: tuple[str, ...]` (rol-id's in volgorde van positie), `identifies: str \| None` (concept-id als dit het identificerende feittype van dat begrip is), `bindings: tuple[CodeBinding, ...]` |
| VAR | `Role` | `fact_type: str`, `name: str` (uniek binnen het feittype, B12), `concept: str \| None`, `datatype: str \| None` (zoals in de bron, niet genormaliseerd), `mandatory: bool \| None` (`None` = onbekend), `bindings: tuple[CodeBinding, ...]` |
| VR | `ValidationRule` | `fact_type: str`, `rule_kind: Literal["uniqueness", "subset", "value", "other"]`, `roles: tuple[str, ...]` (rol-id's), `superset_fact_type: str \| None`, `superset_roles: tuple[str, ...]`, `allowed_values: tuple[str, ...]`, `name: str \| None` (verplicht bij `other`), `statement: str \| None` |
| AR | `DerivationRule` | `name: str`, `statement: str`, `derives: tuple[str, ...]` (id's van feittypen of rollen), `uses: tuple[str, ...]` |
| UR | `ExchangeRule` | `name: str`, `statement: str`, `operations: tuple[Literal["add", "change", "remove"], ...]` (minstens één), `fact_types: tuple[str, ...]` |
| ER | `EventRule` | `name: str`, `statement: str`, `event: str` (wanneer, in woorden), `starts: tuple[str, ...]` (id's van uitwisselings- of afleidingsregels) |
| niveau I | `GroundFact` | `fact_type: str`, `values: Mapping[str, str \| int \| float \| bool \| None]` (rolnaam → waarde), `violates: tuple[str, ...]` (regel-id's; leeg = geldig feit) |

Toelichting:
- **Sjablonen.** Een sjabloon bevat invulplaatsen `<rolnaam>`. Elke rol van het feittype komt in elk sjabloon precies één keer voor, en elke invulplaats hoort bij een rol (B12). Een rolnaam bevat geen `<`, `>` of regeleinde.
- **Identificerend sjabloon.** Dat is het sjabloon van een feittype met `identifies`, zoals in de CEM, waar elk begrip een eigen elementair feittype krijgt.
- **Verplicht en datatype** zijn kenmerken van de rol (B13). Ze zijn geen `ValidationRule`. §7 test ze onder een afgeleid id (§6.2).
- **Regelsoorten** volgen de CEM: uniciteit, deelverzameling en waardenregel. Al het andere valt onder `other`, met een naam en een `statement`. Gelijkheid (`gl` in het boek) is nog niet nagelezen en komt pas na controle tegen de scans. Een regelsoort toevoegen vraagt geen migratie.
- **Tegenvoorbeeld.** Een voorbeeldfeit met `violates` is een tegenvoorbeeld: zo toetst de CEM met varianten welke rollen uniek zijn. Volgens het boek (p.234) en §7 is dat een concreet voorbeeld met een verwachte uitkomst.

### 4.3 Model

```python
class DomainModel(BaseModel):
    schema_version: Literal[1]
    concepts: tuple[Concept, ...]
    fact_types: tuple[FactType, ...]
    roles: tuple[Role, ...]
    validation_rules: tuple[ValidationRule, ...]
    derivation_rules: tuple[DerivationRule, ...]
    exchange_rules: tuple[ExchangeRule, ...]
    event_rules: tuple[EventRule, ...]
    ground_facts: tuple[GroundFact, ...]
```

Elke lijst staat gesorteerd op `id`. De lijsten staan per soort, zodat het `kind` uit de sleutel volgt en er geen gediscrimineerde unie nodig is in het contract.

## 5. JSON-contract: voorbeeld

Het voorbeeld laat drie situaties zien:
- een gevonden feittype (`team_user` uit een migratie) dat een mens via de MCP-tool bevestigde;
- een geplande regel die alleen als menselijke invoer bestaat;
- een voorbeeldfeit.

Commits zijn ingekort ter illustratie. De hashes in de id's van de voorbeeldfeiten zijn echt berekend volgens §6.2, net als die in §9.1.

```json
{
  "schema_version": 1,
  "concepts": [
    {
      "id": "concept:backend/team",
      "repository": "backend",
      "term": "team",
      "plural": "teams",
      "definition": "A group of users who handle tickets together.",
      "synonyms": [],
      "status": "extracted",
      "citations": [
        {"repository": "backend", "path": "backend/app/Models/Team.php", "start_line": 9, "end_line": 41, "commit": "3f2a9c1"}
      ],
      "human_sources": []
    },
    {
      "id": "concept:backend/user",
      "repository": "backend",
      "term": "user",
      "plural": "users",
      "definition": "A person with an account in the ticket system.",
      "synonyms": ["account holder"],
      "status": "extracted",
      "citations": [
        {"repository": "backend", "path": "backend/app/Models/User.php", "start_line": 12, "end_line": 48, "commit": "3f2a9c1"}
      ],
      "human_sources": []
    }
  ],
  "fact_types": [
    {
      "id": "fact_type:backend/team-membership",
      "repository": "backend",
      "name": "team membership",
      "templates": ["User <member> belongs to team <team>."],
      "roles": ["role:backend/team-membership/member", "role:backend/team-membership/team"],
      "identifies": null,
      "bindings": [
        {"repository": "backend", "target": "team_user",
         "citation": {"repository": "backend", "path": "backend/database/migrations/2024_01_10_create_team_user_table.php", "start_line": 14, "end_line": 22, "commit": "3f2a9c1"}}
      ],
      "status": "confirmed",
      "citations": [
        {"repository": "backend", "path": "backend/database/migrations/2024_01_10_create_team_user_table.php", "start_line": 14, "end_line": 22, "commit": "3f2a9c1"}
      ],
      "human_sources": [
        {"record": 12, "op": "confirm", "put_status": null, "author_name": "A. Developer", "author_email": "dev@example.com", "entry_point": "mcp", "recorded_at": "2026-11-12T14:03:22Z"}
      ]
    }
  ],
  "roles": [
    {
      "id": "role:backend/team-membership/member",
      "repository": "backend",
      "fact_type": "fact_type:backend/team-membership",
      "name": "member",
      "concept": "concept:backend/user",
      "datatype": "bigint",
      "mandatory": true,
      "bindings": [
        {"repository": "backend", "target": "team_user.user_id",
         "citation": {"repository": "backend", "path": "backend/database/migrations/2024_01_10_create_team_user_table.php", "start_line": 16, "end_line": 16, "commit": "3f2a9c1"}}
      ],
      "status": "confirmed",
      "citations": [
        {"repository": "backend", "path": "backend/database/migrations/2024_01_10_create_team_user_table.php", "start_line": 16, "end_line": 16, "commit": "3f2a9c1"}
      ],
      "human_sources": [
        {"record": 12, "op": "confirm", "put_status": null, "author_name": "A. Developer", "author_email": "dev@example.com", "entry_point": "mcp", "recorded_at": "2026-11-12T14:03:22Z"}
      ]
    },
    {
      "id": "role:backend/team-membership/team",
      "repository": "backend",
      "fact_type": "fact_type:backend/team-membership",
      "name": "team",
      "concept": "concept:backend/team",
      "datatype": "bigint",
      "mandatory": true,
      "bindings": [
        {"repository": "backend", "target": "team_user.team_id",
         "citation": {"repository": "backend", "path": "backend/database/migrations/2024_01_10_create_team_user_table.php", "start_line": 17, "end_line": 17, "commit": "3f2a9c1"}}
      ],
      "status": "confirmed",
      "citations": [
        {"repository": "backend", "path": "backend/database/migrations/2024_01_10_create_team_user_table.php", "start_line": 17, "end_line": 17, "commit": "3f2a9c1"}
      ],
      "human_sources": [
        {"record": 12, "op": "confirm", "put_status": null, "author_name": "A. Developer", "author_email": "dev@example.com", "entry_point": "mcp", "recorded_at": "2026-11-12T14:03:22Z"}
      ]
    }
  ],
  "validation_rules": [
    {
      "id": "validation_rule:backend/team-membership/other/one-lead-per-team",
      "repository": "backend",
      "fact_type": "fact_type:backend/team-membership",
      "rule_kind": "other",
      "roles": ["role:backend/team-membership/team"],
      "superset_fact_type": null,
      "superset_roles": [],
      "allowed_values": [],
      "name": "one lead per team",
      "statement": "A team has at most one member with the lead role.",
      "status": "proposed",
      "citations": [],
      "human_sources": [
        {"record": 13, "op": "put", "put_status": "proposed", "author_name": "A. Developer", "author_email": "dev@example.com", "entry_point": "mcp", "recorded_at": "2026-11-12T14:05:10Z"}
      ]
    },
    {
      "id": "validation_rule:backend/team-membership/uniqueness/member+team",
      "repository": "backend",
      "fact_type": "fact_type:backend/team-membership",
      "rule_kind": "uniqueness",
      "roles": ["role:backend/team-membership/member", "role:backend/team-membership/team"],
      "superset_fact_type": null,
      "superset_roles": [],
      "allowed_values": [],
      "name": null,
      "statement": null,
      "status": "extracted",
      "citations": [
        {"repository": "backend", "path": "backend/database/migrations/2024_01_10_create_team_user_table.php", "start_line": 19, "end_line": 19, "commit": "3f2a9c1"}
      ],
      "human_sources": []
    }
  ],
  "derivation_rules": [],
  "exchange_rules": [
    {
      "id": "exchange_rule:backend/add-team-member",
      "repository": "backend",
      "name": "add team member",
      "statement": "A team lead adds a user to the team.",
      "operations": ["add"],
      "fact_types": ["fact_type:backend/team-membership"],
      "status": "proposed",
      "citations": [
        {"repository": "backend", "path": "backend/app/Http/Controllers/TeamMemberController.php", "start_line": 21, "end_line": 39, "commit": "3f2a9c1"}
      ],
      "human_sources": []
    }
  ],
  "event_rules": [],
  "ground_facts": [
    {
      "id": "ground_fact:backend/team-membership/d0480d33ce24",
      "repository": "backend",
      "fact_type": "fact_type:backend/team-membership",
      "values": {"member": "42", "team": "7"},
      "violates": [],
      "status": "proposed",
      "citations": [],
      "human_sources": [
        {"record": 11, "op": "put", "put_status": "proposed", "author_name": "A. Developer", "author_email": "dev@example.com", "entry_point": "mcp", "recorded_at": "2026-11-12T14:02:47Z"}
      ]
    }
  ]
}
```

Wat het voorbeeld laat zien:
- **Gerealiseerd en gepland.** De regel `one-lead-per-team` heeft geen citatie, dus is ze gepland. De andere elementen hebben er wel een en zijn gerealiseerd.
- **Bevestiging.** Record 12 bevestigt het feittype. Dat mag (B14), omdat er een geldig voorbeeldfeit is (record 11). De bevestiging geldt ook voor de rollen van het feittype (§9.2).
- **Serialisatie.** `dump_model` volgt deze regels:
  - de sleutels van een element staan in een vaste volgorde: eerst `id` en `repository`, dan de eigen velden in de volgorde van §4.2, en dan `status`, `citations` en `human_sources`. Dat is niet vanzelf de volgorde van pydantic, want bij overerving komen de basisvelden eerst;
  - de geneste objecten volgen de volgorde van §4.1, de sleutels van `values` zijn gesorteerd, en de lijsten zijn gesorteerd op `id`;
  - de JSON wordt geschreven met `ensure_ascii=False` en `indent=2`, en eindigt op een regeleinde.

  Voor de leesbaarheid staan citaties en koppelingen hierboven op één regel. `dump_model` schrijft ze met `indent=2` uit. De testfixture is daarom de uitvoer van `dump_model` voor dit voorbeeld, niet de tekst hierboven.

## 6. Identiteit (B21, B22)

Module: `chunkhound/domain_model/identity.py`. Het patroon is `c4/identity.py:25` (`element_id` = voorvoegsel + `slugify_kebab(term, ascii_only=True)`).

### 6.1 Bouwstenen

- **`key_segment(text)`** werkt in drie stappen:
  1. NFKD-normalisatie, waarbij combinerende tekens wegvallen, zodat `categorieën` wordt `categorieen`;
  2. `slugify_kebab(text, ascii_only=True, fallback="")` (`utils/text.py:10`);
  3. bij een leeg resultaat de fout `empty_key`, want de standaard-fallback `"topic"` van `slugify_kebab` zou stil een id maken.

  De functie is idempotent: `key_segment(key_segment(x)) == key_segment(x)`. Dit wijkt af van C4. Domeintermen zijn vaak Nederlands, en zonder NFKD wordt `categorieën` `categorie-n`.
- **Repositorysleutel.**
  - De bron is het repository-id van C4: het pad relatief aan de hoofdmap, of `.` voor de hoofdmap zelf (`c4/contract.py:39`, `:498`).
  - De sleutel is `root` voor `.` en anders `key_segment(pad)`, dus `services/backend` wordt `services-backend`.
  - Omdat `key_segment` idempotent is, accepteert de schrijfdienst een pad of een sleutel.
  - Geven twee repositories dezelfde sleutel (bijvoorbeeld `services/backend` en `services-backend`, of een map die `root` heet), dan stopt de run in §2 met de fout `repository_key_collision`.
- **Gepland element zonder bekende repository** (het open punt uit B21, besloten in B25): de schrijfdienst gebruikt standaard `.`, dus `root`. Dat betekent "nog niet geplaatst". Komt het element later in een repository, dan krijgt het een ander id, en §4 herkent dat als hernoeming of koppeling.

### 6.2 Sleutel per soort

| Soort | Id | Voorbeeld |
|---|---|---|
| `concept` | `concept:<repo>/<term>` | `concept:backend/user` |
| `fact_type` | `fact_type:<repo>/<name>` | `fact_type:backend/team-membership` |
| `role` | `role:<repo>/<fact type>/<name>` | `role:backend/team-membership/member` |
| `validation_rule`, soort `uniqueness`, `subset` of `value` | `validation_rule:<repo>/<fact type>/<rule_kind>/<rollen>` | `validation_rule:backend/team-membership/uniqueness/member+team` |
| `validation_rule`, soort `other` | `validation_rule:<repo>/<fact type>/other/<name>` | `validation_rule:backend/team-membership/other/one-lead-per-team` |
| Afgeleid, alleen voor §7 (B13) | `validation_rule:<repo>/<fact type>/mandatory/<rol>` en `…/datatype/<rol>` | `validation_rule:backend/team-membership/mandatory/member` |
| `derivation_rule`, `exchange_rule`, `event_rule` | `<kind>:<repo>/<name>` | `exchange_rule:backend/add-team-member` |
| `ground_fact` | `ground_fact:<repo>/<fact type>/<hash>` | `ground_fact:backend/team-membership/d0480d33ce24` |

Regels voor de opbouw:
- Elk deel tussen `/` is een `key_segment`. Daarom bevat een deel nooit `/`, `:` of `+`.
- `<fact type>` is het laatste deel van het id van het feittype. Rollen, regels en voorbeeldfeiten erven de repository van hun feittype.
- `<rollen>` zijn de sleutels van de rolnamen, gesorteerd en verbonden met `+`. Een `value`-regel heeft precies één rol.
- Twee `subset`-regels op dezelfde rollen naar verschillende verzamelingen geven hetzelfde id, dus de fout `duplicate_id`. Gebruik in dat zeldzame geval `other` met een naam.
- `<hash>` bestaat uit de eerste 12 hex-tekens van SHA-256 over de UTF-8-bytes van `json.dumps({"values": values, "violates": sorted(violates)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. De sleutels van `values` zijn de rolnamen zoals ze in het feittype staan. Een geldig feit en een tegenvoorbeeld met dezelfde waarden krijgen zo elk een eigen id. Controle: `{"member": "42", "team": "7"}` zonder `violates` geeft `d0480d33ce24`.
- De sleutels `mandatory` en `datatype` zijn gereserveerd. Een opgeslagen regel met die soort is een fout: `derived_rule_kind`.
- De voorbeelden in B21 (`uniqueness:backend/role-assignment/user+role` en `mandatory:backend/role-assignment/user`) staan hier in de vorm van B22. Het voorvoegsel is de soort `validation_rule`, en de regelsoort wordt het deel na het feittype: `validation_rule:backend/role-assignment/uniqueness/role+user`. De rollen zijn gesorteerd.
- `parse_id(id)` geeft `(kind, repository, segments)` terug, of de fout `invalid_reference`.
- Een hernoeming geeft een nieuw id (B21). §4 herkent dat.

## 7. Lader en laadfouten

Modules: `chunkhound/domain_model/issues.py` (`Issue` en `ModelLoadError`, die ook de schrijfdienst gebruikt) en `chunkhound/domain_model/loader.py`. Het patroon is `autodoc/architecture/loader.py`: een vaste schemaversie (`:28`), een eigen fout (`:31`) en `_read_model` (`:134`). Er zijn twee verschillen:
- de lader **gooit een fout** in plaats van `None` terug te geven, omdat §6 en §7 een model nodig hebben;
- elke fout heeft een **JSON-pad** in plaats van een platte sleutel.

```python
@dataclass(frozen=True)
class Issue:
    path: str        # "fact_types[0].templates[0]", "operations[1].element.roles[0].name"
    code: str        # stabiele code, zie de tabellen hieronder
    message: str     # Engels, met de verwachte waarde of de geldige keuzes

class ModelLoadError(ValueError):
    issues: tuple[Issue, ...]

def parse_model(data: object) -> DomainModel: ...   # gooit ModelLoadError
def load_model(path: Path) -> DomainModel: ...      # plus OSError/JSON-fouten als ModelLoadError
def dump_model(model: DomainModel) -> str: ...      # deterministisch (invariant 11)
```

De lader verzamelt alle fouten en stopt niet bij de eerste. In de foutmelding staan de eerste 20, met het totaal erbij.

| Code | Wanneer | Invariant |
|---|---|---|
| `unsupported_schema_version` | `schema_version` ontbreekt of is niet 1 | – |
| `missing_field`, `unknown_field`, `invalid_value` | Vormfout volgens pydantic (`loc` wordt het pad) | – |
| `invalid_json` | Het bestand is geen JSON of geen UTF-8 | – |
| `duplicate_id` | Een id komt twee keer voor | 5 |
| `id_mismatch` | Het id verschilt van de sleutel uit §6.2, of `repository` verschilt van het id | 5 |
| `empty_key` | Een naam of term geeft een lege sleutel (§6.1) | 5 |
| `invalid_reference` | Een verwijzing is geen id volgens §6.2 (`parse_id` faalt), of wijst naar een id van de verkeerde soort, zoals een concept-id in `violates` | – |
| `dangling_reference` | Een verwijzing (`fact_type`, `roles`, `concept`, `identifies`, `superset_*`, `derives`, `uses`, `fact_types`, `starts`, `violates`) wijst naar een id dat niet in het model staat. Afgeleide id's in `violates` (§6.2) zijn toegestaan | – |
| `role_mismatch` | `FactType.roles` en `Role.fact_type` spreken elkaar tegen | – |
| `template_role_mismatch` | Een invulplaats zonder rol, een rol die in een sjabloon ontbreekt, of een dubbele invulplaats | – |
| `unknown_role` | Een sleutel in `GroundFact.values` is geen rolnaam van het feittype | – |
| `rule_shape` | Een `uniqueness`-regel zonder rol, een `value`-regel met meer dan één rol, een `subset`-regel zonder verzameling of met een ander aantal rollen, of een `other`-regel zonder naam | – |
| `derived_rule_kind` | `rule_kind` is `mandatory` of `datatype` | B13 |
| `invalid_line_range` | `start_line < 1` of `end_line < start_line` | – |
| `binding_citation_missing` | De citatie van een `CodeBinding` staat niet ook in `citations` van hetzelfde element | 6 |
| `missing_source` | Geen citatie en geen `human_sources` | 2 |
| `confirmed_without_human_source` | Status `confirmed`, maar geen `human_source` met `op` `confirm`, en ook geen met `op` `put` en `put_status` `confirmed` | 3 |
| `confirmed_without_ground_fact` | Een bevestigd feittype zonder geldig voorbeeldfeit | 4 |

`repository_key_collision` (§6.1) is geen laadfout, maar een fout van de run in §2. De schrijfdienst (§9.2) gebruikt dezelfde codes als de lader waar het om dezelfde fout gaat.

§4 moet daarom altijd een samenhangend model maken: een verwijzing naar een element dat uit de code verdween, wordt daar een bevinding en geen kapotte verwijzing.

## 8. Opslag van menselijke invoer (B15, B16, B23)

### 8.1 Tabel

Er is één tabel, met alleen toevoegingen. De huidige stand volgt uit het afspelen van de records op volgorde van `seq`. Een correctie uit §4, zoals verwerpen, samenvoegen of hernoemen, wordt later een nieuwe waarde van `op` met een eigen `payload`, zonder migratie.

```sql
CREATE TABLE IF NOT EXISTS domain_input (
    seq             BIGINT    PRIMARY KEY,   -- max(seq) + 1 binnen de transactie; geen sequence
    batch_id        VARCHAR   NOT NULL,      -- uuid4 per schrijfverzoek
    op              VARCHAR   NOT NULL,      -- put | confirm | unconfirm | delete
    element_id      VARCHAR   NOT NULL,
    payload         VARCHAR,                 -- canonieke JSON van de put-body; NULL bij de andere ops
    payload_version INTEGER   NOT NULL,      -- 1
    author_name     VARCHAR   NOT NULL,
    author_email    VARCHAR,
    entry_point     VARCHAR   NOT NULL,      -- cli | mcp
    recorded_at     TIMESTAMP NOT NULL       -- UTC
)
```

Keuzes:
- **Prefix `domain_`.** Alle tabellen van deze feature beginnen met `domain_`. Alleen die tabellen neemt de compactie mee (§8.3).
- **Geen sequence en geen `JSON`-type.** Een tabel met alleen gewone kolommen laat zich generiek kopiëren, ook vanuit Rust, waar de JSON-extensie misschien ontbreekt. `seq` is veilig zonder sequence, omdat alle databasewerk over één executor-thread loopt (`serial_executor.py`) en DuckDB per bestand één proces toelaat.
- **Pas aanmaken bij de eerste schrijfactie** (invariant 1). `_executor_create_schema` (`duckdb_provider.py:1603`) verandert niet. Lezen zonder tabel geeft een lege stand.
- **Afspelen** levert per `element_id` het volgende op:
  - de laatste `put` sinds de laatste `delete`;
  - de vlag `confirmed`: die volgt de laatste `confirm` of `unconfirm`, of de status van de laatste `put`, en een `delete` zet haar uit;
  - alle records sinds de laatste `delete`, als `human_sources`.

  Een record op een feittype geldt ook voor zijn rollen. Een rol krijgt de records van haar feittype in `human_sources`, plus haar eigen records, en volgt de bevestiging van het feittype tenzij er een eigen `confirm` of `unconfirm` later komt. Voor rollen uit de menselijke invoer doet het afspelen dat. Voor gevonden rollen doet §4 het; zo komen de rollen in het voorbeeld van §5 aan record 12.

  Een id met een bevestiging maar zonder `put` is een **oordeel** over een gevonden element. §4 past dat oordeel toe.

### 8.2 Providermethoden

De SQL staat in de provider, net als de andere databasecode. De domeinmodule roept alleen deze methoden aan:

| Methode | Werking | Aanhaakpunt |
|---|---|---|
| `supports_domain_input: bool` | `True` op DuckDB, `False` op LanceDB en standaard | Patroon `supports_rust_pipeline`, `interfaces/database_provider.py:41`, `duckdb_provider.py:342` |
| `append_domain_input(rows) -> list[int]` | Executor-operatie `_executor_append_domain_input`:<br>1. `CREATE TABLE IF NOT EXISTS`, plus later `ALTER TABLE … ADD COLUMN IF NOT EXISTS`;<br>2. `BEGIN`;<br>3. `max(seq)` lezen;<br>4. **één** `INSERT` met meerdere rijen;<br>5. `COMMIT`;<br>6. `CHECKPOINT`.<br>Geeft de `seq`-nummers terug. | `_execute_in_db_thread_sync` (`serial_database_provider.py:198`). Voor de `CHECKPOINT` het patroon van `_executor_commit_transaction(force_checkpoint)` (`duckdb_provider.py:4749`) |
| `load_domain_input() -> list[dict]` | Alle records op volgorde van `seq`. Geeft `[]` zonder tabel | idem |

De operatienamen beginnen niet met `insert`, `update`, enzovoort. Een schrijfactie start dus geen steekproef voor automatische compactie (`serial_executor.py:103`, `:106`).

### 8.3 Hoe de invoer alles overleeft

| Gebeurtenis | Wat er nu gebeurt | Wijziging | Test (§12) |
|---|---|---|---|
| Compactie in Python (`_compact_copy_data`, `duckdb_provider.py:1217`), ook automatisch met kans 1/100 (`serial_executor.py:49`) | Onbekende tabellen vallen weg, met een waarschuwing (`:1322`) | Vóór de `known`-set (`:1322`): elke brontabel met naam `domain_%` opnieuw aanmaken met haar eigen DDL uit `duckdb_tables().sql`, dan `INSERT INTO t SELECT * FROM src.t`, en de naam toevoegen aan `known` | `test_human_input_survives_python_compaction` |
| Compactie in Rust (`run_attach_copy_compaction`, `compaction.rs:32`), aan het eind van een indexrun | Alleen `files`, `chunks`, `schema_version` en `embeddings_*` (`:88-96`) | Dezelfde generieke kopie na de lus over de embedding-tabellen, vóór `DETACH src` (`:180`). `SELECT *` is hier veilig, omdat de DDL uit de bron zelf komt. Rust hoeft het domeinschema dus niet te kennen. Volgens de `RUST_RULES` | `compaction_preserves_domain_tables` (Rust), `test_human_input_survives_rust_compaction` |
| Andere tabellen dan `domain_%` | Vallen weg | Geen | Bestaande test `test_unknown_tables_are_dropped_during_compaction` (`tests/test_duckdb_compaction.py:475`) blijft groen |
| Een WAL-bestand ouder dan 24 uur, of een ongeldig WAL-bestand, wordt bij het openen verwijderd: in de provider (`duckdb_provider.py:530`, `:540-546`) en al eerder in `_preemptive_wal_cleanup` (`duckdb/connection_manager.py:244`) | Niet-gecheckpointe invoer gaat verloren | `CHECKPOINT` in `append_domain_input` | `test_human_input_survives_wal_removal` |
| `--force-reindex` (`pipeline_bridge.py:890`) | Zet alleen `incremental=False`. Rust verwijdert alleen rijen uit `files`, `chunks` en `embeddings_*` (`src/db/duckdb_backend/write.rs:266-488`, `delete_paths` en `pre_delete_for_upsert`) | Geen | `test_human_input_survives_force_reindex` |
| Upgrade van ChunkHound | – | Tabelwijzigingen alleen via idempotente DDL bij het schrijven en lezen. Een payload uit een oudere versie wordt bij het lezen opgewaardeerd (`upgrade_payload(version, payload)`), en oude rijen worden nooit herschreven | `test_human_input_from_payload_version_1_loads` |
| Downgrade naar een versie zonder deze feature | De oude compactie gooit `domain_input` weg | Geen. Dit staat in de documentatie, met het advies voor een back-up (B20) | – |
| `.chunkhound/` weggooien | Alles weg | Geen (B20) | – |
| Herstel na een onderbroken compactie (`duckdb/connection_manager.py:193-242`) | Zet de oude database terug, inclusief `domain_input` | Geen | Valt onder de bestaande herstel-tests |

Over `schema_version`: dit **wijkt af** van een bevinding in de routekaart ("migratie via `schema_version`"). Die tabel heeft alleen een rij "Initial schema" (`duckdb_provider.py:1670`), en geen code handelt op de waarde. ChunkHound migreert al idempotent, zie `_executor_migrate_schema` (`:1682`) en `ADD COLUMN IF NOT EXISTS` in `duckdb_provider.py:1553` en `src/db/duckdb_backend/schema.rs:72`. Een rij in `schema_version` zou een migratieraamwerk introduceren dat nergens voor nodig is. De versie per rij (`payload_version`) dekt de upgrades van de inhoud.

## 9. Schrijfdienst (B17, B18, B19, B24)

Module: `chunkhound/domain_model/human_input.py` (verzoekmodellen, controle, afspelen) en `chunkhound/domain_model/author.py`.

```python
# publiek: de ingangen roepen alleen deze twee aan
def write_human_input(request: WriteRequest | dict, *, provider, project_root: Path,
                      entry_point: EntryPoint, dry_run: bool = False) -> WriteResult
def load_human_input(provider) -> HumanInputView    # elementen + oordelen

# intern: write_human_input lost de auteur op (§9.3) en roept dit aan
def apply_write(request, *, provider, author: Author, entry_point, dry_run) -> WriteResult
```

De publieke functie heeft geen parameter voor de auteur (invariant 9).

### 9.1 Verzoek

```python
class WriteRequest(BaseModel):          # extra="forbid"
    operations: list[Operation]         # 1 tot 500 (too_many_operations)

Operation = PutOp | ConfirmOp | UnconfirmOp | DeleteOp        # discriminator "op"

class PutOp:       op: Literal["put"];       element: PutBody   # discriminator "kind"
class ConfirmOp:   op: Literal["confirm"];   id: str
class UnconfirmOp: op: Literal["unconfirm"]; id: str
class DeleteOp:    op: Literal["delete"];    id: str
```

Een `put`-body heeft de eigen velden uit §4.2, met deze verschillen:
- **Geen `id`.** De dienst berekent het id (§6) en geeft het terug.
- **Geen `citations`, `bindings` of `human_sources`.** Een gepland element heeft nog geen koppeling (B12), en de bron is het record zelf.
- **Standaardwaarden.** Een weggelaten lijst is leeg, en een weggelaten optioneel veld (`str | None`, `bool | None`) is `null`. Verplicht zijn alleen `kind`, de naam of term, en per soort: `templates` en `roles` bij `fact_type`, `fact_type` en `rule_kind` bij `validation_rule`, `statement` bij de andere regels, en `fact_type` en `values` bij `ground_fact`. Het contract zelf (§5) is strenger: daar schrijft `dump_model` elk veld, en de lader eist ze allemaal.
- **`status`** is `proposed` (standaard) of `confirmed`. `extracted` geeft een fout.
- **`repository`** staat bij `concept`, `fact_type`, `derivation_rule`, `exchange_rule` en `event_rule`. Het is optioneel, met standaard `.` (§6.1). Rollen, regels en voorbeeldfeiten erven de repository van `fact_type`.
- **Rollen** staan in de body van het feittype: `roles: [{name, concept?, datatype?, mandatory?}]`. Er is geen aparte `put` voor een rol. De dienst maakt de rolelementen, met de status en het record van het feittype.
- **In regels en voorbeeldfeiten** verwijzen `roles` en `superset_roles` naar **rolnamen** binnen het genoemde feittype. In het contract staan rol-id's.
- **Geen auteursvelden.** Een veld `author`, `author_name`, `author_email`, `entry_point` of `recorded_at` geeft `unknown_field`, met de melding dat ChunkHound dit zelf invult (B18).

Voorbeeld van een verzoek. Het legt een gepland begrip, een gepland bevestigd feittype met uniciteit, een geldig voorbeeldfeit en een tegenvoorbeeld vast:

```json
{
  "operations": [
    {"op": "put", "element": {"kind": "concept", "repository": "backend", "term": "skill",
      "plural": "skills", "definition": "An area of expertise a user can handle tickets for."}},
    {"op": "put", "element": {"kind": "fact_type", "repository": "backend", "name": "user skill",
      "templates": ["User <user> has skill <skill>."],
      "roles": [
        {"name": "user", "concept": "concept:backend/user", "datatype": "bigint", "mandatory": true},
        {"name": "skill", "concept": "concept:backend/skill", "datatype": "bigint", "mandatory": true}],
      "status": "confirmed"}},
    {"op": "put", "element": {"kind": "validation_rule", "fact_type": "fact_type:backend/user-skill",
      "rule_kind": "uniqueness", "roles": ["user", "skill"],
      "statement": "A user has a skill at most once."}},
    {"op": "put", "element": {"kind": "ground_fact", "fact_type": "fact_type:backend/user-skill",
      "values": {"user": "42", "skill": "3"}}},
    {"op": "put", "element": {"kind": "ground_fact", "fact_type": "fact_type:backend/user-skill",
      "values": {"user": "42", "skill": "3"},
      "violates": ["validation_rule:backend/user-skill/uniqueness/skill+user"]}}
  ]
}
```

Antwoord (MCP en CLI geven dezelfde JSON):

```json
{
  "batch_id": "5b0e…",
  "dry_run": false,
  "records": [21, 22, 23, 24, 25],
  "elements": [
    {"id": "concept:backend/skill", "kind": "concept", "status": "proposed"},
    {"id": "fact_type:backend/user-skill", "kind": "fact_type", "status": "confirmed"},
    {"id": "role:backend/user-skill/user", "kind": "role", "status": "confirmed"},
    {"id": "role:backend/user-skill/skill", "kind": "role", "status": "confirmed"},
    {"id": "validation_rule:backend/user-skill/uniqueness/skill+user", "kind": "validation_rule", "status": "proposed"},
    {"id": "ground_fact:backend/user-skill/4d435d18ce2b", "kind": "ground_fact", "status": "proposed"},
    {"id": "ground_fact:backend/user-skill/64420c4e0416", "kind": "ground_fact", "status": "proposed"}
  ],
  "warnings": [
    {"path": "operations[1].element.roles[0].concept", "code": "unresolved_reference",
     "message": "concept:backend/user is not in the human input; it may be a found element. Section 6 checks it on the full model."}
  ]
}
```

### 9.2 Controle

Een verzoek wordt als geheel gecontroleerd. De dienst voert de operaties op volgorde uit op een kopie van de huidige stand. Verwijzingen en B14 worden op de **eindstand** gecontroleerd. Zo maakt de volgorde binnen één verzoek niet uit: bijvoorbeeld eerst het bevestigde feittype en dan het voorbeeldfeit. Bij één fout wordt niets geschreven. Het antwoord bevat dan alle fouten.

Fouten blokkeren het verzoek:

| Code | Wanneer |
|---|---|
| `missing_field`, `unknown_field`, `invalid_value` | Vormfout volgens pydantic. Het pad komt uit `loc`, bijvoorbeeld `operations[1].element.roles[0].name` |
| `too_many_operations` | Meer dan 500 operaties |
| `empty_key` | Een naam of term wordt een lege sleutel |
| `duplicate_id` | Twee rollen in één feittype krijgen dezelfde sleutel, of twee `put`s in één verzoek geven hetzelfde id |
| `template_role_mismatch`, `rule_shape`, `derived_rule_kind` | Zoals in §7 |
| `unknown_role` | Een rolnaam in `roles`, `superset_roles` of `values` hoort niet bij het feittype. Dit wordt alleen gecontroleerd als het feittype in de menselijke invoer staat |
| `invalid_reference` | Een id dat niet volgens §6 is opgebouwd, of van de verkeerde soort, bijvoorbeeld een concept-id in `violates` |
| `unknown_element` | Een `delete` van een id zonder `put` in de menselijke invoer, of een `unconfirm` van een id dat er helemaal niet in staat |
| `still_referenced` | Een `delete` van een element waarnaar een ander element in de menselijke invoer na het verzoek nog verwijst. Het antwoord noemt de verwijzers |
| `confirmed_without_ground_fact` | Een feittype dat na het verzoek bevestigd is, heeft in de menselijke invoer geen geldig voorbeeldfeit (B14, B19). Dit geldt ook voor een `delete` van het laatste voorbeeldfeit |
| `backend_not_supported` | `config.database.provider` is `lancedb` (`database_config.py:31`), of de provider heeft geen `supports_domain_input` (B23) |
| `database_busy` | De database is tijdelijk niet beschikbaar (`DatabaseTemporarilyUnavailableError`, `serial_executor.py:21`), bijvoorbeeld tijdens een compactie of terwijl de Rust-pijplijn indexeert. De melding zegt dat er niets is geschreven en dat het over een paar seconden opnieuw kan |

Waarschuwingen schrijven wel:

| Code | Wanneer |
|---|---|
| `unresolved_reference` | Het id staat niet in de menselijke invoer. Het kan een gevonden element zijn; §6 controleert het hele model |
| `no_change` | Een `confirm` van iets dat al bevestigd is, of een `unconfirm` van iets dat niet bevestigd is |

Voorbeeld van een afwijzing. Het sjabloon gebruikt `<agent>`, maar de rol heet `assignee`, en het feittype wordt bevestigd zonder voorbeeldfeit:

```json
{
  "operations": [
    {"op": "put", "element": {"kind": "fact_type", "repository": "backend", "name": "ticket assignment",
      "templates": ["Ticket <ticket> is assigned to <agent>."],
      "roles": [{"name": "ticket"}, {"name": "assignee"}],
      "status": "confirmed"}}
  ]
}
```

Antwoord (MCP: een toolfout met `isError`; CLI: exitcode 1). Er is niets geschreven:

```json
{
  "error": {
    "type": "DomainInputRejected",
    "message": "3 issues; nothing was written",
    "issues": [
      {"path": "operations[0].element.templates[0]", "code": "template_role_mismatch",
       "message": "placeholder <agent> matches no role; roles are: ticket, assignee"},
      {"path": "operations[0].element.templates[0]", "code": "template_role_mismatch",
       "message": "role 'assignee' does not appear in this template"},
      {"path": "operations[0].element.status", "code": "confirmed_without_ground_fact",
       "message": "fact_type:backend/ticket-assignment would be confirmed without a valid ground fact; add a ground_fact put for it in the same request"}
    ]
  }
}
```

Interpretaties, aanvaard bij de review (B25):
- **B14 telt alleen geldige voorbeeldfeiten** uit de menselijke invoer. Een tegenvoorbeeld hoort niet bij de populatie. Gevonden voorbeeldfeiten ziet de dienst bij het schrijven niet, want die staan niet in de database. §4 kan dat later uitbreiden.
- **Bevestigen van een feittype geldt ook voor zijn rollen**, want een zinsjabloon en zijn invulplaatsen horen samen (ZS en VAR). Een rol kan ook los worden bevestigd of ontbevestigd.

### 9.3 Auteur, tijdstip en ingang (B18)

- **Auteur.** Per repository in het verzoek één keer `run_git(["config", "--get", "user.name"])` en hetzelfde voor `user.email` (`utils/git_safe.py:80`).
  - De `cwd` is de hoofdmap voor de sleutel `root`. Voor elke andere sleutel is het `<hoofdmap>/<repositorysleutel>` als die map een `.git` heeft, en anders de hoofdmap. Git leest dan zelf de configuratie van de repository, en anders de globale. Dat volgt de aanname bij B18.
  - Voor geneste repositories met een sleutel als `services-backend` valt de dienst terug op de hoofdmap.
  - Een returncode die niet 0 is, een lege uitvoer of een `GitCommandError` gelden als "geen naam". Dan wordt `author_name` gelijk aan `getpass.getuser()` en `author_email` gelijk aan `NULL`.
- **Tijdstip.** Eén tijdstip per verzoek, `datetime.now(UTC)`.
- **Ingang.** `cli` of `mcp`, gezet door de ingang zelf en niet door de aanroeper.

### 9.4 Ingangen

**MCP-tool `domain_write`**, geregistreerd met `register_tool` (`mcp_server/tools.py:294`). De daemon gebruikt dezelfde registry (`daemon/server.py:376`).
- **Parameters:** `operations: list[dict]` en `dry_run: bool = False`. `services` en `config` worden geïnjecteerd en staan niet in het schema (`tools.py:255-262`). De hoofdmap is `config.target_dir`.
- **Beschrijving:** kort, met de vorm van een `put` per soort in één regel en een verwijzing naar `chunkhound domain --schema`. Het volledige pydantic-schema staat niet in de toollijst: dat zou elke MCP-sessie van elke gebruiker duizenden tokens kosten (U5).
- **Afwijzing:** de tool geeft `{"error": {"type": "DomainInputRejected", "message": "<n> issues; nothing was written", "issues": [...]}}` terug. Dat herkent `is_error_tool_content` (`mcp_server/common.py:126`) als toolfout, zodat `isError` wordt gezet. De issues bevatten pad, code en melding (§7).
- **Omgevingsfout:** bij `backend_not_supported` of `database_busy` (§9.2) is het type `DomainInputUnavailable`, met dezelfde vorm en de code in `issues`. Zo ziet een agent het verschil tussen "verbeter je verzoek" en "probeer het later opnieuw", net als bij de exitcodes 1 en 2 van de CLI.
- **Logging:** geen `print()` (`AGENTS.md`).

**MCP-tool `domain_read`** (B24), geregistreerd zoals `domain_write`. Een agent leest hiermee de bestaande menselijke invoer voordat hij schrijft, ook als de daemon de database op slot heeft.
- **Parameters:** geen, net als `daemon_status` (`mcp_server/tools.py:773`). `services` en `config` worden geïnjecteerd.
- **Uitvoer:** de `HumanInputView` uit `load_human_input(provider)`, als dezelfde JSON als `--list-input` (zie hieronder).
- **Alleen lezen:** de tool schrijft niets en maakt de tabel niet aan. Zonder tabel is het antwoord een leeg model en een lege lijst `judgements` (invariant 1).
- **Fouten:** `backend_not_supported` en `database_busy`, als `DomainInputUnavailable` zoals bij `domain_write`.
- **Omvang:** geen filters en geen paginering. De invoer is handwerk en blijft klein. Filters en het lezen van het hele model horen bij §9.
- **Beschrijving:** kort. Ze zegt dat de tool geplande elementen, voorbeeldfeiten en bevestigingen teruggeeft, en dat een agent haar gebruikt vóór `domain_write`, om bestaande id's te hergebruiken.

**CLI `chunkhound domain`.** De vorm `chunkhound domain <hoofdmap>` ligt vast (B8), daarom kiest deze spec voor vlaggen en niet voor subcommando's:

```
chunkhound domain [PATH] --write FILE|- [--dry-run]   # verzoek uit bestand of stdin, antwoord als JSON op stdout
chunkhound domain [PATH] --list-input                 # huidige menselijke invoer als JSON (contractvorm + oordelen)
chunkhound domain --schema                            # JSON-schema van het verzoek; opent geen database
```

- **Registratie** volgt het patroon van `autodoc` (`api/cli/main.py:172`, `:194`, `:363`). De databasetoegang verloopt via `create_services` (`database_factory.py:82`), zoals `code_mapper.py:499`.
- **Ontbrekende database:** `--write` maakt `.chunkhound/db` aan als die nog niet bestaat. Dat is nodig voor model-eerst-werk zonder index, en voor §10 (B20).
- **Draaiende daemon:** de database is dan op slot. De CLI herkent de lockfout via `_is_db_lock_error` (`api/cli/commands/run.py:120`) en meldt dat de MCP-tools `domain_write` en `domain_read` de weg zijn zolang de daemon draait. De melding is eigen tekst (B25), omdat de bestaande melding van `_handle_daemon_lock_conflict` (`:134`) over indexeren gaat.
- **Exitcodes:**
  - `0`: geschreven;
  - `1`: afgewezen, met de issues als JSON;
  - `2`: de omgeving, zoals een lock, LanceDB of `database_busy`.
- **Zonder vlag** meldt `chunkhound domain <hoofdmap>` in §1 dat extractie nog niet beschikbaar is (§2), met exitcode 2.

`--list-input` en `domain_read` geven dezelfde `HumanInputView` terug, geserialiseerd volgens de regels uit §5:
- een `DomainModel` met de elementen die een `put` hebben;
- een lijst `judgements`: oordelen over id's zonder `put`, elk met `id`, `confirmed` en `human_sources`.

Hoe die oordelen in het model komen, besluit §4.

## 10. Besloten bij de review

1. **Een agent kan de menselijke invoer lezen terwijl de daemon draait (B24).** Bij een draaiende daemon staat de database op slot, en dan werkt `--list-input` niet. Zonder leestoegang zou de agent blind schrijven: hij kent de bestaande geplande id's niet en maakt makkelijk dubbelingen of verkeerde verwijzingen. Daarom komt er een tweede, kleine MCP-tool `domain_read` (§9.4). Die schrijft niet, dus B17 ("één schrijftool") blijft staan. Wel wijzigt de volgorde uit B2 op nog een punt.
2. **De vier voorstellen uit §11 die van een besluit afwijken of er een open punt in invullen, zijn aanvaard (B25):** `templates` als lijst, een eigen lockmelding, `root` voor een niet-geplaatst element, en wat bevestigen doet.

## 11. Voorstellen in deze spec

De voorstellen met "B25" zijn bij de review aanvaard. De andere zijn technische keuzes die geen besluit raken; ze gelden zodra de spec is goedgekeurd.

| Voorstel | Waar | Waarom |
|---|---|---|
| Een niet-geplaatst gepland element krijgt repository `.`, dus sleutel `root` (B25) | §6.1 | Lost het open punt uit B21 op zonder extra veld. Nadeel: bij meerdere repositories met ook code in de hoofdmap zelf vallen "niet geplaatst" en "in de hoofdmap" samen |
| NFKD vóór `slugify_kebab` | §6.1 | Nederlandse termen met trema of accent blijven leesbaar |
| Het id van een voorbeeldfeit is een hash over waarden en `violates` | §6.2 | Een voorbeeldfeit heeft geen naam, en een tegenvoorbeeld met dezelfde waarden moet een eigen id hebben |
| `FactType.templates` is een lijst, en het eerste sjabloon is het hoofdsjabloon. B22 en de woordenlijst noemden "`fact_type` met `template`" (B25) | §4.2 | Het boek en de CEM kennen meerdere synonieme zinsjablonen per feittype. Met één veld `template` zou dat later een migratie vragen |
| `HumanSource.put_status` legt vast met welke status een `put` schreef | §4.1 | Anders kan de lader invariant 3 niet controleren: een `put` met `proposed` en een `put` met `confirmed` zien er dan hetzelfde uit |
| Gelijkheid (`gl`) nog niet als regelsoort | §4.2 | Nog niet nagelezen tegen het boek; later toevoegen is goedkoop |
| Eén tabel met alleen toevoegingen, aangemaakt bij de eerste schrijfactie | §8.1 | Geen bijwerking voor wie de feature niet gebruikt (U5); de correcties van §4 passen erin zonder migratie |
| Generieke kopie van `domain_%` tijdens de compactie, met de DDL uit de bron | §8.3 | Rust hoeft het domeinschema niet te kennen; een nieuwe tabel vraagt geen wijziging in Rust |
| Geen rij in `schema_version`; idempotente DDL en `payload_version` | §8.3 | Er is geen migratieraamwerk, en dit volgt het bestaande patroon |
| Rollen alleen binnen de `put` van een feittype; regels en voorbeeldfeiten verwijzen naar rolnamen | §9.1 | Een agent schrijft een feittype in één stap |
| Bevestigen van een feittype geldt ook voor zijn rollen; B14 telt alleen geldige voorbeeldfeiten uit de menselijke invoer (B25) | §9.2 | Interpretatie van B14 en B19 |
| `domain_write` en `domain_read` staan altijd in de toollijst, met een korte beschrijving | §9.4 | Toegang per configuratie maakt de configuratie groter; de kosten in tokens blijven klein |
| `domain_read` zonder parameters, filters of paginering | §9.4 | De invoer is handwerk en blijft klein; filters horen bij §9 |
| Omgevingsfouten in de MCP-tools als `DomainInputUnavailable`, afwijzingen als `DomainInputRejected` | §9.4 | Een agent moet weten of hij zijn verzoek moet verbeteren of later opnieuw moet proberen |
| Vlaggen `--write`, `--list-input` en `--schema` in plaats van subcommando's | §9.4 | B8 legt `chunkhound domain <hoofdmap>` vast |
| Bij een draaiende daemon een eigen lockmelding die naar `domain_write` en `domain_read` wijst (B25) | §9.4 | B17 noemt "de bestaande lockmelding", maar die (`run.py:134`) zegt hoe je handmatig indexeert en helpt hier niet. De herkenning van de lock (`run.py:120`) blijft dezelfde |
| De auteur wordt per repositorysleutel gelezen, met terugval op de hoofdmap | §9.3 | Werkt de aanname bij B18 uit voor meerdere repositories |

## 12. Testen

Volgens `TESTING_PHILOSOPHY` in `AGENTS.md`: alleen contracten die een gebruiker, aanroeper of extern systeem merkt.

| Test | Contract |
|---|---|
| `test_contract_round_trip_is_byte_stable` | Laden en daarna dumpen geeft dezelfde bytes (invariant 11) |
| `test_loader_reports_all_issues_with_json_paths` | Meerdere fouten tegelijk, elk met pad en code |
| `test_loader_rejects_unsupported_schema_version` | Versie 0 of 2 geeft een fout |
| `test_loader_rejects_element_without_source` | Invariant 2 |
| `test_loader_rejects_confirmed_without_human_source` | Invariant 3 |
| `test_loader_rejects_confirmed_fact_type_without_ground_fact` | Invariant 4 |
| `test_loader_rejects_template_role_mismatch` | Invulplaats en rollen kloppen niet met elkaar (B12) |
| `test_loader_rejects_id_that_does_not_match_key` | Invariant 5 |
| `test_element_ids_are_stable_and_ascii` | Voorbeelden uit §6.2, met NFKD, gesorteerde rollen, `root`, `empty_key` en een afgeleid id |
| `test_realization_follows_code_citations` | Invariant 6 |
| `test_write_rejects_invalid_request_with_paths_and_writes_nothing` | Invariant 7 |
| `test_write_rejects_author_fields` | Invariant 9 |
| `test_write_confirm_requires_valid_ground_fact` | B14 en B19, ook bij de `delete` van het laatste voorbeeldfeit |
| `test_write_records_author_time_and_entry_point` | B18, met een tijdelijke Git-configuratie en de terugval op de gebruikersnaam van het besturingssysteem |
| `test_write_dry_run_writes_nothing` | `dry_run`, met het verzoek uit §9.1 als fixture. De id's, soorten, statussen en de waarschuwing zijn precies die uit het antwoordvoorbeeld, `records` is leeg, en de tabel ontstaat niet |
| `test_list_input_replays_puts_confirms_and_deletes` | Afspelen (§8.1), met oordelen over gevonden id's |
| `test_database_without_domain_input_is_unchanged` | Invariant 1: na indexeren en compactie zonder schrijfactie bestaat er geen `domain_`-tabel |
| `test_human_input_survives_python_compaction` | §8.3, met de fixture `populated_db` (`tests/test_duckdb_compaction.py:241`) |
| `test_human_input_survives_rust_compaction` | §8.3, via een indexrun met de Rust-pijplijn en een geforceerde compactie |
| `compaction_preserves_domain_tables` (Rust, `compaction.rs`) | Een tabel `domain_*` blijft, een andere onbekende tabel valt weg |
| `test_human_input_survives_wal_removal` | Na de schrijfactie, met de verbinding nog open: het databasebestand zonder WAL kopiëren en openen, en de invoer is er |
| `test_human_input_survives_force_reindex` | §8.3 |
| `test_human_input_from_payload_version_1_loads` | Upgradepad; een vaste rij als fixture |
| `test_human_input_rejected_on_lancedb` | B23, `backend_not_supported`, er wordt niets geschreven |
| `test_write_while_database_busy_reports_retry` | `database_busy` |
| `test_mcp_domain_write_reports_issues_as_tool_error` | `isError` plus de issues, via `common.handle_tool_call` |
| `test_mcp_domain_read_returns_human_input` | B24, via `common.handle_tool_call`: op een verse database een lege `HumanInputView` zonder dat de tabel ontstaat (invariant 1); na een `domain_write` dezelfde JSON als `--list-input` |
| `test_cli_domain_write_and_list_round_trip` | CLI: schrijven, lezen, exitcodes 0, 1 en 2, en `--schema` zonder database |

De bestaande test `test_unknown_tables_are_dropped_during_compaction` blijft ongewijzigd groen.

## 13. Fasering (uitvoering via pi-bolt, één sessie per fase)

| Fase | Inhoud | Hangt af van | Model |
|---|---|---|---|
| 1 | `model.py`, `identity.py` en `Issue`, met de identiteits- en realisatietests | – | sol/medium |
| 2 | `loader.py` (`parse_model`, `load_model`, `dump_model`) met de laadtests | 1 | sol/medium |
| 3 | De provider: `supports_domain_input`, `append_domain_input` (aanmaken bij eerste schrijfactie, bundelen, `CHECKPOINT`), `load_domain_input`, de kopie in de Python-compactie. Tests voor Python-compactie, WAL en ongewijzigde database | – | sol/high |
| 4 | De kopie in de Rust-compactie, met een Rust-test en Python-contracttests via de Rust-pijplijn (compactie en `--force-reindex`); `make rust-check` en `make rust-test` | 3 | sol/high |
| 5 | `human_input.py`: verzoekmodellen, afspelen, controle, `apply_write` en `load_human_input`, met de schrijftests op een echte tijdelijke DuckDB | 1, 2, 3 | sol/high |
| 6 | `author.py` en `write_human_input`: auteur, tijdstip, ingang, LanceDB-weigering, `database_busy` en `upgrade_payload`, met de bijbehorende tests | 5 | sol/medium |
| 7 | Ingangen: de CLI `chunkhound domain` (`--write`, `--list-input`, `--schema`, `--dry-run`) en de MCP-tools `domain_write` en `domain_read` (B24), met de ingangstests | 6 | sol/medium |

Fase 1 en 3 zijn onafhankelijk en kunnen parallel in aparte worktrees, net als fase 2 en 4. Na elke fase volgen een diff-review, de smoke tests en een commit. Het plan (`docs/melly/plans/2026-11-13-cogniam-1.md`) werkt de fasen uit met bestanden, acceptatiecriteria en een testcommando per fase.

## 14. Bewust niet

- Geen veld `level` (B23), geen opgeslagen veld voor gepland of gerealiseerd (B23), en verplicht en datatype niet als regel-element (B13).
- Geen modelbestand en geen curatiebestand (B15). Geen export, import of synchronisatie tussen machines (B20).
- Geen menselijke invoer op LanceDB (B23).
- Geen correcties op gevonden elementen behalve bevestigen en ontbevestigen. Verwerpen, samenvoegen en hernoemen komen in §4, als nieuwe waarden van `op` in dezelfde tabel.
- Geen normalisatie van datatypen: dat is §2.
- Geen aparte bevestigtool en geen controle dat een mens echt bevestigde (B19).
- Geen `JSON`-kolomtype en geen sequence in de domeintabel (§8.1).
- Geen schrijfroute via de CLI terwijl de daemon draait (B17): de CLI geeft dan een duidelijke melding.
