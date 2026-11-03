## 0.4.7 RC3 – testovací oprava Brother QR (3. 11. 2026)
- Nová cesta pro Brother DK-11204: vektorové PDF s QR maticí 12,50 mm, QR Model 2, verze 4, ECC M, poloha x=3 mm, svisle vystředěno, bez škálování bitmapy.
- Profil Brother nyní nabízí stažení přesného PDF namísto nekalibrovaného tisku HTML.
- Dlouhé adresy, které nelze zakódovat do verze 4, se explicitně odmítnou; nedochází k tiché změně geometrie.
- Jednotný údaj o verzi pro horní lištu a postranní panel, aktualizované README a config.yaml.
- **Zatím neověřeno na reálném tisku přímo z RC3; jde o kandidáta k testování.**

## 0.4.7 RC2 – testovací oprava QR tisku (3. 11. 2026)
- Brother DK-11204 (54 × 17 mm): zkušební QR Model 2, ECC M, verze 4, 4 body/modul, 4modulový ochranný okraj.
- PNG rastr bez interpolace místo SVG, které mohlo být v prohlížeči nevhodně přepočítáno.
- Profil QR 13,885 mm (164 bodů při 300 dpi), krátký odkaz `/p/<short_id>` zachován.
- Pokud se adresa nevejde do verze 4, generátor zvolí vyšší verzi; čitelnost může být odlišná.
- **Dosud neověřeno fyzickým tiskem v Lékárničce.** Nejdříve vytisknout jediný testovací štítek.

## 0.4.6 – doplnění podpory Home Assistant Ingress (kandidát)

- Zapnuta podpora Ingress na interním portu 8099.
- Zobrazení v postranním panelu je volitelné a spravuje jej správce v nastavení doplňku; není zapnuto automaticky.
- `panel_admin: false` umožňuje položku zobrazit i běžným uživatelům Home Assistantu.
- Flask generuje odkazy s prefixem Ingress při požadavcích od interní proxy Supervisoru.
- Přihlášení Home Assistantu nahrazuje heslo aplikace pouze pro požadavky od důvěryhodné proxy; přímý přístup přes port 8099 zůstává beze změny.
- Vyžaduje integrační ověření v Home Assistantu.

## 0.4.6 – další kandidát k ověření (2026-11-03)

- Oddělena validace kusové spotřeby do samostatného modulu `consumption.py`.
- Zpřísněna kontrola odečtu, neměnnosti počátečního množství a jednotek u sledovaného balení.
- Přidány jednotkové testy plného balení, částečné spotřeby, vyčerpání a chybných vstupů.
- Doplněno zahrnutí validačního modulu do Docker image.
- Stav: kandidát k ověření; provozní instalace a migrace dosud neověřeny.

## 0.4.6 – bezpečnostní kontrola odečtů (3. 11. 2026)

- Oprava validace odečtu: server používá skutečný zůstatek v databázi, nikoliv upravitelnou hodnotu odeslanou formulářem.
- Při zahájení evidence se zůstatek inicializuje počátečním množstvím.
- Zamítnutí záporných, nadlimitních a neplatných odečtů; zachování kontextu při chybě.
- Kontrolní testy aktualizovány. Stále vývojový kandidát bez ověření ve spuštěném Home Assistantu.

## 0.4.6 – rozšířený kandidát k ověření (3. 11. 2026)

- Zamezení změně počáteční kapacity již sledovaného balení při odečtu spotřeby.
- Oprava návratu tlačítkem Zrušit se zachováním kontextu úložné krabice.
- Neaktivní tlačítko Odstranit lék s vysvětlením při existenci fyzických balení.
- Zobrazení množství počáteční/zbývající také na kartě balení v detailu léku.
- Doplněny regresní kontroly těchto změn.

**Stále vývojové sestavení:** bez integračního ověření ve Flasku a Home Assistantu.

## 0.4.6 – předchozí kandidát (3. 11. 2026)

- Zachování vybraného léku při návratu z editace léku, balení a detailu.
- Návazná obrazovka po přidání balení s odkazy na QR štítky nových balení.
- Dvousloupcová editace fyzického balení, tlačítko Zrušit.
- Počítadlo −/+ a posuvník pro odečet kusových jednotek; zůstatek počítá aplikace.
- Zobrazení množství jako počáteční/zbývající v přehledu balení.

**Poznámka:** Kandidát k ověření, nikoli potvrzené finální vydání. Počáteční množství lze nastavit při zahájení evidence; při prvním uložení se zbývající množství automaticky doplní. Editace balení po uložení vrací do katalogu s vybraným lékem. Bez ověření běžícího Flask rozhraní a instalace v Home Assistantu nelze vydání označit za stabilní. Dříve plánované integrace SÚKL, PIL/SmPC a AI importů nejsou tímto označeny za dokončené.

## 0.4.4-rc2 – rozpracovaná testovací sestava (2026-11-02)

### Nově implementováno
- Ruční import katalogu SÚKL ze souboru CSV nebo ZIP s rozpoznanými sloupci kódu a názvu; bezpečné zpracování ZIP bez extrakce na disk a limit velikosti 32 MB.
- Transakční nahrazení pouze lokálního katalogu SÚKL. Záznamy uživatelů, jejich balení a poznámky zůstávají zachované.
- Vyhledávání v lokálním katalogu podle názvu nebo sedmimístného kódu SÚKL.
- Ruční přiřazení vybraného katalogového záznamu SÚKL ke stávajícímu léku, bez změny jeho názvu, EAN a fyzických balení.
- Dva automatické testy importního parseru.

### Důležitá omezení
- Oficiální struktura všech aktuálních DLP souborů SÚKL ještě nebyla ověřena na reálném exportu. Import rozpozná pouze některé názvy sloupců; další mapování může být nutné.
- Automatické stažení a pravidelná aktualizace SÚKL zatím nejsou implementovány.
- Import je omezen na ZIP/CSV do 32 MB; ZIP může obsahovat více CSV, hledá se první podporovaný soubor.
- V místním prostředí chybí Flask a další runtime závislosti, proto nebylo možné provést integrační testy webového rozhraní.
- Jde o vývojový RC balíček, nikoliv stabilní aktualizaci. **Neinstalovat na produkční data bez zálohy a testovací instance.**

# Historie změn

## 0.4.4-rc1 – vývojová testovací sestava

### Implementováno v tomto balíčku
- Rozšíření SQLite schématu s aditivní migrací pro pole SÚKL, zásoby, spotřebu a pokyny k balení.
- Validace sedmimístného kódu SÚKL v ručním formuláři; stávající vyhledávání podle kódu SÚKL zachováno.
- Formulář pro rozšířené registrační údaje léku (zatím ruční zadání).
- Nastavení volitelné podrobné evidence kusových jednotek; samostatné množství u každého fyzického balení.
- Automatická archivace balení při uložení nulového zbývajícího počtu.
- Individuální rozpis a předvolené pokyny k užívání přiřazené konkrétnímu balení.
- Hlídání minimální zásoby podle počtu aktivních balení nebo podle součtu kusových jednotek; upozornění a možnost přidat do místního košíku.
- Původní funkce 0.4.3-rc1 jsou zachovány ve zdrojových souborech.

### Zatím neimplementováno / neověřeno
- Automatické stažení, rozbalení a import otevřených dat SÚKL ZIP/CSV a jejich aktualizace.
- Párování fotografií s místním katalogem SÚKL, oficiální dokumenty PIL/SmPC a jejich odkazy.
- Plně nový design přesně podle referenčního obrázku, čtyři interaktivní záložky podrobné karty.
- Kompletní dekódování GS1 Data Matrix a automatické předvyplnění všech údajů.
- Všechny dříve diskutované drobné UX opravy nejsou v této sestavě ověřeny.
- Test v běžícím Home Assistantu a kompletní integrační testy (v místním prostředí nebyl dostupný Flask).

**Nenasazovat jako stabilní produkční verzi. Před zkouškou zálohujte databázi.**

## 0.4.4 RC3 (vývojová sestava, 2026-11-02)
### Implementováno
- Čtyři samostatné záložky detailu léku: Údaje, Dokumenty, Balení a Poznámky. Zobrazení dokumentů zatím správně uvádí, že jejich propojení není ověřeno.
- Samostatná obrazovka importu EAN/GTIN, ruční zadání a běžná klávesnicová čtečka; vyhledávání v již existujících místních záznamech a navázání nového balení.
- Menší úpravy kompaktního vzhledu a označení verze.
### Nedokončeno – povinné pro finální 0.4.4
- Automatické stahování/aktualizace a validace skutečných dat SÚKL; oficiální dokumenty PIL/SmPC.
- Spolehlivá identifikace dosud neznámého EAN, dekódování Data Matrix, fotografie čárového kódu a kompletní AI kontrolní proces.
- Dotažení redesignu podle schválené reference a všechny regresní a migrační testy v Home Assistantu.
- Audit všech schválených požadavků, včetně nastavení HA seznamu a oprav UI.
### Ověření
- Syntaxe Pythonu a 8 nezávislých testů prošly; dva integrační testy se nepodařilo spustit kvůli nedostupné knihovně Flask/Werkzeug v tomto prostředí. Nejde o potvrzenou instalační sestavu.

## 0.4.5 RC1 — vizuální aktualizace (3. 11. 2026)
- Přestavba horní lišty včetně vyhledávacího pole, tmavé navigace a kompaktního katalogu.
- Odstranění nadměrného horního odsazení, nové proporce katalogu a pravého panelu.
- Sjednocení tabulek, detailů, záložek, typografie a formulářů.
- Úprava označení fyzických balení v katalogu a detailu: nezobrazovat databázová ID jako pořadová čísla.
- Sekce spotřeby a individuálních pokynů v editaci balení jako rozbalovací skupiny; vyplněné skupiny se otevřou.
- Bez změny databázového modelu, backendových funkcí a migračních pravidel.

### Zůstává k řešení mimo čistě vizuální rozsah 0.4.5
- Bezpečná akce „Odstranit lék“ s vysvětlením při deaktivaci (vyžaduje rozhodnutí o archivovaných baleních a úpravu backendu).
- Po uložení balení automaticky otevřít záložku Balení a zvýraznit nový záznam (změna toku aplikace).
- Funkce označené v přehledu 0.4.4 jako nedokončené nejsou tímto vydáním implementovány.

## 0.4.7-rc1 – testovací kandidát (3. 11. 2026)

- Trvalé veřejné označení fyzického balení `BAL-000001` a krátký QR odkaz `/p/<short_id>`; umístění `L-01` zůstává samostatné.
- Rychlá karta QR pro odečet a vrácení; u vrácení volba právě skenovaného nebo jiného balení stejného léku, s potvrzením cíle.
- Zápis časově označených změn množství do tabulky `package_movements` a kontrola kapacity při QR operacích.
- Filtry historie podle typu, data, počtu a balení v pravém panelu desktopového katalogu; levý seznam léků zůstává viditelný.
- Zobrazení stavu „Rozbaleno“ v náhledu při již sníženém množství.

**Omezení RC1:** Neověřeno v reálné instalaci Home Assistantu ani na tiskárně Brother QL-700. Historie se vytváří až od instalace této verze, dřívější odečty nelze zpětně rekonstruovat. Před testem proveďte zálohu databáze. Nejde o produkčně ověřené vydání.
