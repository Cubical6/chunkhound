# Spec deel A: `map` levert een C4-kaart voor AutoDoc (O-MAP)

- Datum: 2026-11-04 · Branch: `c4/shared-extraction-layer` (HEAD bij start `cfb59235`)
- **Status:** goedgekeurd op 2026-11-04, inclusief de punten uit §12 en de wijzigingen in §3.1 en §16 na de planreview; plan goedgekeurd; geen providerrun goedgekeurd. §17 goedgekeurd op 2026-11-04, inclusief één providerrun en de eenmalige ingreep in het lockbestand. §18 goedgekeurd op 2026-11-04, inclusief één providerrun. §20 goedgekeurd op 2026-11-05 na spec-review; plan volgt; geen providerrun goedgekeurd
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
3. Het interne paar blijft volledig. Weglaten geldt alleen voor het contract, en elke weglating wordt geteld. Uitzondering: `drop` en `merge` uit het lockbestand (§20) halen elementen, relaties en hun citaten bewust ook uit het interne paar; de referenties zelf blijven staan.
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

> Vervangen door §18.1: de kandidaten volgen niet meer uit topics. De uitsluitingen hieronder blijven gelden.

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

## 17. Aanvulling na de eerste echte run

**Aanleiding.** De run op `9457f168` gaf de hoofdcontainer 18 echte componenten, zonder fixtures of procesdocumenten. De kaart voldoet toch niet aan C4: 95 van de 105 relaties hebben een titel zonder inhoud, 30 van de 33 externe systemen hebben geen relatie, en 15 relaties lopen tussen een container en zijn eigen component. Deze aanvulling herstelt dat vóór deel B. Elementen en id's van componenten blijven gelijk, net als het lockformaat (versie 4).

### 17.1 Eigen namen

`ChunkHound` staat in de documentuitkomst als container, extern systeem en component. Daardoor is de term ambigu, en vervallen de relaties ermee, waaronder die naar de providers.

**Regel.** Een documentterm van soort `external`, `container` of `component` wordt geen nieuw element als zijn genormaliseerde naam (`slugify_kebab`, als in R4) gelijk is aan die van het eigen systeem, een container of opslag. Het citaat en de term gaan naar dat bestaande element; bij systeem plus container is dat de container (§3.4). Blijft er meer dan één kandidaat over, dan verandert er niets. Personen vallen buiten deze regel.

Dit lost ook DuckDB en LanceDB op, die nu zowel opslag als extern systeem zijn. Geen modelaanroep.

### 17.2 Externe systemen en personen zonder relatie

C4 toont een persoon of extern systeem omdat die met het systeem samenwerkt. Zonder relatie is daar geen grond voor.

**Regel, alleen in het contract.** Een extern systeem of persoon blijft staan als er minstens één contractrelatie is met een intern element (systeem, container, opslag of component). Andere vervallen, met hun relaties, zoals GitHub Actions → PyPI. Het interne paar blijft compleet (invariant 3).

**Rapport.** Omdat deze regel ook echte systemen kan raken, noemt het rapport ze bij naam:

```text
C4-contract zonder relatie weggelaten: <n> externe systemen (<namen>), <n> personen (<namen>)
```

Dit vult §7.2 en §8 aan. Geen modelaanroep.

### 17.3 Relaties van directe bestanden

Een container is eigenaar van de bestanden die in geen component zitten (`assemble.py:215`). Elke verwijzing daarvan wordt een relatie van of naar de container. Dat geeft pijlen tussen een container en zijn eigen component, die C4 niet kent: een component zit ín de container. Deel B kan bovendien geen relatie afbeelden die eindigt op een gesplitste container.

**Regels.** Een relatie telt niet mee voor kaart en labels als:

- **a.** ze loopt tussen een container en een component van diezelfde container;
- **b.** ze een aangetroffen relatie is van een container naar een doel, terwijl een component van die container ook een relatie met dat doel heeft. De containerview toont die pijl dan al.

Andere relaties blijven: een container zonder componenten houdt zijn pijl naar opslag, en een relatie naar een container vanaf buiten blijft staan.

**Waar.** Eén pure functie bepaalt deze set. `derive_views` en `build_contract` gebruiken hem allebei, zodat een label nooit vervalt door een onderliggende relatie die hier wegvalt (§7.5). Het interne paar houdt de relaties.

**Rapport.** De regel `C4-contract weggelaten` krijgt `<n> relaties binnen een container` en `<n> overbodige relaties van directe bestanden`.

**Gevolg.** In deze run gaat het om alle 17 relaties met `container:chunkhound` als eindpunt: 15 naar eigen componenten en 2 naar opslag, waar `Databaseopslag` al naar wijst. Daarmee vervallen ook echte afhankelijkheden, zoals `Realtime-indexering` naar `chunkhound/watchman_runtime`, want die map hangt direct onder de container. De kaart toont die dan niet; het bewijs wel.

### 17.4 Titels

Het model krijgt nu alleen een hash en aantallen per soort (`merge.py:687`) en kan dus niets over de bedoeling zeggen.

**Invoer per relatie:**

```json
{"fingerprint": "...", "from": {"name": "...", "description": "..."},
 "to": {"name": "...", "description": "..."}, "kinds": {"call": 3},
 "targets": ["<ten hoogste 5 bereikte bestanden of pakketten>"]}
```

**Prompt.** Een titel van ten hoogste 60 tekens begint met een werkwoord en zegt waarvoor de bron het doel gebruikt. Hij beschrijft niet het mechanisme ("importeert", "roept aan", "via codeverwijzingen"). Hij gebruikt alleen wat de feiten dragen; ontbreekt een specifieke bedoeling, dan wordt het "gebruikt <doel>". De lengte staat alleen in de prompt: een te lange titel keurt niet het hele antwoord af.

**Cache.** `relation_fingerprint` krijgt de hash van `c4_titles.md` erbij. Een gewijzigde prompt geeft zo nieuwe titels. Deze cache is de enige die een promptversie kent: classificaties en documentuitkomsten zijn bewust stabiele beslissingen (§17.5).

**Grenzen,** als in §4.3 en §4.5: past de prompt niet, dan vervallen eerst `targets`, en daarna volgt de terugvaltitel met de reden in het rapport. Hetzelfde geldt voor geweigerde invoer. Terugvaltitels gaan niet in het lockbestand.

### 17.5 Provider-SDK's

Geen enkel van de 155 kandidaten is `external_system`: `openai`, `anthropic` en `voyageai` kregen 2 tegen 1 `library`. De code levert daardoor geen pijl naar een provider, terwijl de verwijzingen er zijn.

**Prompt `c4_classify.md`.** Bij `external_system` komt erbij dat een SDK of client die bestaat om één extern beheerde dienst aan te roepen hieronder valt, ook al draait zijn code in het proces. Een algemene HTTP-client of parser die geen dienst aanwijst, blijft `library`. `library` blijft de veilige standaard.

**Eenmalig in dit lockbestand.** De cache kent geen promptversie, en dat blijft zo, omdat opnieuw stemmen ook stabiele keuzes kan omdraaien, zoals `site/package.json` (2 tegen 1). Daarom haal ik vóór de run alleen de vermeldingen met waarde `library` of `external_system` uit `classifications`. Opslag en de vragen over containers blijven staan. Andere repository's hebben nog geen lockbestand versie 4, want deze branch is niet uitgebracht. Vóór de ingreep maak ik een kopie, omdat het lockbestand niet in Git staat.

### 17.6 Run en acceptatie

Eén volledige run plus `chunkhound autodoc` en `npm run build`. C4-aanroepen: 3 classify, 1 titels en 1 labels. `documented` blijft in de cache, behalve als topics andere documenten citeren. Daarbovenop komen HyDE en de researches, samen ongeveer 30 minuten, en AutoDoc, ongeveer 18 minuten.

**Controles op de uitvoer:**

1. geen merge-aanroep, dezelfde 19 componenten en id's;
2. geen titel met "codeverwijzingen", en een steekproef van 20 titels tegen de code, want een statische verwijzing bewijst een afhankelijkheid en geen bedoeling;
3. elk extern systeem en elke persoon in het contract heeft een relatie; `extern:chunkhound` en `extern:duckdb` bestaan niet meer;
4. pijlen van `LLM-providers` of `Embeddingproviders` naar externe systemen;
5. geen relatie tussen een container en zijn eigen component in het contract;
6. labels met twee of meer titels aanwezig, en `ModelLoader` en de LikeC4-build zonder waarschuwing.

**Verwacht, afgeleid en niet gedraaid:** ongeveer 12 externe systemen en 2 personen. Ollama verdwijnt waarschijnlijk van de kaart, want er is geen pakket en geen relatie die het draagt.

### 17.7 Testen

Contracttests volgens `AGENTS.md`, op de bestaande routes:

1. Een externe documentterm met de naam van een container, opslag of het systeem geeft geen element, en een documentrelatie met die term koppelt.
2. Contract zonder onverbonden extern systeem en persoon, met telling en namen; het interne paar houdt ze; een persoon of extern systeem met een relatie blijft.
3. Regels a en b, met de tegenvoorbeelden: een container zonder componenten houdt zijn pijl, en een label blijft bestaan als een relatie uit regel b onder dezelfde pijl valt.
4. Het titelverzoek bevat namen, omschrijvingen en doelen; een gewijzigde prompt vraagt nieuwe titels, en dezelfde prompt niet.
5. Een te grote of geweigerde titelprompt breekt de run niet af en gaat niet in het lockbestand.

### 17.8 Bewust niet

- **Omschrijvingen van externe systemen en personen:** §5 blijft staan. C4 vraagt ze wel, dus de 40 lege omschrijvingen uit het rapport worden minder, maar verdwijnen niet.
- **Misleidende mapnamen,** zoals `chunkhound/utils`: groepen blijven per map (§12, punt 4).
- **Runtimecode die direct onder de container hangt,** zoals `watchman_runtime`: de merge-keuze blijft staan; een gebruiker kan die met `overrides.placements` veranderen.
- **Weergavenaam:** een extern systeem uit een pakket heet `openai`, niet `OpenAI`.
- **`c4_documented.md` herschrijven:** dat maakt alle documentuitkomsten ongeldig en voegt onzekerheid toe. Personen die de documenten niet noemen, zoals een MCP-client, blijven dus ontbreken.
- **Protocollen op relaties tussen containers:** §12, punt 7. De telling daarvan daalt in deze run naar 0, terwijl dit niet is opgelost. Deel B pakt dit op.

## 18. Herziening van de documentstap

**Aanleiding.** Na §17 bevat het contract nog 17 externe systemen, waarvan ruim de helft geen systeem is, en geen enkele persoon. Twee metingen verklaren dat:

- **De bronnen wisselen per run.** Tussen de twee runs veranderde de set, omdat ze volgt uit wat de topics citeren. Daardoor draait de stap opnieuw en verandert de kaart, zonder dat de documenten veranderden. Tot de set behoorden ook `c4_merge.md`, `hyde_scope_prompt*.md` en `src/AGENTS.md`; uit de eerste kwam de relatie "Components → container".
- **De prompt definieert de soorten niet.** Van de 88 elementen zijn er 70 `external`, zoals `CLI flags`, `MIT`, `.gitignore` en `` `asyncio.gather` ``. Er is 1 `person`. Gemini en Grok staan alleen in een tabel en krijgen daardoor geen relatie, zodat §17.2 ze laat vallen.

Dit vervangt de keuze "citerende documenten" (besluit rij 23) en §3.2, en haalt de documentstap uit §17.8.

### 18.1 Vaste bronnen

`doc_files_for` hangt niet meer af van topics. De kandidaten zijn `README*` in de scope-wortel en alle Markdown uit de bestandslijst van de run (§3.1). Daarmee gelden de testregels, `c4.exclude` en de eigen uitvoer al. Daarna vallen weg:

- zoals nu (§3.2): paden met een map die met `.` begint, en historiedocumenten;
- **nieuw, geen documentatie over het systeem:** bestanden die beginnen met `agents` of `claude`, of waarvan de naam `license` bevat, en paden met een map `prompts` of `vendor`, zonder hoofdlettergevoeligheid.

Topics bepalen alleen nog de volgorde van de aanroepen (`order_hint`). Op deze repository blijven 13 documenten over, tegen 14 in de vorige run.

**Gevolg:** zolang documenten niet veranderen, is de uitkomst gelijk en is er geen aanroep (`documented.py:515`). De kaart hangt dan niet meer van de research af.

### 18.2 Prompt `c4_documented.md`

De prompt krijgt de systeemnaam en de C4-definities, en vraagt alleen nog `person` en `external`:

- **`person`:** een menselijke rol of groep die het systeem gebruikt en die het document noemt.
- **`external`:** een softwaresysteem buiten deze repository, met eigen beheer of eigen proces, dat het systeem aanroept of dat het systeem aanroept. Voorbeelden: een gehoste API, een modelprovider, of een AI-assistent die via MCP aanroept.
- **Niet als element:** bestandsformaten, protocollen, configuratiemiddelen, bibliotheken en frameworks, build-, test- en publicatiegereedschap, licenties, communitykanalen, taalconstructies en onderdelen van het systeem zelf.
- **Term:** de kale naam (`Astro`, niet `Astro 7`), één naam per element, nooit "A of B". De term moet letterlijk in het citaat staan, zoals nu.
- **Omschrijving:** één korte zin in het Nederlands, op basis van het citaat. C4 vraagt die voor elk element; zonder bruikbare tekst blijft ze leeg.
- **Relaties:** alleen met minstens één persoon of extern systeem als eindpunt. Voor een onderdeel van het systeem gebruikt de relatie de systeemnaam. Een tabel of lijst van ondersteunde diensten geldt als uitspraak: elke rij geeft een relatie, met de rij als citaat. De richting volgt wie wie aanroept of gebruikt.

Het geldige antwoord (`_FragmentElement.kind`) wordt `person` of `external`. `DocElement` blijft breder, zodat bestaande uitkomsten leesbaar blijven. De regel "geen eigen afleiding uit voorkennis" blijft staan.

**Gevolg:** elementen uit documenten van soort `container` en `component` ontstaan niet meer. Een interne relatie uit alleen documentatie verdwijnt dus. De `component`-elementen haalden het contract al niet, en een container die alleen in documentatie staat komt niet meer op de kaart.

### 18.3 Cache

`LockedDocumented` krijgt `version: str = ""`, met de bestaande versie van het doel (`_DocumentedGoal.version`: prompt, schema, validatie). Het lockbestand wordt alleen hergebruikt als documenten én versie gelijk zijn. Een oude vermelding heeft een lege versie en wordt dus opnieuw bepaald, zonder lockversie omhoog en zonder handmatige ingreep. Dit neemt voor deze stap het risico op schijnsucces weg dat §17.4 ook voor titels oploste.

### 18.4 Samenstellen

- Een omschrijving uit een document komt op het element, behalve als een override die vervangt.
- Een extern systeem uit een pakket krijgt de documentterm als weergavenaam (`OpenAI`, niet `openai`), als beide dezelfde id geven. De eerste term op citaatpositie wint, zodat de naam stabiel is. Een override gaat voor.

§17.1 en §17.2 blijven gelden. §17.2 blijft de vangnetregel: een element zonder relatie haalt de kaart niet.

### 18.5 Run en acceptatie

Eén volledige run plus `chunkhound autodoc` en `npm run build`. Classificatie, merge en titels blijven in de cache, dus de C4-kosten zijn alleen de documentstap: naar schatting 3 tot 6 aanroepen. HyDE en de researches draaien wel (ongeveer 30 minuten), AutoDoc ongeveer 15 minuten.

**Controles:**

1. geen prompts, `AGENTS.md`, licenties of `vendor` in de bronnen;
2. geen formaten, configuratiemiddelen, build- of publicatiegereedschap als extern systeem in het contract;
3. echte providers op de kaart, met relaties, ook die uit de tabel;
4. minstens één persoon met een relatie;
5. externe systemen en personen hebben een omschrijving, op een enkele na;
6. `ModelLoader` en de LikeC4-build zonder waarschuwing.

**Onzeker:** de scheiding hangt van het model af, dus er kan ruis blijven of een echt systeem wegvallen. Ik voeg daarvoor geen lijst met namen toe, omdat die niet voor andere repository's geldt; `overrides` blijft de uitweg. Een tweede run om stabiliteit te bewijzen doe ik niet; dat toetst test 1 hieronder zonder provider.

### 18.6 Testen

Contracttests op de bestaande routes:

1. Dezelfde bestanden met andere topics geven dezelfde documentset, en de tweede run doet geen documentaanroep.
2. Prompts, `AGENTS.md`, licenties en `vendor` vallen af; andere Markdown en `README*` in de scope-wortel blijven; `c4.exclude` en de testregels gelden.
3. Een gewijzigde promptversie bepaalt de uitkomst opnieuw; gelijke versie en documenten doen geen aanroep; een lockvermelding zonder versie wordt opnieuw bepaald.
4. Een antwoord met soort `component` of `container` wordt niet aanvaard; oude uitkomsten met die soorten blijven leesbaar.
5. Omschrijving en weergavenaam komen op het element, en een override gaat voor.

### 18.7 Bewust niet

- **Componentnamen en -indeling:** de misleidende titels uit de steekproef blijven bestaan (§17.8). Dat is de volgende stap na deze.
- **Providers zonder pakket of documentrelatie:** die blijven weg; dat is §17.2.
- **Protocollen, processen en deel B:** ongewijzigd.

## 19. Engels en strengere documentstap

**Aanleiding.** In run 3 (`e2b7d693`) zijn 14 relatietitels en 9 omschrijvingen Pools. Ze komen uit één cachebundel over `site/src/pages/docs/configuration.md`, terwijl de bron Engels is. De prompt vroeg Nederlands, de validatie (`_DocumentedGoal.validate`) toetst geen taal, en het lockbestand houdt de uitkomst vast zolang documenten en versie gelijk zijn. Daarnaast toetst de validatie bij een relatie niet of de eindpunten in het citaat staan. De gebruiker kiest Engels voor alle uitvoer en vaste teksten van de kaart, een nieuw lockbestand, geen automatische taalcontrole, en een herbouwde LikeC4-fork. Dit vervangt de keuze voor Nederlandse titels en terugvaltitels uit het plan van de structuuranalyse en de Nederlandse omschrijving in §18.2.

### 19.1 Engels

- **Prompts:** `c4_documented`, `c4_merge`, `c4_summaries` en `c4_titles` vragen Engels voor titels, namen, labels en omschrijvingen. `c4_classify` levert geen tekst.
- **Terugvaltitels:** `inherits from`, `calls`, `imports`; ook in de verbodsregel van `c4_titles`.
- **Id-prefixen:** `system:`, `container:`, `storage:`, `external:`, `person:`, `component:`.
- **Status:** `found` en `documented`, in het contract, het model van AutoDoc, de LikeC4-tag `documented` en de legenda.
- **Vaste teksten:** rapportregels en foutmeldingen van `map` en de C4-stappen, en de teksten van `likec4_writer` (`+N relations`, `sources`).
- **LikeC4-fork:** de kop boven de bronlinks in het detailpaneel wordt `sources`. De fork krijgt versie `1.60.0-chunkhound.2`, zodat een npm-cache het oude archief niet hergebruikt.

### 19.2 Versies

- **Lockversie 5** (`SCHEMA_VERSION`). Een lockbestand met versie 4 geeft de bestaande melding "Delete it and run `chunkhound map` again". Daarmee vervallen alle opgeslagen classificaties, merges, titels, labels en documentuitkomsten, ook die met Nederlandse tekst of Nederlandse id's. Bewijs en kaartmodel volgen dezelfde versie.
- **Contractversie 2** (`CONTRACT_VERSION`). Het model van AutoDoc aanvaardt alleen versie 2; een oud contract met Nederlandse statussen geeft een duidelijke versiemelding in plaats van een fout op een onbekende status.

### 19.3 Documentstap

- **Eindpunten in het citaat:** een relatie wordt alleen aanvaard als elk eindpunt gelijk is aan de systeemnaam, of letterlijk in de geciteerde regels staat. Dat is dezelfde regel als voor de term van een element. De systeemnaam blijft vrij, omdat de prompt die voorschrijft voor elk onderdeel van het systeem. Een fragment waarvan geen enkel voorstel overblijft, wordt zoals nu afgekeurd.
- **Hele woorden** (na de review van run 4): een elementterm of eindpunt telt alleen als het als heel woord in de geciteerde regels staat, dus `Go` niet in "Google" en `AI` niet in "MAIN". Witruimte mag verschillen; hoofdletters niet. Het citaat zelf blijft een gewone letterlijke deelreeks. De regel geldt ook voor elementen uit een teruggevallen fragment en uit een eerder lockbestand.
- `_VALIDATOR_VERSION` wordt 2, en met de regel voor hele woorden 3, zodat cache en lockvermelding opnieuw worden bepaald.
- **Geen taalcontrole** (keuze van de gebruiker). Een antwoord in een andere taal kan dus weer in het lockbestand belanden; `overrides` of een nieuwe versie van de stap is dan de uitweg.

### 19.4 Run en acceptatie

Het oude lockbestand moet weg; de volgende run roept dus classificatie, merge, titels, labels en de documentstap opnieuw aan. Die run vraagt aparte goedkeuring.

**Controles:**

1. geen Nederlandse of andere niet-Engelse tekst in het contract (handmatige steekproef van titels, namen en omschrijvingen);
2. alle id's met Engelse prefixen, statussen `found` en `documented`;
3. elke documentrelatie heeft haar eindpunten, of de systeemnaam, in het citaat;
4. `ModelLoader` en de LikeC4-build zonder waarschuwing, en het detailpaneel toont `sources`.

### 19.5 Testen

Bestaande contracttests volgen de nieuwe prefixen, statussen en teksten. Nieuw:

1. Een documentrelatie met een eindpunt dat niet in het citaat staat, wordt niet aanvaard; de systeemnaam als eindpunt wel.
2. Een lockbestand met versie 4 wordt geweigerd met de melding om het te verwijderen.
3. AutoDoc weigert een contract met versie 1.
4. Een elementterm of eindpunt dat alleen als deel van een woord in het citaat staat, wordt niet aanvaard.

### 19.6 Bewust niet

- **Taalcontrole:** zie §19.3.
- **Personen samenvoegen, componentnamen en -indeling, deel B:** ongewijzigd (punten 3 tot en met 5 van de review van run 3).

## 20. Ruis onder externe systemen en personen

**Aanleiding.** Run 4 (`.scratch/omap-a4/map`, besluit rij 153) levert 33 externe systemen. Een deel daarvan is geen concreet systeem:

| Soort ruis                                | Elementen                                                                       | Bron                                                                                                    |
| ----------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Bibliotheek uit de documentatie           | `httpx`                                                                         | `site/src/pages/docs/configuration.md:307-314`, "per-phase `httpx` timeout"                             |
| Algemene categorie, geen concreet systeem | `llm`, `llm-provider`, `embedding`, `embedding-provider`, `embedding-providers` | o.a. `operations/README.md:26-28`, `README.md:148-155`, `chunkhound/providers/embeddings/README.md:1-3` |
| Voorbeeldtekst, geen afhankelijkheid      | `stripe`                                                                        | `README.md:117-123`, `chunkhound websearch "Stripe webhook retry schedule"`                             |
| Importnaam van een SDK naast de dienst    | `google` (`found`) naast `gemini` (`documented`)                                | `chunkhound/providers/llm/gemini_llm_provider.py:20-21`, `configuration.md:502`                         |
| Rol als extern systeem                    | `operator-controlled-https-endpoint`                                            | documentatie                                                                                            |

Daarnaast staan dezelfde rol of hetzelfde systeem soms twee keer op de kaart: `operator`/`operators`, `ai-agent`/`ai-assistant`.

De bestaande uitweg is beperkt. `overrides.classifications` werkt alleen op de sleutel van een kandidaat uit de code (`classify.py:76`). Voor een element uit de documentatie kun je alleen de naam of omschrijving overschrijven (`assemble.py:452-455`). §18.5 sloot een lijst met namen uit en noemde `overrides` de uitweg; die uitweg bestaat voor documentelementen dus nog niet. De gebruiker kiest: de prompt aanscherpen én een override om een element weg te halen of samen te voegen; beide alleen voor externe systemen en personen; een categorieregel alleen voor externe systemen (personen mogen een rol zijn); en de nabewerking als aparte stap na de assemblage.

**Regels.** In het modelbestand staan al R1-R12, dus de nieuwe regels heten daar R13-R16 (in het ontwerpgesprek R7-R10):

| #    | Regel                                                                                                                                                                                                                      | Voorbeeld → verwachte uitkomst                                                                                                                         |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| R13  | `drop` haalt een extern systeem of persoon weg uit kaartmodel, bewijs en contract, met alle relaties die het raakt                                                                                                         | `"drop": ["external:httpx"]` → geen `external:httpx`, geen relatie `chunkhound -> httpx`; de run slaagt                                                |
| R14  | `merge` voegt een extern systeem of persoon samen met een doel van dezelfde soort. Het doel houdt naam, omschrijving en id; citaten en relaties gaan mee, dubbele relaties vallen samen en de status wordt opnieuw bepaald | `"merge": {"external:google": "external:gemini"}` → alleen `external:gemini`, status `found`, met het citaat uit `gemini_llm_provider.py:20`           |
| R15a | Een extern systeem is nooit een categorie of rol zonder eigen naam; personen mogen een rol zijn                                                                                                                            | "requires an embedding provider" → geen `embedding-provider`; `operator` als persoon blijft                                                            |
| R15b | Geen naam die alleen in een voorbeeldcommando, voorbeeldvraag of voorbeeldcode staat                                                                                                                                       | `chunkhound websearch "Stripe webhook retry schedule"` → geen `stripe`. Tegenvoorbeeld: "DuckDuckGo provides web search results" → `duckduckgo` blijft |
| R15c | Een bibliotheek blijft verboden, ook als de tekst terloops vertelt wat ze doet                                                                                                                                             | "per-phase `httpx` timeout" → geen `httpx`                                                                                                             |
| R16  | Een ongeldige `drop` of `merge` wordt overgeslagen met een rapportregel en de run gaat door; een fout in de structuur is een fout bij het laden van het lockbestand; `drop` gaat voor `merge`                              | zie §20.4                                                                                                                                              |

### 20.1 Lockbestand

`Overrides` (`model.py:153-159`) krijgt twee velden, beide standaard leeg:

```python
drop: list[str] = Field(default_factory=list)        # element-ids
merge: dict[str, str] = Field(default_factory=dict)  # bron-id -> doel-id
```

Voorbeeld in de scope van `.chunkhound/map.lock.json`:

```json
"overrides": {
  "drop": ["external:httpx"],
  "merge": {"external:google": "external:gemini", "person:operators": "person:operator"}
}
```

- **Schema:** `map_lock.schema.json` wordt opnieuw gemaakt met `scripts/generate_c4_schemas.py`; `test_shipped_schema_matches_model` bewaakt dat.
- **Lockversie blijft 5.** Een bestaand lockbestand blijft geldig; niets hoeft te worden verwijderd of opnieuw geclassificeerd. Een oudere ChunkHound weigert een lockbestand met `drop` of `merge`, omdat het schema geen extra velden toestaat; dat is aanvaard, want het is een nieuwe functie.
- **Herspelen:** de invoervingerafdruk bevat `overrides.model_dump()` (`pipeline.py:576`). Door de twee nieuwe velden verandert die één keer en wordt de laatste overgang niet hergebruikt. Het ongeldig worden van de vingerafdruk zelf kost geen aanroep; alleen de geschiedenis van id-wijzigingen wordt opnieuw bepaald. Een latere wijziging van `drop` of `merge` maakt de vingerafdruk ook ongeldig, en kan daarnaast titels voor nieuwe relaties en nieuwe samenvattende labels vragen. Een volgende run met ongewijzigde invoer hergebruikt alles.
- **Bewaren:** `write_scope_lock` neemt `overrides` ongewijzigd over (`lockfile.py:58`); een run schrijft `drop` en `merge` nooit zelf.
- **Naast `classifications`:** die blijft de route om een kandidaat uit de code als `library` te classificeren. Voor een extern systeem uit de code werken beide; `drop` werkt op het element, `classifications` op de kandidaat.

### 20.2 Nabewerking

Nieuwe module `chunkhound/code_mapper/c4/curation.py` met één pure functie. Ze draait in de assemblage, na `documented_relations()` en vóór de overrides `names`, `descriptions` en `titles` (`assemble.py:450-459`), en dus vóór het ontdubbelen van citaten (`assemble.py:460`). Ze krijgt de elementen, relaties, citaten, referenties, bestanden per element, `inp.titles` en de overrides, en geeft hetzelfde terug plus de overgeslagen vermeldingen. De code die de kaart opbouwt, verandert niet. Het resultaat hangt niet af van de volgorde van de vermeldingen in het lockbestand.

1. **Toetsen (R16)** tegen de kaart zoals de assemblage die opleverde, in twee rondes.

   Eerst per vermelding. Overgeslagen, met een reden, als:
   - het id niet op de kaart staat;
   - het element geen extern systeem of persoon is;
   - bij `merge`: bron en doel van een andere soort zijn, of hetzelfde element;
   - bij `merge`: bron of doel ook in `drop` staat (`drop` gaat voor).

   Daarna, alleen tussen de `merge`-vermeldingen die de eerste ronde doorstaan: overgeslagen als het doel zelf de bron van zo'n vermelding is. Bij `a -> b` en `b -> c` wordt alleen `b -> c` uitgevoerd; bij een kring (`a -> b`, `b -> a`) geen van beide. Een vermelding die al in de eerste ronde afvalt, telt hier niet mee: bij `a -> b` en `b -> onbekend` wordt `a -> b` uitgevoerd.

   Dubbele id's in `drop` tellen één keer. De geldige vermeldingen worden tegelijk toegepast. Rapportregels staan gesorteerd: eerst `drop`, dan `merge`, elk op bron-id.

2. **`drop` (R13).**
   - Het element verdwijnt, en elke relatie die het raakt ook.
   - Citaten met het element of zo'n relatie als `target` verdwijnen, net als de sleutel van het element in de bestanden per element.
   - Een referentie blijft als feit in het bewijs, met ongewijzigd `to`; alleen `relation` wordt leeg als die relatie verdween. Zo staat nu ook een bibliotheek in het bewijs (`assemble.py:279-295`).
   - Een documentrelatie naar een weggehaald element verdwijnt met het element en telt niet als niet-gekoppeld. De tellingen van niet-gekoppelde documentrelaties uit de assemblage blijven ongewijzigd; de nabewerking voegt er niets aan toe.
3. **`merge` (R14).**
   - Relaties van de bron gaan naar het doel. Het id van een relatie wordt `<van>-><naar>` met het doel-id.
   - Citaten: `target` gelijk aan het bron-id wordt het doel-id; `target` gelijk aan een omgezette relatie wordt het nieuwe relatie-id.
   - Referenties: `to` blijft het oorspronkelijke pakket of bestand; alleen `relation` krijgt het nieuwe relatie-id. Zo rekent `_fingerprints` (`pipeline.py:440-451`) in beide `assemble()`-rondes van `_titles` met dezelfde gegevens.
   - Bestanden per element: die van de bron komen gesorteerd en zonder dubbelen bij het doel; de sleutel van de bron verdwijnt.
   - Een relatie die daardoor naar zichzelf wijst, vervalt; haar citaten verdwijnen en haar referenties krijgen een lege `relation`.
   - Relaties die daardoor hetzelfde id krijgen, vallen samen: status `found` als één ervan `found` was, `reference_counts` opgeteld, markeringen samengevoegd en gesorteerd.
   - Titel van de samengevoegde relatie: met codereferenties uit `titles` op de nieuwe vingerafdruk, anders `fallback_title`. Een relatie zonder codereferenties houdt de titel van de relatie die al dit id had, en anders die van de oorspronkelijke relatie met het kleinste id.
   - Het doel houdt zijn naam, omschrijving en id; de markeringen van de bron, zoals `fallback`, komen erbij.
   - Bron en doel mogen elk uit de code of uit de documentatie komen.
4. **Status opnieuw bepalen:** `found` met een citaat uit code of configuratie, anders `documented` (dezelfde regel als `statuses()`, `assemble.py:369-374`).

Het contract volgt daarna de bestaande regels: een extern systeem of persoon dat na `drop` of `merge` geen relatie met het systeem meer heeft, valt weg en wordt geteld (§17.2), en een samengevoegde relatie kan als dubbele directe relatie van de kaart gaan (`relations_off_the_map`, `model.py:188-222`).

**Titelstap.** `_pending_titles` werkt op het resultaat (`pipeline.py:462-497`). Een samengevoegde relatie met codereferenties krijgt een nieuwe vingerafdruk, haalt haar titel uit het lockbestand of vraagt er één keer om; de tweede `assemble()`-ronde in `_titles` (`pipeline.py:500-524`) vindt die titel via dezelfde vingerafdruk.

**Voorbeeld, run 4 met `merge: {"external:google": "external:gemini"}`:** `external:google` verdwijnt; `external:gemini` krijgt het codecitaat uit `gemini_llm_provider.py:20-21` en wordt `found`; `chunkhound -> google` (`found`) en `chunkhound -> gemini` (`documented`) worden één relatie `chunkhound -> gemini` met status `found`.

### 20.3 Prompt `c4_documented.md`

Direct na het verbod op regel 23-25 komt:

```text
An external element names one concrete system. Never make one of a category or
role without its own name, such as "an LLM provider", "embedding providers" or
"an operator-controlled HTTPS endpoint"; where the fragment names the concrete
systems, use those. A person may be a role. Never take a name that occurs only
inside an example command, example query or code sample. A library stays
excluded even when the text says what it does.
```

- De eerste twee zinnen zijn R15a, de zin over voorbeelden R15b, de laatste zin R15c. De tabelregel (regel 35-36) blijft: concrete providers uit een tabel blijven elk een element.
- `c4_classify.md` verandert niet; "A general HTTP client or parser that names no service stays library" (regel 11-12) dekt `httpx` als kandidaat uit de code al.
- **Versie:** de stapversie is een hash over instructies, schema en `_VALIDATOR_VERSION` (`documented.py:297-300`), dus de gewijzigde prompt geeft vanzelf een nieuwe versie. `_VALIDATOR_VERSION` blijft 3. Samen met de regel voor hele woorden (§19.3) roept de volgende run de documentstap één keer opnieuw aan, naar schatting 3 aanroepen; bundeling en fouten kunnen dat aantal veranderen.
- De tekst van de prompt krijgt geen test; de werking blijkt uit §20.6.

### 20.4 Rapport en fouten

- `assemble_with_unlinked` heet `assemble_with_notes` en geeft als vierde waarde `AssemblyNotes(unlinked: UnlinkedCounts, ignored_overrides: tuple[str, ...])`. De aanroep in `pipeline.py:844` en de tests volgen; er komt geen alias.
- Per overgeslagen vermelding één rapportregel in `report_extra`, direct na de regel over niet-gekoppelde documentrelaties (`pipeline.py:845-852`), in de vorm van de bestaande regel voor een onbekende groep (`pipeline.py:700-703`):

  ```text
  C4-overrides: drop ignored for external:foo (not on the map)
  C4-overrides: drop ignored for container:chunkhound (not an external system or person)
  C4-overrides: merge ignored for person:operator -> external:github (different kinds)
  C4-overrides: merge ignored for external:a -> external:b (target is merged itself)
  C4-overrides: merge ignored for external:google -> external:gemini (dropped)
  ```

  Een proefrun toont ze ook, want de nabewerking roept geen model aan.

- Een ongeldige vermelding breekt de run niet af (R16). Een fout in de structuur, zoals `drop` als tekst of een `merge`-waarde die geen tekst is, is een fout bij het laden van het lockbestand, zoals nu bij elk ongeldig lockbestand.
- Een naam, omschrijving of titel uit de overrides voor een id dat na de nabewerking niet meer bestaat, valt stil weg, zoals nu bij een onbekend id.
- Contract en AutoDoc veranderen niet: het contract volgt uit de elementen en relaties na de nabewerking.

### 20.5 Testen

Contracttests op de bestaande routes, via de publieke uitvoer (kaartmodel, bewijs, contract, rapport), niet via hulpfuncties:

1. `test_assemble.py`: na `drop` staat het element niet in elementen, relaties of citaten; een codereferentie ernaar blijft in het bewijs met haar oorspronkelijke `to` en zonder relatie.
2. `test_assemble.py`, voor een extern systeem uit de code met een doel uit de documentatie, voor een bron uit de documentatie met een doel uit de code, en voor twee personen uit de documentatie: het doel wordt `found` als bron of doel een codecitaat had en houdt zijn naam; relaties vallen samen met opgetelde `reference_counts` en samengevoegde markeringen; een relatie zonder codereferenties houdt de titel volgens §20.2; een relatie die naar zichzelf zou wijzen, vervalt; een `names`-override voor de bron heeft geen effect.
3. `test_assemble.py`: elk geval van R16 geeft de verwachte uitkomst en reden in `AssemblyNotes.ignored_overrides`: onbekend id, container, verschillende soorten, keten (alleen `b -> c`), kring, `a -> b` naast `b -> onbekend`, en `drop` vóór `merge`. Een andere volgorde van dezelfde vermeldingen geeft dezelfde uitvoer.
4. `test_pipeline.py`: een volledige run met de bestaande fixture. Het samengevoegde element staat niet in het contract; de omgezette relatie staat erin met haar bronnen; ze krijgt een titel uit de titelstap; een persoon die door `drop` zijn enige relatie verliest, staat niet in het contract en wel in `persons_without_relation`; een samengevoegde relatie die een bestaande directe relatie dubbelt, telt in `redundant_direct_relations`; de regel `C4-overrides: …` verschijnt; een tweede run met dezelfde invoer doet geen aanroep en hergebruikt de titel.
5. `test_pipeline.py`: een proefrun met dezelfde overrides toont de rapportregels, doet geen aanroep, schrijft geen contract en laat het lockbestand ongewijzigd.
6. `test_lockfile.py`: `drop` en `merge` overleven het opnieuw schrijven (uitbreiding van `test_override_section_is_never_rewritten`); `drop` als tekst en een `merge`-waarde die geen tekst is, geven elk een fout bij het laden.

### 20.6 Run en acceptatie

Run 5 vraagt aparte goedkeuring. Controles:

1. geen element voor een algemene categorie (`llm`, `llm-provider`, `embedding`, `embedding-provider(s)`), voor `stripe` of voor `operator-controlled-https-endpoint`; wel `duckduckgo` als de documenten die dienst noemen;
2. geen `httpx` uit de documentatie;
3. concrete providers uit de tabel staan er nog, met een relatie (§18.5, controle 3);
4. wat toch doorkomt, gaat als voorstel voor `drop`/`merge` in het lockbestand; na een tweede run klopt de kaart, zonder extra aanroep behalve voor titels en samenvattende labels die nog niet in het lockbestand staan;
5. `ModelLoader` en de LikeC4-build zonder waarschuwing.

**Onzeker:** R15 verkleint de ruis maar haalt die niet gegarandeerd weg; R13 en R14 vangen de rest op. Samenvoegen gebeurt niet automatisch: `ai-agent`/`ai-assistant` en `operator`/`operators` ruim je met `merge` op.

### 20.7 Bewust niet

- **Automatisch samenvoegen** via de classificatie: verandert het uitvoerformaat en de opgeslagen classificaties, en hangt weer van het model af.
- **Een lijst met namen** (§18.5): blijft uitgesloten.
- **`drop` of `merge` voor containers, opslag en componenten:** buiten deze stap. `overrides.placements` corrigeert alleen de plaatsing van groepen.
- **De weergave van ongeveer 20 providers** in het contextdiagram: een open punt voor AutoDoc/LikeC4, niet voor het model.
- **Zes externe systemen met dezelfde omschrijving, misleidende componentnamen, deel B en de volledige testsuite:** buiten deze stap.
