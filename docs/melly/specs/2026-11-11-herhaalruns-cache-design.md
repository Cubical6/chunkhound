# Spec: herhaalruns van `map` en `autodoc` versnellen (ontwikkelcache)

- Datum: 2026-11-11 · Branch: `main` (HEAD bij start `d34911a9`)
- **Status:** goedgekeurd 2026-11-11, inclusief de besluiten in §7. Fase 0 is gestart. Deze spec geeft geen toestemming voor een providerrun (fase 4) of een push.
- Bron: punt 4 in `.superpowers/design/omap-open-items-handoff.md`, met de sectie "Inventarisatie" (tijden uit Run 7 en Run 11, code gelezen op `d34911a9`).
- Besluit gebruiker (2026-11-11): de cache is **alleen voor ontwikkeling** (optie A). Hij mag bewust verouderd materiaal hergebruiken, mits dat zichtbaar wordt gemeld en de cache standaard uit staat.

## 1. Probleem

| Fase | Run 7 (volledig, 58 min) | Run 11 (`--minimal`, warme C4-cache, 16 min) | Cache nu |
|---|---|---|---|
| HyDE-planning (`code_mapper/hyde.py:82`) | 40 s | 17 s | geen |
| Topic-research (`code_mapper/service.py:479`) | 3306 s (96 %) | 878 s (94 %) | geen |
| C4-staart (na de topics) | 100 s | ~32 s | ja (DecisionStore, ExtractionStore, `map.lock.json`) |
| AutoDoc: cleanup, homepage, navigatie + woordenlijst | ~1 uur inclusief de sitebuild | niet gedraaid | geen |

Een herhaalrun doet dus vrijwel al het dure werk opnieuw. De C4-cache werkt wel, maar C4 is maar 3 % van de tijd.

## 2. Doel en afbakening

**Doel:** tijdens ontwikkeling van C4, prompts en AutoDoc moet een herhaalrun minuten kosten in plaats van uren. Alleen de stappen waarvan de invoer echt veranderde, draaien opnieuw.

**In scope:**
- modus "alleen C4" (§3);
- een cache voor AutoDoc (§4);
- een cache voor het topicplan en de topic-research (§5);
- een opslag voor al deze caches (§6);
- tests (§8) en een meetrun (§9).

**Buiten scope:**
- productie- of CI-garanties dat de uitkomst gelijk is aan een verse run;
- snelheidswinst zonder cache, zoals de staart in de topicplanning of de seriële reduce-call van ~300 s per topic (§10);
- de C4-caches zelf.

**Invarianten:**
- Zonder `--dev-cache` gedraagt alles zich exact als nu: er wordt geen cachebestand gelezen of geschreven.
- Elk hergebruik verschijnt in het rapport, met per stap het aantal hergebruikte en het aantal nieuwe items.
- Een cache-item wordt alleen gebruikt als alle sleuteldelen exact overeenkomen; het `DecisionStore`-patroon controleert ze bij het lezen opnieuw.
- Elke provider, elk model of reasoning effort, en elke prompt- of schemaversie zit in de sleutel. Zo'n wijziging geeft dus altijd een miss.

## 3. Modus "alleen C4": `chunkhound map --c4-only`

**Waarom:** veel diagnoseruns controleren alleen systemen, personen en relaties. Run 10 en Run 11 duurden toch 16 minuten, omdat ze HyDE en één topic deden.

**Wat:**
- Er draaien geen HyDE en geen topic-research.
- `c4.analyze()` loopt zoals nu. Daarna volgt `finish_c4(draft, topics=None, …)`.
- In de code is gecontroleerd dat `finish_c4` `topics=None` aankan; de proefrun (`--plan`) doet dat al.
  - De topics bepalen alleen de volgorde van de documentextractie: `order_hint` (`c4/pipeline.py:762-774`, "Research only orders the calls; it never limits coverage").
  - Ze bepalen ook de dekking per element (`compute_coverage`, `:817`) en de topics in het contract (`build_contract`, `:885`).

**Gevolgen voor de uitvoer:**
- Elementen krijgen geen topicdekking.
- Het contract bevat geen topics.
- Het rapport vermeldt `c4-only: topics skipped`.
- Er worden geen nieuwe topicbestanden en geen index gemaakt. Bestaande topicbestanden in de uitvoermap blijven onaangeroerd; de modus ruimt niets op.

**Combinaties:**
- Samen met `--no-c4` is het een fout.
- Samen met `--plan` is het een fout, want `--plan` doet al een C4-proef zonder LLM.

**Verwachte duur met een warme besliscache:** ongeveer 1 à 2 minuten (opstart ~10 s plus de C4-staart 30-100 s). Dit is een schatting.

Deze modus staat los van `--dev-cache` en is het goedkoopst te bouwen.

## 4. AutoDoc-cache

**Stappen** (inventarisatie, `autodoc/cleanup.py:72`, `autodoc/ia.py:157` en `:233`):
- cleanup per topic, in batches via `batch_complete`;
- homepage-overzicht, één call;
- navigatie en woordenlijst, één `complete_structured`-call.

Elke stap is een zuivere functie van zijn prompttekst en de provider. Hergebruik is daarom alleen onjuist als de provider zelf willekeurig antwoordt; dat is acceptabel binnen optie A.

**Sleutel per item** (`DecisionStore`-vorm):

| Stap | `question` | `item` |
|---|---|---|
| cleanup | `autodoc_cleanup` | sha256 van de volledige gerenderde gebruikersprompt (titel, topictekst, audience) |
| homepage | `autodoc_homepage` | sha256 van de gerenderde prompt (koppen en snippets van de opgeschoonde pagina's) |
| navigatie en woordenlijst | `autodoc_site_ia` | sha256 van de gerenderde sitecontext plus het schema |

Voor alle drie geldt:
- `question_version` is de sha256 van de systeemprompt, het promptsjabloon, het eventuele schema en `max_completion_tokens`.
- `provider` is de `ProviderIdentity` van de synthesisprovider.

**Gedrag:**
- Een cleanup-batch stuurt alleen de misses naar de provider. De hits worden direct ingevoegd.
- Homepage en navigatie raken vanzelf als alle cleanup-uitkomsten gelijk zijn, omdat hun prompt uit die uitkomsten bestaat.

**Verwachting:** `autodoc --map-in <ongewijzigde kaart> --dev-cache` doet geen LLM-calls meer. Wat overblijft is de sitebuild, waarvan de duur nog niet apart is gemeten.

## 5. Cache voor het topicplan en de topic-research

### 5.1 Waarom eerst het plan

De lijst topics (PoI's) komt uit de HyDE-call en verschilt per run. De HyDE-prompt bevat bovendien codesnippets, dus elke codewijziging geeft een andere prompt en daarmee een nieuwe topiclijst. Een topic-cache raakt daarom alleen als het plan vastligt.

### 5.2 Plan vastzetten

Met `--dev-cache` wordt het HyDE-plan bewaard en hergebruikt. De sleutel bevat:
- de scope;
- `comprehensiveness` en `max_points`;
- het ops-budget;
- de audience en het `--context`-bestand (de hash van de inhoud);
- de hash van het HyDE-promptsjabloon;
- de provideridentiteit.

De sleutel bevat **niet** de codesnippets en de bestandsindeling. Het plan blijft dus geldig na codewijzigingen; dat is bewust verouderd materiaal, toegestaan door optie A. Het rapport meldt: `plan reused (from <datum>)`.

Met `--refresh-plan` wordt het plan geforceerd opnieuw gemaakt. Topics met een nieuwe PoI-tekst missen dan. Een topic waarvan de PoI-tekst exact gelijk blijft, raakt wel; dat is correct, want de onderzoeksvraag is dezelfde. Een generatienummer in de topic-sleutel is daarom niet nodig.

### 5.3 Topic-research

De sleutel bevat:
- de exacte `section_query`: de PoI-tekst plus de audience- en scopetekst;
- `path_filter`;
- de researchconfiguratie;
- de identiteit van de utility- en de synthesisprovider;
- een broncodemanifest als `question_version`: de sha256 over de gesorteerde relatieve paden plus de sha256 van elk bestand in `services/research/**/*.py`, `services/prompts/**/*.py` en `services/deep_research_service.py`, plus een expliciete formaatversie (fase 0, Q2).
  - Constanten alleen zijn onvoldoende, want prompts en schema's staan ook inline en in builders.
  - Een wijziging in de researchcode maakt alle topics dus ongeldig. Dat is bewust conservatief.
  - Is de broncode niet leesbaar, dan geldt de cache als uit ("fail closed").

**Geldigheid op bewijsniveau** (besloten, §7):
- Het cache-item bewaart de bewijsbestanden van het topic: de `TopicSources.files` die `_topic_sources` nu al afleidt, met hun `content_hash` uit de index.
- Bij het lezen is het item alleen geldig als al die bestanden nog bestaan en dezelfde `content_hash` hebben.
- Een topic waarvan een bewijsbestand veranderde, wordt opnieuw onderzocht.
- Een topic dat alleen door ongerelateerde wijzigingen "veroudert", wordt hergebruikt. De research kan in dat geval nieuwe relevante bestanden missen; het rapport noemt dat bewust hergebruik.

Opgeslagen wordt:
- de uitkomst van `run_deep_research` voor dit topic: de Markdown en de bronnen die `CodeMapperPipelineResult` nodig heeft;
- de bewijsbestanden met hun hashes.

Niet opgeslagen worden de tussenstappen van de research.

**Verwachting bij een herhaalrun zonder codewijziging:** de kaart duurt ongeveer 2-3 minuten in plaats van 58. Na een wijziging schaalt de duur met het aantal topics waarvan bewijs veranderde. Dit is een schatting.

## 6. Opslag

Hergebruik van `DecisionStore` (`services/extraction/store.py:140`) met nieuwe vraagsoorten heeft de voorkeur boven een nieuwe klasse. Die winkel levert al:
- een sleutel uit de sha256 van canonieke JSON;
- een herhaalde controle van `key_parts` bij het lezen;
- atomaire, duurzame schrijfacties;
- opruimen op leeftijd;
- `read_only` voor proefruns.

Het pad wordt `.chunkhound/extraction/decisions/<question>/<key>.json`, met als vragen `hyde_plan`, `topic_research`, `autodoc_cleanup`, `autodoc_homepage` en `autodoc_site_ia`.

`DecisionStore` wordt direct gebruikt (fase 0, Q4). Hij accepteert willekeurige vraagnamen en JSON-antwoorden zonder groottelimiet, en is niet gekoppeld aan C4-typen. Een topicresultaat is 40-80 kB Markdown plus herkomst.

De store heeft zelf geen hervalidatiehaak. Die zit in de C4-runner (`_DecisionRun.cached`), en die is aan C4-typen gekoppeld. Daarom komt er een dunne toepassingslaag boven de store:
- die controleert de vorm en de bewijshashes;
- een afgewezen item telt als miss en leidt tot een nieuwe call;
- alleen geaccepteerde items worden ge-`touch`t.

De antwoordenvelop bevat het aanmaakmoment (voor `plan reused (from <datum>)`) en de bewijshashes.

**Vlag:** `--dev-cache` op `map` en `autodoc`. Ook bij `autodoc` zonder `--map-in` gaat de vlag door naar de interne kaartrun. Standaard staat de vlag uit. Er komt geen configuratie- of omgevingsvariant, zodat hij niet ongemerkt in CI aan staat.

## 7. Ter beslissing

1. **Geldigheid van een topic** (§5.3). **Besloten (2026-11-11): geldig op bewijsniveau.** Een topic wordt alleen opnieuw onderzocht als een van zijn bewijsbestanden veranderde. Verworpen: een vingerafdruk van alle bestanden in de scope. Die is strenger, maar bij `map .` op chunkhound zelf verandert hij bij elke commit, waardoor de cache bijna nooit raakt.
2. **Plan vastzetten** (§5.2). **Besloten (2026-11-11): ja.** Met `--dev-cache` wordt het plan automatisch hergebruikt, ook na codewijzigingen; `--refresh-plan` ververst het. Verworpen: het plan alleen hergebruiken als de HyDE-prompt identiek is. Dat raakt na elke codewijziging niet, en dan raken de topics ook niet.
3. **Namen van de vlaggen.** **Besloten (2026-11-11):** `--c4-only`, `--dev-cache` en `--refresh-plan`.

## 8. Testen

Contracttests met een nep-LLM-provider op de echte pipeline, volgens de testfilosofie in `AGENTS.md`:

- `test_map_c4_only_makes_no_research_calls`: `--c4-only` levert een C4-model en doet nul research- en HyDE-calls.
- `test_dev_cache_off_writes_nothing`: zonder vlag komt er geen bestand onder `decisions/` voor de nieuwe vragen.
- `test_dev_cache_second_run_makes_no_llm_calls`: een herhaalrun met dezelfde invoer doet nul calls in `map` en in `autodoc --map-in`.
- `test_changed_evidence_file_reresearches_only_that_topic`: na een wijziging in het bewijsbestand van één topic draait alleen dat topic opnieuw.
- `test_prompt_or_provider_change_misses`: een andere modelnaam of promptversie geeft een miss.

## 9. Fasering (uitvoering via pi-bolt, één sessie per fase)

| Fase | Inhoud | Model |
|---|---|---|
| 0 | Onderzoek zonder provider, alleen een kort rapport en geen code. Vragen: is het HyDE-plan via een bestand te injecteren, welke researchprompts horen in de versiehash, past een topicresultaat in `DecisionStore`, en waar komt de `content_hash` per bestand vandaan. | sol/medium |
| 1 | `--c4-only` met test | sol/medium |
| 2 | AutoDoc-cache met tests | sol/medium |
| 3 | Plan vastzetten en topic-cache met tests | sol/high |
| 4 | Meetrun: Run 12, twee keer `map` plus `autodoc` met `--dev-cache` op een worktree, en daarna één `--c4-only`. **Alleen na toestemming.** | n.v.t. |

Na elke fase volgen een diff-review, de smoke-tests en een commit, maar alleen als de gebruiker daarom vraagt. Fase 1 en 2 zijn onafhankelijk en kunnen parallel in aparte worktrees.

## 10. Uitkomst fase 0 (2026-11-11, alleen lezen, pi-bolt sessie `01a1cc4c`)

Correcties zijn verwerkt in §3, §5 en §6. Aanvullende eisen voor de implementatie:

**HyDE (§5.2):**
- Cache beide ruwe antwoorden (arch en ops) direct na de calls (`code_mapper/pipeline.py:375`). Bij een hit worden ze vóór het parsen (`:397`) ingevoegd, zodat het parsen en de artefacten ongewijzigd blijven.
- Doe de lookup vóór de scope-sampling (`:234`).
- De sleutel bevat ook de inline-objective (`:281-330`) en de repository-identiteit van de scope.
- De audience zit nu niet in de HyDE-signatuur en moet vanuit `service.py:243` worden doorgegeven.
- De bestandsvolgorde van de layout is niet deterministisch (`utils/file_patterns.py`). Dat is één reden te meer om de layout buiten de sleutel te houden.

**Topic (§5.3):**
- De lookup gebeurt in `_run_point_once` (`code_mapper/service.py:430-479`), na `section_query` en vóór de research.
- Alleen het resultaatwoordenboek per topic wordt gecachet (`{"answer", "metadata"}`), niet `CodeMapperPipelineResult`; dat is niet JSON-serialiseerbaar.
- Workers, nummering, retries en de weergave van fouten blijven ongewijzigd.

**Bewijs (§5.3):**
- De paden in `metadata.sources.files` zijn relatief aan de indexbasis, maar kunnen soms absoluut zijn; normaliseer ze daarom.
- Lees de hash via `get_file_by_path` (XXH3-64) en bewaar per run per pad.
- Een ontbrekend bestand of een lege of ontbrekende hash geeft een miss. `None == None` telt niet als gelijk.
- De hash in de DB weerspiegelt de laatste indexering. De cache werkt dus pas correct na `chunkhound index`; het rapport vermeldt dat.

**AutoDoc (§4):**
- Bij een hit wordt `cleaned[idx]` direct gevuld. Alleen de misses gaan als batch naar de provider (`autodoc/cleanup.py:80-108`). Succesvolle uitkomsten, ook die van de fallback per topic, worden meteen opgeslagen.
- `_batch_complete_with_backoff` blijft ongewijzigd.
- Na een cache-hit draait de bestaande validatie van navigatie en woordenlijst opnieuw (`autodoc/ia.py:185-199`).
- Een homepage wordt alleen opgeslagen als de uitkomst niet leeg is.
- De provideridentiteit is die van de rol `autodoc_cleanup`.
- `--dev-cache` gaat expliciet via `autodoc_autorun.py:312-348` naar de `Namespace` van de interne kaartrun.

**`--c4-only` (§3):**
- De vertakking komt in `_run_requested_outputs` (`api/cli/commands/code_mapper.py:328-344`), vóór de keuze tussen trial en full.
- Daar wordt de echte LLM-manager gemaakt en wordt `c4.llm` vervangen door `C4Llm(..., trial=False)`; anders blijft `kind` op `"trial"` staan. Daarna volgt `finish(analyze(), None)`.
- Dit slaat de setup van de DB en de embeddings over. Contract, `map.lock.json` en `c4.write` werken zonder topics.

## 11. Bewust niet

- **Productie- of CI-cache met een garantie op versheid.** Optie A is gekozen.
- **Caching binnen de research**, zoals per zoekvraag of per cluster. Dat is complexer en levert weinig op naast caching per topic.
- **Snelheidswinst zonder cache.** De staart van ~455 s waarin in Run 7 maar één topic liep, en de seriële reduce-call per topic, verdienen een apart onderzoek.
- **Een TTL bij het lezen.** Ongeldig maken gebeurt alleen doordat de sleutel of het bewijs verandert; opruimen gebeurt op leeftijd, zoals nu.
