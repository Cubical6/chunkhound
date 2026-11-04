# Spec deel A: `map` levert een C4-kaart voor AutoDoc (O-MAP)

- Datum: 2026-11-04 · Branch: `c4/shared-extraction-layer` (HEAD bij start `cfb59235`)
- **Status:** goedgekeurd op 2026-11-04, inclusief de punten uit §12 en de wijzigingen in §3.1 en §16 na de planreview; plan goedgekeurd; geen providerrun goedgekeurd
- Besluitenlog: [2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md), de rijen "O-MAP", "Bronselectie", "Groepsindeling", "C4-toets" en "Bouwstenen en reikwijdte" (hieronder "besluit: …")
- Consument: [AutoDoc-spec](2026-10-29-autodoc-c4-map-design.md) en `chunkhound/autodoc/architecture/`
- Vervolg: [deel B, containers per proces](2026-11-04-c4-processen-design.md)

## 1. Doel en afbakening

`chunkhound map` schrijft nu alleen het eigen model versie 3. AutoDoc leest uitsluitend het neutrale contract versie 1 en slaat een ander bestand met een waarschuwing over. Een geslaagde maprun levert dus geen kaart op. Bovendien zijn testcode en procesdocumenten bron, en krijgt de hoofdcontainer van deze repository geen componenten.

Deel A levert een werkende kaart met echte componenten. **Containers blijven per manifest.** Daarmee voldoet de kaart nog niet aan de C4-eis dat componenten van een container in dezelfde procesruimte draaien. Dat lost deel B op (besluit: O-MAP · splitsing in deel A en B).

**In scope:** bronselectie en systeemnaam (§3), bouwstenen en merge-stap (§4), technologie en omschrijvingen (§5), lockbestand (§6), de vertaling naar contract versie 1 (§7 tot en met §9), rapport (§10) en de naamfix in AutoDoc (§11).

**Buiten scope:**
- processen, plaatsing, kopieën, markeren van gedeelde componenten, en minder `exclude`-regels: deel B;
- deployment-views;
- Task6 en de opgeruimde execution-coördinator;
- `chunkhound research`, de topics en de index: die blijven ongewijzigd.

**Invarianten**
1. Het contract laadt in `ModelLoader` zonder één waarschuwing.
2. Het contract bevat geen gegeven dat niet uit het interne paar of de maprun volgt. Er wordt niets verzonnen.
3. Het interne paar blijft volledig. Weglaten geldt alleen voor het contract, en elke weglating wordt geteld.
4. Met `--no-c4` blijft de uitvoer byte-gelijk.
5. Een tweede volledige run op dezelfde bestanden doet geen merge-aanroep, ook als `--out` in de repository staat. Zijn research en topics gelijk gebleven en was de eerste run schoon, dan is het contract ook byte-gelijk. Elke volledige run doet wel opnieuw research, dus topics kunnen verschillen.

## 2. Bestanden

| Bestand | Inhoud | Wanneer |
|---|---|---|
| `<scope>_c4_model.json` | contract `schema_version: 1` | alleen bij `run.kind == "full"` |
| `<scope>_c4_map_model.json` | intern model versie 4 (was `_c4_model.json`) | volledige run en proefrun |
| `<scope>_c4_map_evidence.json` | intern bewijs versie 4 (was `_c4_evidence.json`) | volledige run en proefrun |

`<scope>` is `safe_scope_label`, net als nu. De naam van het contract volgt `loader.py:113`.

**Publicatievolgorde:** eerst het paar (bewijs, dan model), daarna het contract, daarna het lockbestand, en als laatste het opruimen van oude uitvoer. Elk bestand gaat via de bestaande atomaire schrijfroute. Crasht een run tussen paar en contract, dan blijft een ouder contract staan tot de volgende volledige run.

**Oude uitvoer.** Een volledige run verwijdert een achtergebleven `<scope>_c4_evidence.json`. `<scope>_c4_model.json` wordt vanzelf overschreven. Een proefrun verwijdert niets.

**Lezers van de oude namen.** In `chunkhound/` leest niets anders het paar; `load_c4_pair` krijgt paden als argument. Aan te passen: `c4/writer.py:61–62`, de helptekst in `code_mapper_parser.py:39` en de tests in `test_output_contract.py` en `test_cli_contract.py`.

## 3. Bronselectie

### 3.1 Bestandslijst voor de analyse

`list_scope_files` filtert na `collect_scope_files`. Alleen C4 gebruikt `list_scope_files`; HyDE roept `collect_scope_files` rechtstreeks aan.

Standaard vervalt:
- elk bestand in een map met de naam `tests`, `test`, `__tests__`, `fixtures`, `__fixtures__` of `testdata`;
- elk bestand met de naam `test_*`, `*_test.*`, `*.test.*`, `*.spec.*` of `conftest.py`;
- elk pad dat past op `c4.exclude` (§3.3);
- de eigen uitvoer van `map`: bestanden direct in de uitvoermap die beginnen met `<safe_scope_label>_`, of die heten `hyde_plan_{arch,ops}_<safe_scope_label>.md` of `hyde_scope_prompt_{arch,ops}_<safe_scope_label>.md` (`code_mapper/pipeline.py:349–391`), als die map in het project ligt. De gedocumenteerde aanroep is `chunkhound map … --out docs/` (`cli-reference.md:333`). Zonder deze regel ziet de volgende run zijn eigen uitvoer als broncode, en worden die niet-gevolgde bestanden ook bronnen.

De test-regels kijken alleen naar paddelen onder de scope: een scope binnen `tests/` blijft dus werken. Patronen worden op relatieve paden toegepast.

Uitsluiten gebeurt vóór verwijzingen, manifesten en bouwstenen. Zo ontstaan geen fixturecontainers, en tellen imports uit tests niet mee voor afhankelijkheden. Verwijzingen naar uitgesloten paden vallen al weg (`assemble.py:208–213`). Op deze repository vallen buiten `tests/` alleen `scripts/test_*` (10 bestanden) en de twee projectmappen weg.

### 3.2 Documentatie als architectuurbron

`doc_files_for` krijgt de configuratie en verwijdert uit de kandidaten (`README*` en topicbronnen):
- elk pad met een map die met `.` begint;
- de testmappen uit §3.1;
- bestandsnamen die, zonder hoofdletters, beginnen met `changelog`, `changes`, `history`, `news`, `release_notes`, `releases`, `migration` of `upgrading`;
- `c4.exclude`;
- de eigen uitvoer uit §3.1, want een topic kan eerdere uitvoer citeren als die geïndexeerd is.

De topicbronnen komen niet uit `list_scope_files`. Dit filter is dus nodig naast dat van §3.1.

### 3.3 Projectinstelling

Nieuw veld `Config.c4` met model `C4Config` in `chunkhound/core/config/c4_config.py`, geladen zoals de andere secties:

```json
{
  "c4": {
    "exclude": ["docs/melly/**", ".superpowers/**"],
    "exclude_test_code": true
  }
}
```

- `exclude`: patronen vanaf de projectroot, met de bestaande matcher uit `utils/file_patterns.py`; standaard leeg. Ze gelden voor §3.1 en §3.2.
- `exclude_test_code`: standaard `true`; `false` schakelt de testregels van §3.1 en §3.2 uit. Verborgen mappen en changelogs blijven uitgesloten als documentatiebron; daarvoor is geen uitzondering.
- Beide tellen vanzelf mee in `_input_fingerprint`, want `config.model_dump` neemt de nieuwe sectie mee.
- Geen omgevingsvariabelen en geen CLI-opties.

Waar deze instelling in deze repository staat: §12, punt 1.

### 3.4 Systeemnaam

`scan_runtime` kiest de naam ná de selectie: de eerste geselecteerde container van de hoofdmap, anders het eerste manifest in de hoofdmap, anders de mapnaam. De uitkomst verandert alleen als het eerste manifest niet is geselecteerd en een later wel. De id blijft uit het lockbestand komen zolang dat bestaat.

**`cdylib` naast een ander manifest.** Een `Cargo.toml` met `crate-type = ["cdylib"]` in een map met nog een manifest is geen containerkandidaat: de bibliotheek draait in het proces van dat andere manifest. Hij komt dus niet in `uncertain`, en de uitkomst hangt niet af van een stem van het model. Zijn afhankelijkheden blijven meetellen. Anders zou het systeem hier `chunkhound_native` kunnen heten, met een container zonder bestanden (`runtime.py:350`).

**Dezelfde naam voor systeem en container.** Die komt hierdoor vaker voor (§11). In `documented_relations` geeft zo'n naam twee id's en vervalt de relatie als `ambiguous` (`assemble.py:280–285`). Daarom wint bij precies deze gelijkspel de container. Een documentrelatie met de term `chunkhound` koppelt dus aan de container.

## 4. Bouwstenen en merge

### 4.1 Eén bouwsteen per map

Per container is elke map één bouwsteen (`Group`), met alleen de bestanden direct in die map.

- **Id:** `<container-id>/<map relatief aan de containerwortel>`, met `.` voor de wortel.
- **`name` en `prefix`:** het relatieve mappad; bij de wortel is `name` de containernaam en `prefix` `.`.
- **`build_groups`** krijgt `files`, `container_of`, `container_roots` en `container_names`, en geeft de groepen terug. `new_group_ids` wordt nergens gelezen en vervalt.
- **Vervalt:** `draft_tree`, `replay`, `TreeSpec`, `_new_directories`, `_extend_scope`, `_place_container`, `_unit` in zijn huidige vorm, en het parsen in deze stap.
- **Het model splitst niet** (besluit: Bouwstenen en reikwijdte). Bestanden in één map blijven dus samen.

### 4.2 Invoer

Er blijft één aanroep per container met wachtende bouwstenen. Bouwstenen die al een component hebben of in `direct_groups` staan, wachten niet.

**Prompt `c4_merge.md`** krijgt, naast de bestaande regels:
- **C4-definitie:** een component is *"a grouping of related functionality encapsulated behind a well-defined interface"*; componenten draaien binnen deze container en zijn niet los deploybaar; een map of package is niet automatisch een component; één component mag meerdere groepen omvatten en groepen met verschillende verantwoordelijkheden horen apart; beslissen op verantwoordelijkheid en bewijs, nooit op aantal bestanden of mapgrootte.
- **Runtimeregel:** alleen code die in de container draait kan een component zijn; documentatie, build, packaging, CI, deployment en ontwikkelhulpmiddelen gaan naar `direct`.
- `description` wordt gevraagd in plaats van "may be null". Het schema blijft `str | None`, zodat een ontbrekende omschrijving het antwoord niet afkeurt; die wordt geteld (§5).
- De zin over "positive-count group links" wordt aangepast aan `file_links`.

**Invoerdata:**

```json
{
  "groups": [{"id": "G54", "dir": "chunkhound/services",
              "files": [{"name": "search_service.py", "symbols": ["SearchService"]}]}],
  "existing": [{"id": "E1", "name": "Parsers", "description": "…",
                "dirs": ["chunkhound/parsers"]}],
  "file_links": [[12, 40, 3], [12, "E1", 5], ["E1", 40, 2]]
}
```

- **Aliassen:** `G<n>` en `E<n>` gelden per aanroep. De code vertaalt ze terug, en het model herhaalt geen lange id's. Titel-eindpunten zijn `group:G<n>`, `component:E<n>` of `container`.
- **`symbols`:** de chunks van `parse_file` met soort `CLASS`, `INTERFACE`, `STRUCT`, `ENUM`, `TRAIT`, `FUNCTION`, `TYPE` of `TYPE_ALIAS`, alleen voor bestanden waarvan `Language.is_programming_language` waar is; zonder namen met `.`, `::`, `_line_` of een `_` aan het begin; `_part<n>`-achtervoegsels eraf en ontdubbeld. Ze benaderen wat een bestand aanbiedt en bewijzen geen gedrag. Een bestand dat niet te parsen is, krijgt een lege lijst.
- **`file_links`:** `[van, naar, aantal]`, alleen met status `counts`. Een getal is de plek van een bestand in `groups`, in de volgorde van de prompt; `E<n>` is een bestaande component, opgeteld over al zijn bestanden.
- **Weggelaten koppelingen:** naar `direct_groups` en naar andere containers, want die kunnen de plaatsing niet sturen.
- **Parsen** gebeurt alleen voor wachtende bouwstenen. Zonder wachtende bouwstenen wordt niets geparseerd.

De eerste run heeft geen `existing`, dus daar zijn alle eindpunten getallen. De controle op toegestane titels (`_merge_titles`) blijft de volledige koppelingen gebruiken, niet deze gefilterde weergave.

### 4.3 Grenzen en foutindeling

- **Uitvoerlimiet:** `max_completion_tokens = max(8192, min(32768, prompt_chars // 4))`. Nu krijgt de merge-stap de standaard van 4.096 tokens.
- **Foutindeling:** een onleesbaar of afgekapt antwoord (`is_unreadable`) wordt `AnswerRejectedError`. Een geweigerde invoer (`INPUT_REJECTED_MARKERS`) wordt binnen `attempt` afgevangen en gaat zonder herkansing naar §4.5. Overige fouten blijven zoals nu: tijdelijk via `_is_retryable_poi_error`, anders fataal.
- **Invoerbudget:** vóór de aanroep controleert de stap `fits()` met het schema van `MergeAnswer` tegen `llm.input_limit("synthesis")`. Past de prompt niet, dan vervallen eerst `symbols`. Past hij dan nog niet, dan volgt §4.5 zonder aanroep, met de reden in het rapport. De limiet is in deel A niet instelbaar: `llm_config.py:989` zet instelbare limieten alleen voor de utility-rol, dus hier geldt de bekende providerwaarde of de standaard van 400.000 tekens.

### 4.4 Een antwoord verwerken

`check_merge_answer` wordt vervangen door `normalize_merge_answer`. Die keurt niet het hele antwoord af bij één fout, maar:

- verwijdert onbekende groep-id's en telt die;
- laat bij een herhaalde plaatsing de eerste staan, in de volgorde van het antwoord: eerst `components`, dan `direct`;
- verwijdert een componentrij zonder naam of zonder overgebleven groepen;
- voegt nieuwe componenten met dezelfde naam samen;
- koppelt een rij met de naam van één bestaande component aan die component; een naam die op meerdere bestaande componenten past (`merge.py:190`), maakt de groepen van die rij `leftover`;
- laat een titelrij met een ongeldig paar vallen in `_merge_titles`; de titelstap vult dat aan;
- geeft de niet-geplaatste bouwstenen terug als `leftover`.

Alleen een antwoord dat **geen enkele** bouwsteen plaatst, is nog `AnswerRejectedError`.

**Herkansing.** Per container zijn er hoogstens twee aanroepen:

| Eerste aanroep | Tweede aanroep via `RetryQueue` |
|---|---|
| tijdelijke fout of afgekeurd | dezelfde prompt |
| `leftover` over | smalle prompt: alleen de `leftover`-bouwstenen, met de zojuist gekozen componenten als `existing` |
| volledig geplaatst | geen |

Alleen de eerste aanroep mag uitstellen, want `drain` wisselt de wachtrij één keer. De terugval van de tweede aanroep geeft het tot dan toe geplaatste resultaat terug. Titels uit beide aanroepen worden samengevoegd; bij hetzelfde paar wint de eerste.

Wat na de tweede aanroep overblijft, valt onder §4.5. Geplaatste bouwstenen blijven geplaatst.

### 4.5 Mislukte of onvolledige merge-stap

Er worden **geen componenten verzonnen**. `_default_merge` geldt nog alleen voor de proefrun.

Bij een container met niet-geplaatste bouwstenen:

- **Deze run:** de bestanden staan direct onder de container. `assemble.py:60` zet de eigenaar al standaard op de container, en `implementation_sources` citeert ze.
- **`MergeResult.fallback`** is `True`, zodat `_transition` geen geschiedenis vastlegt (`pipeline.py:515`).
- **Markering:** het container-element krijgt `fallback`, zodat `fallback_count` en de bestaande waarschuwing werken. De markering gaat niet op `unit.markers`, want dan valt de container uit `ScopeLock.containers` (`pipeline.py:546`).
- **Niet in `direct_groups`:** anders worden ze blijvend (`pipeline.py:228`, `:552`). De volgende run ziet ze weer als wachtend.

**Lockbestand** bij zo'n run:

- **`base_sha`:** blijft de oude waarde. Deze staat op scope-niveau, dus dit geldt voor de hele scope. Het gevolg is alleen dat de volgende run een grotere hernoemingsdiff leest.
- **Vastgelegde componenten van die container** worden alleen overgenomen als **geen van hun groepen nog bestaat en hun id niet in `identity.ids.values()` zit**. Bestaat een groep nog, dan kan overnemen de volgende run laten falen op dubbele eigenaars (`merge.py:125–126`).
- **Overnemen gebeurt in `_identify`:** de tombstone uit `identity.py:166–167` en de `removed`-rand uit `_history` worden voor die id's weer verwijderd, en `_build_lock` zet het oude `LockedComponent` terug. Ze verschijnen niet in deze uitvoer.
- **Andere containers** worden gewoon bijgewerkt.

Zonder eerder lockbestand is er niets over te nemen; `base_sha` is dan de huidige commit en de volgende run probeert de wachtende bouwstenen opnieuw.

**Proefrun:** `--overview-only` houdt één voorlopige component per bouwsteen, gemarkeerd als `trial`, met `Group.name` als naam. Dat voorkomt de id `component:topic` die de naam `.` nu geeft.

## 5. Technologie en omschrijvingen

C4 vraagt technologie op elke container en component, en een korte omschrijving op elk element. Het interne `Element` krijgt het veld `technology: str`, zodat het paar de bron blijft.

| Element | `technology` | `description` |
|---|---|---|
| Systeem | geen veld | `description` uit het manifest van de naamgever, anders `""` |
| Container | taal van het manifest (`pyproject.toml` → `Python`, `Cargo.toml` → `Rust`, `package.json` → `Node.js`, `composer.json` → `PHP`); bij een `cdylib` in dezelfde map: `Python, Rust`; zonder manifest: `""` | `description` uit het manifest, anders `""` |
| Component | de talen van zijn bestanden, gesorteerd; talen zonder code tellen alleen als er verder niets is | uit het merge-antwoord; ontbreekt die, dan `""` |
| Opslag uit een afhankelijkheid met de stem `storage_driver` | de naam van het element (§12, punt 6) | `""` |
| Opslag uit een configuratiebestand, zoals `VOLUME` | `""` | `""` |
| Persoon, extern systeem | `""` | zoals nu |
| Relatie | `""` | n.v.t. |

Lege velden worden geteld in het rapport (§10). Omdat manifesten en bestanden in elke run gelezen worden en componentomschrijvingen in het lockbestand staan (`LockedComponent.description`), blijft dit stabiel zonder merge-aanroep.

## 6. Lockbestand

`SCHEMA_VERSION` gaat van 3 naar 4. Deze waarde bepaalt ook het interne paar; het AutoDoc-contract blijft op versie 1.

| Veld | Wijziging |
|---|---|
| `tree_spec` | vervalt |
| `group_membership` | vervalt, want af te leiden uit het pad |
| `components[].groups`, `direct_groups` | bevatten mapgroepen |
| overige velden | ongewijzigd |

Deel B voegt later alleen velden toe (zie de deel B-spec).

**Oud lockbestand.** `_read_lock` controleert de versie vóór de schemavalidatie: `raw` moet een object zijn en `raw.get("version")` gelijk aan 4. Anders volgt `LockfileError` met het pad en de melding dat het bestand uit een oude versie komt en verwijderd moet worden. Er is geen migratie, omdat geen enkele release-tag deze code bevat. Verwijderen doet de gebruiker zelf; ook container-id's, tombstones en overrides vervallen dan.

**Stabiliteit.**

| Gebeurtenis | Gedrag |
|---|---|
| Nieuw bestand in een bekende map | hoort bij die bouwsteen, geen aanroep |
| Nieuwe map, ook onder een geclaimde map | nieuwe wachtende bouwsteen, één merge-aanroep; het model mag hem aan een bestaande component koppelen |
| Verplaatst bestand | volgt zijn nieuwe map; `assign_component_ids` volgt via overlap en hernoemingen |
| Hernoemde map | nieuwe wachtende bouwsteen; de id van de component blijft via overlap behouden, maar de naam kan wijzigen |
| Verwijderde map | claim vervalt; een lege component krijgt een tombstone, behalve in §4.5 |
| Teruggekeerde map | wachtend, tenzij een bestaande component de groep nog claimt |
| Gegroeide vergrendelde bouwsteen | blijft in zijn component; opnieuw verdelen vraagt een nieuw lockbestand |
| `overrides.placements` met een onbekende groep | wordt genegeerd, met een regel in het rapport |

Dit lockbestand vraagt op deze repository één keer een nieuwe merge-ronde, omdat de oude indeling vervalt.

## 7. Vertaling naar het contract

`c4/contract.py` bevat een pure functie die het contract bouwt uit model, bewijs, topics en de pad-naar-repository-tabel. Git-gegevens komen uit een aparte functie (§9). Het contract krijgt een eigen getypeerde vorm, zonder import uit `chunkhound/autodoc`. Er komt geen schemabestand: de loader is de bron van waarheid.

### 7.1 `system`

Het element met `kind: system` wordt het object `system` met `id`, `name` en `description`. Citaten met het systeem als doel gaan niet mee, want `system` heeft geen bronveld.

### 7.2 `elements[]`

| Intern | Contract `kind` | Contract `parent` |
|---|---|---|
| `container` met status `found` of `documented` | `container` | systeem-id |
| `storage` | `container` | systeem-id |
| `component` met een container als ouder | `component` | die container |
| `component` met een andere ouder | weglaten (§8) | |
| `external` | `externalSystem` | `null` |
| `person` | `person` | `null` |

- `id` en `name` blijven gelijk. `status` wordt `found` → `aangetroffen`, `documented` → `gedocumenteerd`.
- `description` wordt weggelaten als die leeg is.
- `technology` volgt §5. Het veld is altijd aanwezig, omdat `loader.py:216, 269` het zonder standaardwaarde leest.
- `files` bevat alleen de **directe** implementatiebestanden, gesorteerd (§7.6).
- `sources` bevat de bron-id's van de geverifieerde citaten met dit element als doel. Bij een container zijn dat bewust ook de citaten van bestanden van zijn componenten (`assemble.py:165–173`). Anders valt een voorlopige container zonder eigen citaat weg, met al zijn componenten. Alleen `files` is direct.
- `markers`, `coverage`, `history` en `merged` gaan niet mee.

### 7.3 `relations[]`

`id` en `title` blijven gelijk, `from` wordt `source`, `to` wordt `target`, `status` zoals in §7.2, en `technology` is `""`. `sources` bevat de geverifieerde citaten met deze relatie als doel. Elke tellende verwijzing is al zo'n citaat (`assemble.py:210–221`), dus een aparte verwerking van verwijzingen is niet nodig.

### 7.4 `sources[]`

Alleen bronnen waarnaar een element of relatie in het contract verwijst. Niet mee: niet-geverifieerde citaten, citaten zonder doel of met doel systeem, en citaten met soort `topic`.

| Veld | Citaat |
|---|---|
| `path` | `file` |
| `start_line`, `end_line` | zoals opgegeven |
| `kind` | `code` → `code`, `configuration` → `config`, `documentation` → `doc` |
| `repository` | id van de repository die het pad bevat (§9) |

`id` is `src:` plus de eerste 32 hextekens van de sha256 over canonieke JSON van `[repository, path, start_line, end_line, kind]`.

**Volgorde.** Alle lijsten zijn gesorteerd: records op `id` (labels op `source`, `target`, `relations`; topics op `file`; `covers` op `element`), en lijsten van id's en paden op waarde.

Paden zijn POSIX-paden vanaf de indexroot, ook bij een kleinere scope.

### 7.5 `merged_labels[]`

1. Neem pijlen waarvan beide eindpunten in het contract of het systeem zitten.
2. Neem de pijl alleen op als **heel** `underlying` in het contract zit.
3. Neem de pijl alleen op bij minstens twee verschillende titels binnen die relaties.
4. Laat een label weg dat leeg is, langer dan 60 tekens is of `[...]` bevat (`loader.py:332–336`).
5. Ontdubbel op (`source`, `target`, `relations`). Bij verschillende labels voor dezelfde sleutel wint het eerste in sortering.

Een paar kan meer dan één regel krijgen als zijn views verschillende relaties tonen. Dat past bij de consument, die op de exacte relatieverzameling vergelijkt (`likec4_writer.py:54–62`).

### 7.6 Directe bestanden en `topics[]`

`evidence.element_files` bevat voor containers de **opgetelde** bestanden, inclusief die van hun componenten.

- component, opslag, persoon en extern systeem: `element_files[id]`;
- container: `element_files[id]` min de bestanden van al zijn componenten.

`topics[]` wordt tijdens de maprun berekend uit de `TopicSources` van de geslaagde topics.
- `file` is de artefactnaam, relatief aan de uitvoermap.
- `covers` heeft per element met een niet-lege doorsnede `{element, files}`, de doorsnede van de geciteerde bestanden van het topic en de directe bestanden van het element.
- Een topic zonder dekking blijft staan met `covers: []`. Mislukte topics komen niet voor.

## 8. Weglaatregels

In deze volgorde (`loader.py:206–246, 249–254, 257–287`):

1. Componenten zonder containerouder.
2. Elementen zonder enige bron, en componenten waarvan de container daardoor wegvalt.
3. Relaties met een eindpunt dat niet in het contract of het systeem zit, en relaties zonder enige bron.
4. Bronnen, labels en dekking die alleen naar het weggelaten deel verwezen.

De aantallen komen in het rapport (§10).

## 9. Repositories en bronlinks

**Welke repositories.** Altijd de indexroot, met `id` en `path` `.`. Daarnaast elke geneste repository die een bronbestand of direct bestand van het contract bevat. Een pad hoort bij de diepste map op de route vanaf de indexroot waarin `.git` bestaat (map of bestand, dus ook worktrees en submodules). `id` en `path` zijn het POSIX-pad vanaf de indexroot.

**Bouwvolgorde.** Eerst wordt pad → repository bepaald; dat is invoer van de pure vertaling, omdat bron-id's de repository bevatten. Daarna worden de Git-gegevens opgehaald.

**`commit`.** `HEAD` van die repository, via `_get_head_sha`. Voor `.` is dat `run.head_sha`. Zonder Git-gegevens is dat `NO_GIT_HEAD`; de consument maakt daar geen link van (`source_links.py:52`).

**`remote_url`.** De URL van remote `origin`, alleen als alle onderstaande voorwaarden gelden. Anders `null`, met de reden in het rapport.

| Voorwaarde | Controle, lokaal en zonder netwerk |
|---|---|
| De map is de echte wortel, per repository | `rev-parse --show-toplevel` is gelijk aan die map, beide opgelost met `resolve()` |
| `HEAD` is niet veranderd tijdens de run | alleen voor `.`: `run.head_sha` is gelijk aan `HEAD` bij het einde. Voor een geneste repository wordt dit niet gecontroleerd (§12, punt 14) |
| `origin` bestaat | `remote get-url origin` |
| De commit staat op de remote | `branch -r --contains <commit> --list 'origin/*'` is niet leeg |
| Geciteerde bestanden zijn gevolgd | elk `sources[].path` van die repository zit in `ls-files -z` |
| Geciteerde bestanden zijn ongewijzigd | geen ervan zit in `status --porcelain -z --no-renames` |

`-z` is verplicht vanwege paden met spaties of niet-ASCII-tekens. Padlijsten gaan niet als argument mee.

**Eén bestand zet alle links uit.** Elk implementatiebestand krijgt een citaat op regel 1, dus één niet-gevolgd of gewijzigd bestand in de scope zet de links van de hele repository uit. De reden in het rapport noemt het aantal en het eerste pad.

**Inloggegevens.** Bij elk schema vervallen gebruikersinformatie, query en fragment; alleen `git` bij `ssh` blijft staan. Bij `gebruiker@host:pad` blijft alleen `git@` staan.

Een Git-fout of time-out is nooit fataal: het gevolg is `remote_url: null` met de foutmelding in de reden. De gegevens worden via `run_git` opgehaald (`utils/git_safe.py:80`).

## 10. Runs en rapport

| Run | Paar | Contract |
|---|---|---|
| volledig | geschreven | geschreven; terugvalitems gaan mee zonder markering |
| volledig met `--no-markdown` | geschreven | geschreven; zonder index selecteert AutoDoc het niet |
| proefrun (`--overview-only`) | geschreven | niet geschreven; het rapport meldt dat |
| `--no-c4` | niet | niet; uitvoer byte-gelijk |
| fatale fout | niet | niet |

Extra regels in `C4Build.report_extra`, zonder wijziging van exitcodes:

```text
C4-bron: <n> bestanden geanalyseerd, <n> uitgesloten als testcode, <n> door c4.exclude
C4-merge <container>: <n> bouwstenen, <n> geplaatst, <n> niet geplaatst (<reden>), <n> plaatsingen verwijderd
C4-merge: override voor onbekende groep genegeerd: <groep>
C4-contract: <n> elementen, <n> relaties, <n> bronnen, <n> labels, <n> topics
C4-contract weggelaten: <n> componenten zonder container, <n> elementen zonder bron, <n> componenten zonder geldige container, <n> relaties zonder eindpunt, <n> relaties zonder bron, <n> labels
C4-contract onvolledig: <n> zonder technologie, <n> zonder omschrijving, <n> relaties tussen containers zonder protocol
C4-contract repository <id>: geen bronlinks (<reden>)
```

Bij een proefrun: `C4-contract: niet geschreven (proefrun)`.

## 11. AutoDoc-wijziging: de naamfout

Dit is de enige AutoDoc-wijziging in deel A. Hij is nodig omdat §3.4 het systeem en de hoofdcontainer hier dezelfde naam geeft.

Binnen `view … of X` overschaduwen unieke afstammelingen van X het eerste segment van een FQN. Een kind met de naam van het systeem geeft daardoor een harde fout (`Could not resolve reference`), en een kind met de naam van een extern systeem of persoon maakt views stil onjuist. Een component met de naam van zijn container is geen probleem.

**Wijziging:** `likec4_ids.py:41–53` wijst eerst id's toe aan wortelelementen en reserveert die voor alle geneste elementen. In het prototype bleven `model.c4` en `views.c4` op een contract zonder botsing byte-gelijk, en view-id's zijn afgeleid van neutrale id's. Alleen botsende FQN's veranderen. Alle 18 onderzochte gevallen slaagden in de fork.

De fork zelf verandert niet.

## 12. Afwijkingen en punten ter bevestiging

1. **Waar de projectinstelling staat.** `.chunkhound.json` staat in `.gitignore` en bestaat in deze repository niet, en de globale configuratie geldt voor alle projecten. Besloten: een lokaal `.chunkhound.json` met alleen de sectie `c4`, en de regel in `.gitignore` laten staan. Daardoor kan een andere ontwikkelaar een andere kaart krijgen.
2. **Containers per manifest in deel A.** Een library zonder proces en een manifest met meerdere processen worden allebei één container. C4 noemt een library geen container, en de daemon blijft hier een component. Deel B lost het tweede op. Het eerste geldt voor een project zonder startpunt; dat krijgt zoals nu één container.
3. **`scripts/`, `.github/` en vergelijkbare bestanden** staan in `files` van de hoofdcontainer. Ze draaien daar niet. De runtimeregel houdt ze wel uit componenten. Deel B beperkt dit.
4. **Bestanden in één map blijven samen.** Dat wijkt af van de C4-gedachte dat verpakking los staat van componenten. Per bestand splitsen bleek in de proef niet herhaalbaar.
5. **Interface blijft een benadering.** Het model ziet namen en verwijzingen, geen interfaces. Elk element is met bronnen te controleren, maar of het inhoudelijk klopt, moet een mens beoordelen.
6. **Opslag met de eigen naam als technologie.** Het element is hier de database-engine zelf, bijvoorbeeld DuckDB. Dat is niet los onderbouwd.
7. **Technologie op relaties blijft leeg.** C4 vraagt een protocol op pijlen tussen containers. Deel A kent dat niet en telt het in het rapport.
8. **Containers kunnen `files: []` hebben.** AutoDoc-spec r. 23 en 25 zegt dat aangetroffen containers expliciete bestanden hebben. Bij directe bestanden geldt dat niet voor opslag en voor containers waarin alles in componenten zit. De loader staat dit toe. Bij de eerdere uitvoer gold dit voor 5 van de 13 containers.
9. **`merged_labels[]` is niet strikt één regel per paar**, en vervalt als een onderliggende relatie is weggelaten (§7.5).
10. **Bronlinks vragen een schone checkout binnen de scope** (§9). De uitsluiting uit §3 haalt `.superpowers/` hier uit de scope.
11. **Alleen de melding `input_too_large` wordt herkend** als geweigerde invoer. Een andere provider kan bij een te grote prompt de run nog steeds afbreken, zoals nu. `fits()` beperkt dat vooraf.
12. **Een te grote container** krijgt blijvend geen componenten totdat de prompt past. Het rapport meldt dat.
13. **Deployment-diagram.** C4 raadt dit aan voor productie; het ontbreekt.
14. **`HEAD` van een geneste repository** wordt niet vergeleken met de start van de run. Een commit daarin tijdens de run kan een link naar een verschoven regel geven. Dat is zeldzaam, en de controle vraagt extra code die deel A niet nodig heeft.
15. **Documentrelaties met de naam van het systeem** koppelen aan de container (§3.4). Een document dat het hele systeem bedoelt, wordt zo aan de hoofdcontainer gehangen.

## 13. Gemeten

Zonder provider gemeten op deze repository, met prototypes buiten de repository.

| Invoer voor de merge-stap (`container:chunkhound`, 553 bestanden, 83 mappen) | Tekens |
|---|---|
| Huidige prompt met 12 groepen na uitsluiting | ~32.000 |
| Mappen, compact, met `file_links` | ~33.000 |
| Mappen, compact, met `file_links` en `symbols` | ~105.000 |

**Proefantwoorden** (Sonnet-subagents in plaats van de provider): alle geldig. Bij de drie proeven met de runtimeregel staan 0 bestanden uit `scripts/`, `.github/`, `operations/` of `.claude/` in componenten. Met `symbols` gaven twee proeven 19 en 20 componenten, met 77% overeenkomst; `src/` en `core/config` werden daarbij beter gescheiden dan zonder `symbols`.

**Kaart** op die twee proefantwoorden, met één container per manifest, door `ModelLoader`, views en schrijver met 0 waarschuwingen: 19–20 componenten, 78–91 relaties, 29–30 views, 0,5 MB DSL, build 2,8 s. Die meting gebruikte een andere containernaam dan de systeemnaam; met dezelfde naam gaf hetzelfde model zonder naamfix 777 validatiefouten.

**Bestanden:** 571 in de scope en 91 mappen, waarvan 553 en 83 in `container:chunkhound` en 18 en 8 in `container:chunkhound-site`.

**Niet gemeten:** de echte provider, de kaart na §3.4 en §11 samen, en de Git-opdrachten uit §9 tegen een echte remote.

## 14. Code en documenten

| Bestand | Wijziging |
|---|---|
| `core/config/c4_config.py`, `core/config/config.py` | nieuwe sectie `c4` |
| `c4/files.py`, `c4/documented.py`, `c4/pipeline.py`, `commands/code_mapper.py` | filters uit §3; `list_scope_files` krijgt de uitvoermap en de scope-naam; `doc_files_for` krijgt de configuratie via `finish_c4` |
| `c4/runtime.py` | systeemnaam, `cdylib`-regel, manifestomschrijving, technologie |
| `c4/grouping.py` | §4.1 |
| `c4/merge.py`, prompt `c4_merge.md`, `c4/llm.py` | §4.2 tot en met §4.5 |
| `c4/pipeline.py`, `c4/assemble.py` | §4.5, §5, geen `tree_spec`; `_identify` en `_build_lock` nemen componenten over; markering op het element; gelijkspel bij documentrelaties (§3.4) |
| `c4/model.py`, `c4/lockfile.py`, `c4/schemas/` | §5, §6; regenereren via `scripts/generate_c4_schemas.py` |
| `c4/contract.py` | nieuw |
| `c4/writer.py`, `commands/code_mapper.py`, `code_mapper_parser.py` | namen, contract, rapport |
| `c4/codeboarding/names/` en `tests/code_mapper/c4/codeboarding/names/` | verwijderen; `source_inspector`, `hierarchy_fallback`, `models`, `config`, `LICENSE` en bestandskoppen blijven (`references.py:14`, `pyproject.toml:170`) |
| `autodoc/architecture/likec4_ids.py` | §11 |

**Documenten**
- Map-spec r. 26, 50, 61, 83, 97, 120, 146–147, 153: bouwstenen, namen en lockvelden, met een verwijzing naar deze spec.
- `docs/melly/models/map-structuuranalyse.md` r. 269: de nieuwe bestandsnamen.
- AutoDoc-spec r. 23, 25: containers zonder bestanden. AutoDoc-besluitenlog: nieuwe rij voor de naamfix en deze afwijking.
- `site/src/pages/docs/cli-reference.md:356–358` en `site/src/pages/docs/changelog.md:25`: de zin over de C4-sidecar en de bestandsnamen.
- `CHANGELOG.md`: nieuwe vermelding met de hernoemde bestanden en de lockversie; regel 17 blijft historisch.

## 15. Testen

Contracttests volgens `AGENTS.md`, op de CLI-route met de bestaande nep aan de providergrens.

**Bron en bouwstenen**
1. Testmappen en -bestanden vallen weg, ook hun manifesten; `exclude_test_code: false` zet ze terug; `c4.exclude` geldt voor code en documentatie; `collect_scope_files` voor HyDE geeft ze nog steeds.
2. Changelog en bestanden in verborgen mappen zijn geen documentatiebron.
3. De systeemnaam volgt de drie stappen uit §3.4; een `cdylib` naast `pyproject.toml` wordt geen container, ook niet bij een "ja" van het model; een documentrelatie met de gedeelde naam koppelt aan de container.
4. Een nieuw bestand in een bekende map vraagt geen aanroep; een nieuwe map vraagt er één en mag aan een bestaande component gekoppeld worden.

**Merge**
5. Een antwoord met een onbekende of dubbele plaatsing wordt hersteld, de rest gaat naar de smalle herkansing, en wat overblijft staat niet in het lockbestand. Aliassen in plaatsingen en titels komen terug als echte id's.
6. Een afgekapt antwoord en een geweigerde invoer breken de run niet af; een te grote prompt doet geen aanroep en meldt de reden.
7. **Mislukte merge-stap:** geen nieuwe componenten; vastgelegde componenten, ook met een verdwenen map, en hun id's blijven; geen tombstone; `base_sha` blijft; de waarschuwing verschijnt; de volgende run probeert opnieuw; een andere container in dezelfde run wordt wel vastgelegd. Na een mislukking gevolgd door een hernoeming blijft de component-id behouden.

**Stabiliteit**
8. **Twee runs:** de tweede volledige run op dezelfde invoer doet geen merge-aanroep en geeft een byte-gelijk contract, ook als `--out` in de repository staat. Topics zijn in deze test gelijk.
9. **Oud lockbestand:** versie 3 geeft de melding met het pad, geen validatiefout; ook een lockbestand zonder object of versie. Een `overrides.placements` met een onbekende groep geeft de rapportregel.

**Contract**
10. **Loader-contract:** op de fixturerepository geeft `ModelLoader.load` een model terug zonder waarschuwing.
11. **Namen:** een volledige run schrijft alle drie de bestanden; de oude bewijsnaam is weg.
12. **Proefrun:** geen contract, en een bestaand contract blijft byte-gelijk.
13. **`--no-c4`:** byte-gelijke uitvoer, geen van de drie bestanden.
14. **Vertaling:** soorten, status, ouders, technologie, omschrijvingen, stabiele en unieke bron-id's.
15. **Weglaten:** component zonder container, relatie naar weggelaten element en element zonder bron ontbreken en worden geteld; het interne paar behoudt ze.
16. **Directe bestanden en topics:** een container bevat de bestanden van zijn component niet; een topic dat alleen componentbestanden citeert, dekt de container niet direct.
17. **Labels:** twee titels geven een label, één niet; een te lang label of een weggelaten onderliggende relatie geeft geen label.
18. **Bronlinks**, op echte tijdelijke Git-repository's, met `update-ref` voor `refs/remotes/origin/main`: commit op `origin` geeft de URL; niet gepusht, gewijzigd of niet-gevolgd bestand geeft `null` met reden, ook met spaties, niet-ASCII en na een hernoeming; geen Git-map geeft `NO_GIT_HEAD`; indexroot als submap en een ongeldige geneste `.git` geven `null`; een geneste repository krijgt een eigen regel.
19. **Inloggegevens:** tokens verdwijnen bij `https`, `http`, `ssh` en `gebruiker@host:pad`; `git@` en `ssh://git@` blijven staan.
20. **Terugval en `--no-markdown`:** beide schrijven een contract dat zonder waarschuwing laadt.

**AutoDoc**
21. `LikeC4IdAllocator` geeft een kind met de naam van een wortelelement een andere id, en id's zonder botsing blijven gelijk. Dit draait altijd.
22. **Einde-tot-einde zonder provider:** een fixture-run gevolgd door AutoDoc koppelt `topics[].file` aan een echte `DocsitePage`.
23. **Fork:** een systeem en container met dezelfde naam valideren, en een kind met de naam van een extern systeem of persoon geeft juiste views; `likec4 build` slaagt. Geen bestaande architectuurtest draait `likec4`, dus deze test heeft Node en het meegeleverde archief nodig en wordt zonder Node overgeslagen.

**Acceptatie met provider, aparte goedkeuring:** een nieuw lockbestand, een echte maprun op deze repository en `chunkhound autodoc`. Daarbij worden gecontroleerd: of de hoofdcontainer echte componenten krijgt, of geen fixtures of procesdocumenten in de kaart staan, hoe vaak het merge-antwoord geldig is, en het oordeel van een mens over de kaart. Dit antwoord is ook de invoer voor deel B.

Verplicht volgens `AGENTS.md`: smoke tests, ruff en mypy, en de volledige suite vóór een PR.

## 16. Risico's

- **Echte provider onbekend.** Alle componentresultaten komen van Sonnet-subagents.
- **Kaart nog niet volledig C4.** Op containerniveau blijft de afwijking tot deel B staan.
- **Geen koppeling tussen contract en index.** Het contract heeft geen run-id, dus een oud contract naast een nieuwe index valt niet op. Dat kan na een crash tussen paar en contract, na `--no-markdown` of `--no-c4` in een bestaande uitvoermap, en tijdens een run.
- **Uitvoer groeit met de grootte.** De invoer is voor deze repository ongeveer 105.000 tekens. Bij grote projecten vervallen `symbols`, en het resultaat is dan zwakker.
- **Remote-config.** `Config.c4` raakt de terminal delta gate niet; de planreview bevestigde dit met een proefklasse. Een geldige `c4` is wel op afstand instelbaar, omdat `REFUSED_PATHS` (`remote/pipeline.py:54`) een verbodslijst is. Een externe configuratie kan dus bronnen uit de kaart houden, zoals die ook andere instellingen kan zetten.
- **Remote-informatie is lokaal.** `origin/*` kan verouderd zijn, en een commit die later verwijderd is, geeft een dode link.
- **`run_git` negeert de globale Git-configuratie** (`git_safe.py:25–36`). In een container met een andere gebruiker kan dat "dubious ownership" geven, dus `NO_GIT_HEAD`.
- **Task6** blijft open, en AutoDoc is op deze branch niet definitief geaccepteerd. Een kaart die rendert, sluit dat niet af.
