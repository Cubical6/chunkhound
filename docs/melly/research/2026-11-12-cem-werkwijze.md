# Onderzoek: de CEM-werkwijze van de gebruiker (praktijkvoorbeeld voor §1 en §2)

Datum: 2026-11-12. Hoort bij B11.

De bron is een eigen uitwerking van de gebruiker: een conceptueel enterprisemodel (CEM) van een ticketsysteem met gebruikers, rollen, permissies, modules en instellingen, gemaakt met de CogNIAM-methode. Het bestand staat lokaal en hoort niet in deze repository. Deze notitie beschrijft alleen de opbouw en de werkwijze, zonder waarden uit het bestand.

Het boek blijft leidend (B10). De CEM laat zien hoe de gebruiker de methode op bestaande en nieuwe software toepast. Uitleg van afkortingen die het bestand zelf niet geeft, staat hieronder als **interpretatie**.

## Stappen: één werkblad per stap

1. **Verwoorden.** Het werkblad bevat deze deelstappen:
   - concrete zinnen over het systeem verwoorden;
   - classificeren;
   - kwalificeren: elke waarde krijgt haar begrip;
   - grenzen vaststellen;
   - begripsdefinities opstellen: term, definitie en bron;
   - identificeren: de vaste zin uit het boek, "Binnen de verzameling van alle … identificeert … een specifieke …";
   - sjabloniseren.

   Bij het sjabloniseren ontstaan twee soorten sjablonen:
   - "back-end": per begrip het identificerende sjabloon;
   - "front-end": per feittype het gekwalificeerde zinsjabloon.

   De invulplaatsen in beide soorten zijn veldnamen uit de code, zoals `<first_name>` en `<id>`.
2. **Diagrammen.** Elk begrip krijgt eerst een eigen elementair feittype met één rol. Bij elk feittype horen een nummer, het identificerende sjabloon en een populatie.
3. **Uniciteiten.** Elk feittype krijgt een uniciteitsregel. Verwijzingen tussen feittypen worden deelverzamelingen.
4. **Samenvoegen.** Een matrix vergelijkt alle paren feittypen op diagram, uniciteit en populatie, en bepaalt zo wat samengaat.
   - Het resultaat is elf samengestelde feittypen, elk met precies één tabel.
   - Tabellen die al in de code bestaan, zijn gemarkeerd als "bestaande tabel". Het gaat om zeven bestaande tabellen (onder meer `users` en `roles`) en vier nieuwe.
   - Waarden die in de code vastliggen, zijn gemarkeerd als "hardcoded".
5. **Waardenregels.** Elke kolom krijgt de volgende gegevens:
   - de herkomst van de waarde;
   - het datatype;
   - of de kolom verplicht is;
   - waar nodig een waardenregel. Die vervangt een eerdere markering "hardcoded".
6. **CEM.** Het eindresultaat, gelijk aan stap 5.

## Opbouw van een feittypeblok

| Rij | Inhoud | Kennisklasse |
|---|---|---|
| Kop | Nummer en naam van het feittype. Bij een samengesteld feittype de tabelnaam en eventueel "bestaande tabel" | ZS |
| Kolommen | Eén kolom per rol, met het begrip als kop | VAR, BO |
| 1 | Uniciteit: `PK n` op één rol. `Ak: 10xx` over een samengesteld feittype (**interpretatie**: uniciteit over de combinatie van rollen) | VR |
| 2 | Deelverzameling: `Hfd: 20xx` bij de verzameling waarnaar verwezen wordt en `Dl: 20xx` bij de verwijzende rol. Dat is een *foreign key* (**interpretatie**: Hfd = hoofdverzameling). Verder de herkomst (`INVOER n` of `AUTOMATISCH n`) en de waardenregel `{}: 50xx = "a, b, …"` | VR; herkomst: zie hieronder |
| 3 | Datatype, zoals `STR`, `TEXT`, `BIG INT` of `TIMESTAMP` | VAR |
| 4 | `NL` bij verplichte kolommen. Een optionele kolom, zoals een tussenvoegsel, heeft het niet (**interpretatie**: verplichte rol, `NOT NULL`) | VR |
| 5 | Zinsjablonen: eerst het feittypesjabloon, dan de identificerende sjablonen | ZS |
| 6 en verder | Populatie: voorbeeldfeiten. Opeenvolgende rijen verschillen vaak op één waarde. Zo toetst de gebruiker welke rollen uniek zijn | niveau I |

De regelnummers staan in blokken per soort:
- 1000 voor uniciteit over meerdere rollen;
- 2000 voor deelverzamelingen, met het nummer van het elementaire feittype erin;
- 5000 voor waardenregels.

Dat sluit aan op de blokken per regelsoort die de subagent in het boek vond (zoals `wr5001`). Die bevinding is nog niet nagelezen; zie het [onderzoek naar het boek](2026-11-12-cogniam-boek-metamodel.md).

## Wat de CEM niet bevat

De CEM is een statisch model en dekt vooral BO, VAR, ZS en VR, plus de populaties (niveau I).

Afleidings-, uitwisselings- en eventregels staan er niet als eigen regel in. Er zijn wel aanwijzingen voor:
- de herkomst `INVOER` of `AUTOMATISCH`;
- de werkwoorden in de zinsjablonen ("registreert zich", "heeft … aangemaakt", "heeft … geüpdatet").

Voor AR, UR en ER blijft het boek de enige bron.

## Gevolgen voor §1 en §2 (voorstellen)

1. **De invulplaats koppelt het feittype aan de code.** Een rol in een zinsjabloon draagt de naam van een veld in de code. Voor §2 is dat het anker:
   - een kolom of modelveld is een VAR;
   - de tabel of het model is een samengesteld feittype met een ZS.
2. **Een invulplaats moet uniek zijn binnen haar sjabloon.** In de CEM komt `<id>` soms meerdere keren in één sjabloon voor, voor verschillende begrippen. Voor een machineleesbaar contract is dat dubbelzinnig. Voorstel voor §1: de invulplaats heet naar de rol (het begrip), met een aparte koppeling naar het codeveld, zoals `users.id`.
3. **"Bestaande tabel" tegenover een nieuwe tabel** is precies de tweede as van U1: *gerealiseerd* tegenover *gepland* (B6, B7). De CEM combineert de bestaande code met een nieuw ontwerp in één model, en dat is het gebruik dat B6 beoogt.
4. **De soorten validatieregels in de CEM zijn wat §2 vast uit schema's kan lezen:**

   | Regelsoort | In de code |
   |---|---|
   | Uniciteit | `PRIMARY KEY`, `UNIQUE` |
   | Deelverzameling | `FOREIGN KEY` |
   | Waardenregel | enum, `CHECK`, vaste lijsten in de code |
   | Verplichte rol | `NOT NULL` |
   | Datatype | Kolomtype |

   Waarden die in de code vastliggen ("hardcoded") zijn kandidaten voor een waardenregel.
5. **De herkomst per veld wijst naar andere kennisklassen** (**interpretatie**):
   - `INVOER`: de waarde komt van buiten, via een uitwisselingsregel (formulier, endpoint);
   - `AUTOMATISCH`: het systeem maakt de waarde zelf, zoals een oplopend id of een tijdstempel. Dat wijst op een afleidings- of eventregel.
6. **Elke regel heeft een id, genummerd in blokken per soort.** Dat helpt bij de keuze over granulariteit in §1, en bij regel-id's in testnamen (§7).
7. **Populaties met varianten zijn testgevallen.** Een rij die op één waarde verschilt, toetst één regel. Dat is de vorm die §7 nodig heeft: een concreet voorbeeld met een verwachte uitkomst.
