# Spec: gedeelde extractielaag voor C4-documentatie en research

- Datum: 2026-11-01 · Werkruimte: hoofdcheckout `main` (HEAD bij start `ec788c01`)
- **Status:** concept, herzien na onafhankelijke specreview (2026-11-01); geen implementatie, implementatieplan of provider-/maprun goedgekeurd
- Besluitenlog: [2026-10-27-map-structuuranalyse.md](../decisions/2026-10-27-map-structuuranalyse.md), rij 71–85 ("rij N" hieronder)
- Bouwt voort op de opgeleverde spec [2026-10-27-map-structuuranalyse-design.md](2026-10-27-map-structuuranalyse-design.md) en het model [map-structuuranalyse.md](../models/map-structuuranalyse.md); die blijven gelden waar §1.1 niets vervangt
- Aanleiding: twee volledige `chunkhound map`-runs faalden bij C4 `extract_documented`. Een vergrote reproductie (bronset van 941.516 bytes) gaf Codex `input_too_large` (1.100.748 tekens in de aanvraag, tegen een grens van 1.048.576). De exacte payload van de oorspronkelijke runs is niet teruggevonden.

## 1. Doel en afbakening

Een gedeelde laag die bronversies, fragmenten, begrensde aanvraagopbouw, persistente resultaten en dekkingsadministratie levert, zonder domeinbetekenis (rij 74, 76). C4-documentatie-extractie is de eerste afnemer; research volgt ná de C4-aansluiting (rij 81 noemt dit de tweede fase; §11 nummert laag, C4 en research als fase 1–3).

**In scope**

- De gedeelde laag, met fouten ingedeeld aan de aanroepgrens.
- C4: `extract_documented` op de laag, terugval per fragment, rapportage.
- Research, fase 2: feitextractie via de laag, zonder persistente opslag.

**Buiten scope**

- Bronselectie: `doc_files_for` en de researchselectie blijven ongewijzigd (rij 71).
- HyDE en topics; hervatten van topicresearch (rij 73).
- Uitwisseling van resultaten tussen research en C4 (rij 76).
- Een andere koppeling van relatietermen (rij 83).
- Begrenzing van andere C4-stappen dan `documented`.
- Kalibratie van startwaarden met echte providerruns.
- In fase 1: wijzigingen aan providers.

**Invarianten**

1. Volledige extractiedekking binnen de geselecteerde bronset; research prioriteert alleen (rij 71, 72).
2. Een researchfeit is nooit C4-dekking of C4-bewijs (rij 72, 76).
3. Een geldig leeg resultaat telt als onderzocht; een mislukte extractie of terugval niet (rij 72).
4. Elke uitkomst doorloopt dezelfde controle door de toepassing tegen de huidige bron, of ze nu uit de cache komt of nieuw is. Verwijderen van de cache verandert alleen kosten en de herkomst van uitkomsten, nooit welke controle geldt (rij 80).
5. Geen aanvraag **via de laag** wordt verzonden boven de effectieve invoerlimiet; de laag kort nooit stilzwijgend in (rij 78).
6. Een onvolledige run publiceert geen nieuw model en werkt het lockbestand niet voortijdig bij (rij 73). Bij een terugval, ook voor één fragment zonder lock-items, slaat het lockbestand geen documentatie op en wordt geen overgang vastgelegd (rij 82).
7. Fase 1 verandert research en het foutgedrag van providers niet; met `--no-c4` blijft de uitvoer byte-gelijk.

### 1.1 Vervangen kaders

Voor de stap `documented` vervangt deze spec twee punten uit de vorige spec, §8:

- "1 aanroep per run" wordt vervangen door bundels (rij 77).
- "niet-tijdelijk → niets geschreven" wordt vervangen door de persistente bundelopslag (rij 73, 80).

De publicatie- en lockvoorwaarden uit de vorige spec blijven ongewijzigd.

## 2. Begrippen

| Begrip | Betekenis | Bron |
|---|---|---|
| Bronversie | projectrelatief POSIX-pad + sha256 van de bytes, één keer per run gelezen. Decodering is een keuze van de toepassing: C4 strikt UTF-8 (fout → expliciete fout); research zoals nu, met `errors="ignore"`. Regels worden gesplitst met `str.splitlines()`, net als `verify_quote`. | rij 72 |
| Fragment | aaneengesloten regelbereik van één bronversie, met oorspronkelijke regelnummers; eenheid van dekking en citaten | rij 72, 77 |
| Fragmentcontext | documentpad + keten van bovenliggende kopjes; alleen leesinformatie | rij 79 |
| Fragmentidentiteit | pad, sha256 van de fragmenttekst, fragmentatieversie en sha256 van de context; **geen** regelnummers | rij 77, 79 |
| Bundel | geordende reeks fragmenten in één aanroep; eenheid van aanroep en hergebruik | rij 77 |
| Extractiedoel | instructies, antwoordschema per fragment, validator, regelnotatie en uitvoerbeleid van een toepassing | rij 76 |
| Extractiedekking | per doel en bronversie: welke fragmenten een geldige uitkomst hebben | rij 72 |

## 3. Architectuur

```text
toepassing (C4 / research)            gedeelde laag (chunkhound/services/extraction/)
─────────────────────────            ───────────────────────────────────────────────
bronselectie + decodering ──────────► bronversies
fragmentbepaling ───────────────────► fragmenten (kopjes | aangeleverde bereiken)
extractiedoel ──────────────────────► cache opzoeken → goal.recheck
volgordehints | eigen bundels ──────► bundels (inpakken | aangeleverd) → budget meten
                                       aanroep → foutindeling → per fragment goal.validate
                                       halveren bij onleesbaar antwoord
                                       geldige bundel atomair opslaan
◄──── uitkomst per fragment (geldig | mislukt + soort) + rapporttellingen
samenvoegen, terugval, lock, publicatie (blijft bij toepassing)
```

Modulevoorstel (namen definitief in het plan): `sources.py`, `fragments.py`, `bundles.py`, `budget.py`, `errors.py`, `store.py`, `runner.py` onder `chunkhound/services/extraction/`. De laag importeert niets uit `code_mapper` of `services/research`.

**Interfaces (schets)**

```python
@dataclass(frozen=True)
class SourceVersion:
    path: str            # projectrelatief, POSIX
    sha256: str          # over de bytes
    lines: tuple[str, ...]

@dataclass(frozen=True)
class Fragment:
    source: SourceVersion
    start_line: int      # oorspronkelijk, 1-gebaseerd, inclusief
    end_line: int
    heading_path: tuple[str, ...]
    def identity(self) -> FragmentIdentity: ...   # zonder regelnummers

class ExtractionGoal(Protocol[PartT]):
    name: str
    version: str                          # sha256(prompttekst, schema, validatorversie)
    line_numbering: Literal["relative", "absolute"]
    def instructions(self) -> str: ...
    def part_model(self) -> type[BaseModel]: ...   # schema van één fragmentdeel
    def max_completion_tokens(self, bundle_chars: int) -> int: ...
    def validate(self, fragment: Fragment, part: PartT) -> PartT | Rejected: ...
    def recheck(self, fragment: Fragment, stored: PartT) -> PartT | Rejected: ...

@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    model: str
    reasoning_effort: str | None     # via LLMConfig-rolresolutie (llm_config.py:740–785)
    base_url: str | None

@dataclass(frozen=True)
class InputLimit:
    max_chars: int
    max_tokens: int | None

async def run_extraction(
    goal: ExtractionGoal[PartT],
    fragments: Sequence[Fragment],
    *,
    call: StructuredCall,                  # adapter met foutindeling (§6.4)
    provider: ProviderIdentity,
    limit: InputLimit,
    store: ExtractionStore | None,         # None = alleen geheugen (research)
    bundles: Sequence[Sequence[Fragment]] | None = None,  # aangeleverd (research)
    order_hint: Callable[[Fragment], float] | None = None,
) -> ExtractionResult[PartT]: ...
```

`ExtractionResult` bevat per fragment `Valid(part, from_cache)` of `Failed(kind)`, met `kind ∈ {transient, rejected}`. Daarnaast de tellingen: bundels hergebruikt, nieuw en gesplitst. Fatale fouten worden doorgegeven en niet gevangen: invoer geweigerd, configuratie, onleesbare bron of een programmeerfout zoals overlappende bereiken.

## 4. Fragmentering

**Gemeenschappelijk**

- De grootte van een fragment wordt gemeten in de **weergegeven vorm**: kopregel met contextpad, plus regels met het voorvoegsel `N| `.
- Maximale fragmentgrootte = effectieve doelgrootte ÷ 4 (§6.1). Er blijft dus altijd ruimte om te halveren.

**Op kopjes** (C4; bestanden die volgens `detect_language` Markdown zijn; rij 77)

1. **Blokherkenning**, buiten fenced codeblokken:
   - YAML-front matter: `---` op regel 1 tot de volgende `---` of `...`. Dit is een eigen blok.
   - Fenced codeblokken: ```` ``` ```` of `~~~`, minimaal 3 tekens. Het blok sluit met hetzelfde teken in minstens dezelfde lengte. Een niet-afgesloten blok loopt door tot het einde van het document.
   - ATX-kopjes: `^ {0,3}#{1,6}(\s|$)`.
   - Setext-kopjes en ingesprongen code zijn **geen** grenzen.
2. **Recursieve indeling.** Een knoop is het hele document of een kopje met zijn hele subboom.
   - Past een knoop in de weergegeven vorm, dan is hij één fragment.
   - Anders worden zijn delen apart behandeld: de introtekst vóór het eerste subkopje, en elk subkopje recursief.
3. **Te grote introtekst of bladsectie.** Splits in alinea's: reeksen regels gescheiden door lege regels, buiten codeblokken. Opeenvolgende alinea's worden gulzig samengevoegd tot de maximale grootte. Is één alinea te groot, dan worden regels gulzig samengevoegd. Is één regel te groot, dan volgt een fatale fout met pad en regelnummer.
4. Elke regel valt in precies één fragment.

**Andere geselecteerde bestanden** (bijvoorbeeld `README.rst` of `README.txt` via `documented.py:105`): dezelfde regels, maar zonder kopjesherkenning, dus alleen stap 3. De context is alleen het documentpad.

**Gevolg.** Een wijziging maakt het kleinste blok dat haar bevat en nog als één fragment past opnieuw nodig. In een document onder de maximale fragmentgrootte is dat het hele document. Binnen een gesplitste sectie kan een wijziging de grenzen van de volgende alineafragmenten in **dezelfde** sectie verschuiven. Daarbuiten kan dat in één zeldzaam geval: de maximale grootte rekent met de breedste regelnummernotatie van het document. Gaat het document door een ingevoegde regel van bijvoorbeeld 99 naar 100 regels, dan kan een sectie die precies op de grens zit een extra fragment worden. Dat kost alleen een extra aanroep; de uitkomst blijft geldig.

**Aangeleverde bereiken** (research): de toepassing levert per bronversie regelbereiken die elkaar niet overlappen. Overlap is een programmeerfout van de toepassing; research voegt overlappende bereiken eerst samen (§9). Een te groot bereik wordt gesplitst volgens stap 3. Er is geen dekkingseis.

**Fragmentatieversie.** Een constante die bij elke wijziging aan deze regels wordt opgehoogd.

## 5. Bundels en hergebruik (rij 77)

1. **Eerst hergebruiken.** Zoek opgeslagen bundels met hetzelfde doel, dezelfde doelversie en dezelfde provideridentiteit, waarvan alle leden als **multiset** van fragmentidentiteiten in de huidige set voorkomen. Zo tellen twee identieke fragmenten met dezelfde kopjesketen elk apart. Vertaal de opgeslagen delen naar de huidige oorspronkelijke regels en roep `goal.recheck` aan.
   - Wat slaagt, is gedekt; wat faalt, gaat terug naar de pool.
   - Bij overlappende treffers kiest de laag deterministisch eerst de bundel met de meeste nog niet gedekte leden, daarna de laagste sleutel. Leden die al gedekt zijn, worden uit een volgende treffer overgeslagen.
2. **Dan inpakken.** De overige fragmenten gaan in padvolgorde, binnen een document in regelvolgorde, gulzig tot de effectieve doelgrootte. Researchhints bepalen alleen de volgorde van aanroepen. Levert de toepassing zelf bundels aan (research), dan meet de laag die en halveert ze vóór verzending als ze te groot zijn. Er wordt niets ingekort.
3. **Regelnotatie** is een eigenschap van het doel:
   - C4 gebruikt `relative`: regelnummers die per fragment bij 1 beginnen. Een ingevoegde regel elders verandert de invoer dan niet.
   - Research gebruikt `absolute`: de echte regelnummers, want research heeft geen cache (rij 81).

   ```text
   === F3 · docs/architecture.md › Containers › Indexeerservice
   1| De indexeerservice schrijft naar DuckDB.
   ```

   Fragment-id's (`F1`…) gelden alleen binnen de bundel.
4. **Antwoordschema:** `{"fragments": [{"id": str, "part": <part_model>}]}`.
   - Een ontbrekend, dubbel of onbekend id, of een `part` dat de validatie niet doorstaat, maakt **alleen dat fragment** ongeldig.
   - Een antwoord dat niet aan het schema voldoet, wordt door de provider als geheel verworpen. Dat geldt als onleesbaar antwoord en leidt tot halveren (§6.3). Fouten in de vorm van één deel kosten dus een halvering, maar nooit stilzwijgend dekking.
5. **Gedeeltelijk geldig.** Geldige delen worden bewaard en opgeslagen. Ongeldige fragmenten worden `Failed(rejected)` en krijgen, gescheiden van de geldige, alleen de uitgestelde herstelpoging uit §8.5. Zo blijft gelden: "afzonderlijk opnieuw" (rij 77) en één uitgestelde herstelpoging.

## 6. Budget en vangnet (rij 78, 84)

### 6.1 Limiet en doelgrootte

- **Waar de limiet staat** (voorstel; rij 78 laat dit open): ingebouwde bekende waarden per providersoort, met optionele configuratievelden per rol (namen in het plan) die ze overschrijven.
- **Effectieve doelgrootte** = min(doelgrootte, `max_chars` − vaste marge). Bij een tokenlimiet geldt bovendien `estimate_tokens(aanvraag) × 1,2 ≤ max_tokens`.
- Een lagere limiet geeft kleinere bundels en fragmenten. Dat kan hergebruik verminderen, maar maakt geen uitkomst ongeldig.

| Startwaarde (rij 84, te kalibreren) | Waarde |
|---|---|
| Codex CLI `max_chars` | 1.048.576 (uit de foutmelding) |
| Standaard zonder opgave `max_chars` | 400.000 |
| Doelgrootte per bundel (hele aanvraag) | 150.000 tekens |
| Maximale fragmentgrootte | effectieve doelgrootte ÷ 4 |
| Uitvoerlimiet C4 `documented` | max(2.048, min(16.384, ⌈bundeltekens ÷ 10⌉)) tokens |
| Veiligheidsmarge op `estimate_tokens` | 20 % |

De uitvoerlimiet schaalt met de omvang van de bundel, met een bovengrens. Dat volgt rij 78. De verhouding 1 token per 10 invoertekens en de ondergrens zijn nieuwe voorstellen.

### 6.2 Meten vooraf

De gemeten grootte is een bovengrens. Ze telt op:

- de instructies;
- het schema zoals CLI-providers het in de prompt opnemen (`json.dumps(schema, indent=2)`, `base_cli_provider.py:420–431`);
- de fragmentnotatie;
- een vaste marge voor de provideromhulling.

Een bundel boven de effectieve doelgrootte wordt niet verzonden.

### 6.3 Halveren

Is het antwoord onleesbaar (§6.4) en bevat de bundel meer dan één fragment, dan wordt de bundel gehalveerd. Beide helften worden opnieuw geprobeerd, desnoods tot er één fragment over is. Bij één fragment wordt het `Failed(rejected)`.

Halveren binnen de uitgestelde herstelpoging hoort bij die ene poging; er komen geen extra herstelrondes bij. Elke splitsing wordt geteld.

### 6.4 Foutindeling aan de aanroepgrens

`StructuredCall` is een adapter rond `C4Llm.call` of rond de researchprovider. De adapter onderzoekt de hele exception-keten en deelt fouten in, in deze volgorde:

1. **Onleesbaar of afgekapt → halveren.** Dit komt eerst, omdat parse- en schemafouten modeluitvoer citeren. Daarin kan de marker van punt 2 voorkomen zonder dat de provider iets geweigerd heeft (herziening na de codereview van 2026-11-03). Herkend aan:
   - `json.JSONDecodeError` of `"Invalid JSON in structured output"` (`base_cli_provider.py:451–454`);
   - `"Structured output truncated"` (`anthropic_llm_provider.py:942–945`);
   - `"LLM response truncated"`, `"Gemini response truncated"`, `"structured completion truncated"` van Gemini en OpenAI-compatibele providers, en `"incomplete - token limit"` van de OpenAI Responses API;
   - een pydantic- of schema-validatiefout in de keten, ook als die verpakt is in `"LLM structured completion failed"` (`base_cli_provider.py:462–465`).
2. **Invoer geweigerd → fatale configuratiefout**, met de gemeten grootte en de opgegeven grens. Herkend aan bekende markers, voor Codex `input_too_large`.
3. **Tijdelijk** volgens `_is_retryable_poi_error` (`service.py:95–119`) → `Failed(transient)`.
4. **Overige fouten → fataal**, net als nu (`llm.py:141–143`).

Fase 1 verandert geen providers en geen `_is_retryable_poi_error`. Daarmee blijft het foutgedrag van research en van de andere C4-stappen ongewijzigd (invariant 7). `C4Llm.call` krijgt alleen een optionele parameter `max_completion_tokens`, die wordt doorgegeven aan `complete_structured_typed`. Nu geldt de standaardwaarde 4096 (`llm_provider.py:293–299`).

## 7. Opslag (rij 80)

- **Locatie:** `<target_dir>/.chunkhound/extraction/<doel>/<sleutel>.json`, los van `map.lock.json` en van de database.
- **Sleutel:** sha256 van canonieke JSON (gesorteerde sleutels, UTF-8, geen witruimte) over:
  - `formaat`, `notatieversie`;
  - `doel`, `doelversie`;
  - `provider`, `model`, `reasoning_effort`, `base_url`, `max_completion_tokens`;
  - `fragmentatieversie`;
  - `leden: [{pad, tekst_sha256, context_sha256}]` in bundelvolgorde.
- **Waarde:** de sleutelonderdelen, de formaatversie, en per lid het gevalideerde deel met regelnummers volgens de notatie. Alleen geldige leden worden opgeslagen.
- **Schrijven:** direct na validatie van een bundel. Eerst naar `.<sleutel>.<willekeurig>.tmp` in dezelfde map, dan fsync, dan `os.replace`. Er is geen gedeelde index. Gelijktijdige runs mogen naar dezelfde sleutel schrijven; de laatste schrijver wint, en beide versies zijn geldig.
- **Bij een fatale fout** worden lopende aanroepen afgebroken. Wat vóór dat moment gevalideerd is, blijft opgeslagen; wat nog liep, niet.
- **Lezen:** alleen `*.json` in `<doel>/`. Een onleesbaar bestand, een onbekende formaatversie of afwijkende sleutelonderdelen telt als cachemiss. Dat wordt gelogd, maar is niet fataal. Tijdelijke bestanden worden genegeerd.
- **Opruimen:** alleen aan het eind van een run die niet fataal faalde en geen proefrun is. Bij hergebruik wordt de wijzigingstijd bijgewerkt. Verwijderd worden `*.json` die langer dan 30 dagen ongebruikt zijn (rij 84), en `*.tmp` ouder dan 1 dag. Dit staat los van de scope.
- **Proefmodus** doet geen aanroepen en schrijft niets, ook geen bijgewerkte wijzigingstijd.

## 8. C4-aansluiting (rij 82, 83)

Doorstroom in `extract_documented`:

1. `doc_files_for` blijft ongewijzigd.
2. **Snelle route.** Is de hele set gelijk aan `locked.hashes`, dan wordt de vorige uitkomst gebruikt, zoals nu. Proefmodus blijft zoals nu (`documented.py:228–233`).
3. Fragmenten worden bepaald (§4), daarna volgt `run_extraction` met het doel `documented` (regelnotatie `relative`).
4. **Validator** = de huidige regels van `check_documented_answer`, per fragment:
   - het citaat moet letterlijk binnen de eigen fragmentregels staan;
   - een elementterm moet letterlijk in de geciteerde regels staan;
   - het veld `file` vervalt in het antwoord, want de laag vult het pad in;
   - zijn alle voorgestelde items van een fragment verworpen, dan is het fragment `rejected`.

   `recheck` past dezelfde regels toe op de huidige bron. Dat kan, omdat de cache het citaat bewaart.
5. **Herstel.** Per oorspronkelijke bundel krijgen de daarin mislukte fragmenten samen één uitgestelde poging via `LlmSteps`/`RetryQueue`, met de sleutel `documented:<bundelsleutel>`.
   - De poging geeft een gedeeltelijk resultaat gewoon terug: herstelde delen plus fragmenten die nog steeds mislukken.
   - Alleen een tijdelijke fout over de hele poging gaat via de terugvalroute van `RetryQueue` (`llm.py:161–170`), die alles of niets is.
   - Een geslaagd herstel wordt als eigen bundel opgeslagen.
6. **Terugval per fragment.** `DocumentedOutcome` krijgt `fallback_fragments`: de verzameling (pad, start, eind) van fragmenten die na de drain nog mislukt zijn. Elk item krijgt een eigen terugvalmarkering.
   - `any_fallback = bool(fallback_fragments)`. Deze waarde vervangt `docs.fallback` in `pipeline.py:550` en `_transition` (`pipeline.py:491`), ook als het fragment geen lock-items heeft.
   - Daarnaast voegt C4 de sleutel `documented` toe aan `LlmSteps.fallbacks`, zodat een gedeeltelijk geslaagde herstelpoging de overgang toch tegenhoudt.
   - Het aantal teruggevallen fragmenten staat in het model als `run.fallback_fragments`, en de CLI waarschuwt erover. Zo blijft een fragment zonder lock-items te onderscheiden van een document zonder feiten (invariant 3).
   - **Terugvalitems** uit `locked.documented`. Het lockbestand bewaart geen citaattekst (`documented.py:190`), daarom:
     - een **element** wordt overgenomen als zijn span helemaal binnen de huidige regels van het fragment ligt en `verify_quote` met de term slaagt;
     - een **relatie** wordt overgenomen als alleen haar span helemaal binnen het fragment ligt. Dat is een zwakkere garantie, gelijk aan het huidige gedrag (`documented.py:199`).
   - Spans die door een invoeging zijn verschoven of over twee fragmenten lopen, vallen weg.
   - De markering `fallback` op elementen (`pipeline.py:617–623`) geldt alleen voor elementen met een teruggevallen documentatiecitaat.
7. **Ontdubbelen** over fragmenten heen, op (soort, term, bestand, start, eind) en (van, naar, titel, bestand, start, eind). `hashes` blijft de hash per bestand van de hele set, voor de snelle route.
8. **Rapport.** `assemble` geeft tellingen terug, en de pipeline voegt die toe aan de rapportregels van C4:
   - bundels: hergebruikt, nieuw, gesplitst en teruggevallen, met aantallen fragmenten;
   - ongekoppelde documentatierelaties met reden: **geen treffer** of **meerdere treffers** (`assemble.py:273–278`; rij 83), en **niet toegestaan** (`assemble.py:280–293`; rij 85). Dit is alleen een telling; het koppelgedrag verandert niet.

**Researchhints voor C4:** `order_hint` geeft fragmenten een hogere prioriteit als ze overlappen met bestanden uit `TopicSources`. Dit beïnvloedt alleen de volgorde van aanroepen.

## 9. Research, fase 2 (rij 81)

Hieronder staat het contract. Vóór het implementatieplan voor fase 2 komt er een kort addendum ter goedkeuring, met de details die pas bij research zichtbaar worden.

- **Bundels = researchclusters.** Research levert de clusters uit `cluster_files_hdbscan_bounded` aan als bundels (`bundles=`). `cluster_id` en het factquotum per cluster blijven van research. Halveert de laag een cluster, dan verdeelt research het quotum naar verhouding.
- **Bereiken.** Research zet de inhoud die het nu selecteert om naar regelbereiken: hele bestanden, of uitgebreide indexstukken (`file_reader.py:98–163`). Overlappende bereiken worden samengevoegd. De huidige inkorting op tekens midden in een regel (`file_reader.py:118–123,170–178`) wordt vervangen door afkappen op een regelgrens. Dat is een zichtbare gedragswijziging voor `code_research` en hoort bij de acceptatie van fase 2.
- **Decodering** blijft `errors="ignore"`.
- **Regelnotatie** `absolute`, en `store=None`. Een `FactEntry` krijgt de echte regels in plaats van een schatting.
- **Foutgedrag van research** blijft het huidige, ook voor fouten uit de foutindeling (§6.4). De laag geeft voor research mislukte fragmenten terug; research behandelt die zoals nu een mislukt cluster.
- Fase 2 raakt zowel `chunkhound map` als de MCP-tool `code_research`. Daarom geldt een eigen acceptatie (§10) en een aparte goedkeuring.

## 10. Testen

Contracttests volgens `AGENTS.md`. De nep zit aan de providergrens: een `LLMProvider` waarvan `complete_structured` ruwe dicts teruggeeft of de **echte** foutteksten van providers opwerpt, of nepuitvoer van het CLI-subproces. Er wordt geen nep-`StructuredCall` gebruikt.

1. **Dekking:** na een geslaagde run is elke regel van elk geselecteerd document gedekt. Bij één blijvend falend fragment zijn precies die regels als teruggevallen gemarkeerd.
2. **Terugval zonder lock-items:** een teruggevallen fragment met een leeg lockbestand geeft `documented=None` en `transition=None` in het lockbestand.
3. **Incrementeel:** een ingevoegde regel bovenaan een document geeft alleen aanroepen voor het blok waarin die regel valt. De citaten in de overige, hergebruikte uitkomsten hebben correcte oorspronkelijke regelnummers.
4. **Hervatten:** na een fatale providerfout blijven alle bundels die vóór de fout gevalideerd waren opgeslagen. De volgende run roept alleen niet-opgeslagen bundels aan. Er is geen publicatie en geen lockupdate na de fatale run.
5. **Budget:** voor een bronset van 941.516 bytes overschrijdt geen enkele verzonden aanvraag de limiet. Bij een override naar een lagere limiet blijft dat zo. Een provider die `input_too_large` geeft, leidt tot een fatale configuratiefout met grootte en grens.
6. **Vangnet:** een afgekapt of niet-JSON-antwoord laat de run niet fataal falen. De geldige delen blijven behouden en het rapport toont de splitsing.
7. **Wegwerpbaar:** met een deterministische nep geeft een verwijderde of beschadigde cache dezelfde uitkomst, alleen met meer aanroepen.
8. **Hercontrole:** een cache-uitkomst waarvan het citaat niet meer klopt, wordt niet gebruikt.
9. **Proefmodus:** geen aanroepen, geen nieuwe cachebestanden en geen gewijzigde wijzigingstijden.
10. **Rapport:** ongekoppelde documentatierelaties worden per reden geteld: geen treffer, meerdere treffers en niet toegestaan.
11. **Fase 1 verandert research niet:** de bestaande `--no-c4`- en researchtests blijven ongewijzigd groen.
12. **Research, fase 2:** de regelnummers van een `FactEntry` liggen binnen het aangeleverde bereik. Daarnaast een kwaliteitsvergelijking op vaste vragen; dat is een providerrun en vereist aparte goedkeuring.

Verplicht volgens `AGENTS.md`: de smoke tests, de volledige suite, ruff en mypy.

## 11. Fasering

1. De gedeelde laag, inclusief foutindeling en limietbepaling.
2. C4-aansluiting (§8). Daarna een gecontroleerde maprun, alleen na aparte goedkeuring.
3. Research (§9), na het addendum, met een eigen acceptatie en een aparte goedkeuring.

## 12. Risico's en open punten

- **Recall bij grote bundels:** het model kan meer missen dan bij kleine fragmenten. Dat is niet gemeten; de doelgrootte moet gekalibreerd worden.
- **Schemafouten:** een fout in de vorm van één deel verwerpt de hele bundel en kost een halvering (§5.4).
- **Herkenning van fouten** gebeurt op foutteksten van providers (§6.4). Nieuwe of gewijzigde teksten kunnen worden gemist; dan volgt het huidige gedrag (tijdelijk of fataal).
- **Tokenschatting:** `estimate_tokens` rekent met lengte gedeeld door 4. Voor tekst met veel tekens per token, zoals CJK, is de marge van 20 % geen garantie. Hoe vaak dat voorkomt, is onbekend.
- **Relatietermen over bundels heen** kunnen vaker ongekoppeld blijven. Dit wordt gemeten (§8.8); een vervolgbesluit valt buiten deze spec (rij 83).
- **Terugvalrelaties** worden alleen op span gecontroleerd, net als nu.
- **Besparing voor research** is niet gemeten (rij 76, 81).
- **Nieuwe voorstellen ter review**, niet uit besluiten afgeleid:
  - maximale fragmentgrootte = ÷ 4;
  - verhouding en ondergrens van de uitvoerlimiet;
  - waar de limiet wordt opgegeven;
  - de regels voor blokherkenning in §4;
  - de foutmarkers in §6.4.

## 13. Bronnen

`chunkhound/code_mapper/c4/documented.py:96–286`, `chunkhound/code_mapper/c4/llm.py:19–26,116–179`, `chunkhound/code_mapper/c4/pipeline.py:75–100,491,533–623`, `chunkhound/code_mapper/c4/assemble.py:240–300`, `chunkhound/code_mapper/c4/lockfile.py:10,29–60`, `chunkhound/code_mapper/service.py:95–119`, `chunkhound/interfaces/llm_provider.py:123–216,293–340`, `chunkhound/providers/llm/base_cli_provider.py:396–465`, `chunkhound/providers/llm/anthropic_llm_provider.py:935–946`, `chunkhound/utils/json_extraction.py:76–107`, `chunkhound/core/config/llm_config.py:740–785`, `chunkhound/services/research/shared/evidence_ledger/{models.py:53–103,extractor.py:117–129,clustered_extractor.py:51–143}`, `chunkhound/services/research/shared/file_reader.py:98–178`, `chunkhound/services/research/v1/pluggable_research_service.py:390`.
