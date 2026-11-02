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
