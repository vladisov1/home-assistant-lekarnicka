# Lékárnička 0.4.3 – průběžný vývojový kandidát

**NEINSTALOVAT jako stabilní vydání.** V této etapě se opravila kritická chyba SQL migrace nových sloupců, upravila se navigace do tmavě modrého vzhledu a zavedly se funkční rozměrové tiskové profily (Brother 54 × 17, Brother 62 × 29, univerzální 50 × 25 a vlastní rozměr). QR je SVG.

## Co je již součástí rozpracované verze
- Rozšířená karta léku (léková forma, účinná látka, výrobce, SÚKL, ATC, popis a EAN).
- Vyhledávání názvu, EAN, léčivé látky a SÚKL.
- Úprava stavu balení v jeho detailu.
- Expirace: po expiraci, 0–7 a 8–30 dnů, s umístěním.
- AI import nejvýše dvou fotografií jednoho balení, kontrola před importem a návrat.
- Vektorové QR štítky a první volitelné tiskové profily.
- První fáze sjednocení vzhledu a navigace.

## Co stále chybí
- Schválené dvoupanelové rozhraní katalog + detail léku vpravo, kompletní mobilní redesign.
- Rozšířené tiskové profily pro celé archy A4 (řádky, sloupce, mezery, více štítků), obsahové přepínače a skutečný živý náhled.
- Ověřené dohledávání podle EAN v externích databázích.
- Automatické vytváření Home Assistant todo entity a její ikony (technicky neověřeno).
- Spuštění aplikace a integrační/migrační testy s Flaskem a Home Assistantem; fyzický tisk.

## Bezpečnost
Před jakoukoliv instalací zálohujte /data/inventory.db. ZIP je zdrojový balíček repozitáře, nikoliv hotová produkční aktualizace.

## Pokračování: dvoupanelový katalog (2026-11-02)
- Katalog léků používá dva panely: vlevo tabulku, vpravo náhled vybraného léku s údaji a baleními.
- Výběr přes parametr `selected` a vyhledávání přes `q`; stávající plná karta léku i akce zůstávají dostupné.
- Při filtrování úložného místa se náhled zobrazí pouze pro léky z aktuálního seznamu.
- Migrace nyní doplňuje i sloupec `ean`, pokud ve starší databázi chybí.
- Staticky ověřeno: Python kompilace, parsování všech Jinja šablon. Neověřeno v běžícím Home Assistantu.
- Stále zbývá integrace HA seznamu, plnohodnotné tiskové profily a testování v prohlížeči.

## Pokračování: nastavení obsahu a počtu kopií štítku
- Tisková stránka nyní nabízí přepínače zobrazení názvu, expirace a ID balení.
- QR kód balení zůstává vždy přítomen; interní identifikátor se nemění.
- Přidána volba 1–12 kopií s náhledem více štítků a tiskovým zalomením mezi kopiemi.
- Vlastní rozměr štítku zůstává v rozsahu 25–210 × 17–297 mm; nejde o plnohodnotný A4 archový profil.
- Statické kontroly Python/Jinja prošly; Flask není dostupný v tomto prostředí, a proto se neuskutečnil integrační test ani fyzický tisk.

## Pokračování – arch A4 a kontrola entity (2026-11-02)
- Doplněn A4 profil 63,5 × 38,1 mm s nastavením řádků, sloupců, mezer a okrajů. Upozornění při přesahu formátu A4.
- Volitelný tisk kódu úložné krabice; až 120 kopií pro A4.
- Opraven konflikt starších CSS pravidel pro tisk, který fixoval všechny štítky do stejné pozice.
- Před synchronizací košíku se ověřuje existence konfigurované entity přes HA States API; pokud chybí, aplikace poskytne pokyny k vytvoření místního seznamu. Automatické vytvoření ani ikona nejsou implementovány, protože podpora rozhraní nebyla ověřena.
- Statická kompilace Pythonu a parsování Jinja šablon provedeno. Fyzický tisk, běh HA a end-to-end testy neprovedeny.
- Není dokončeno externí dohledávání podle EAN. Verze stále není finální.

## Pokračování – sestavení 5 (2026-11-02)
- A4 tisk nyní rozděluje kopie do samostatných archů podle počtu řádků a sloupců; předtím se více kopií mohlo přelévat přes hranici archu.
- Přidán spustitelný automatický test `tests/test_migration.py` pro migraci starší SQLite databáze a opakované spuštění migrace. Test úspěšně prošel.
- Prošla kontrola syntaxe Pythonu a Jinja šablon.
- Stále neověřeno: skutečný tisk Brother, běh Flask/HA, externí databáze EAN, automatické vytvoření HA todo entity. Nevydávat jako finální verzi.

## Průběžné sestavení 6 (2. 11. 2026)

- Po úspěšné HTTP odpovědi `todo.add_item` se znovu načítá obsah seznamu Home Assistantu.
- Lokální položka se odstraní teprve tehdy, pokud HA skutečně vrátí její název v seznamu.
- Při neúspěšném potvrzení zůstává položka v lokálním košíku. Opakování může narazit na zpožděné propsání položky; další synchronizace kontroluje duplicity.
- Přidán statický regresní test pořadí operací a znovu spuštěn test migrace databáze.
- Stále neověřeno: provoz v HA, tisk na Brother, externí EAN, automatické založení lokálního todo seznamu.

## Průběžné sestavení 7 – offline testy rozhraní Home Assistant

Doplněny čtyři izolované testy smlouvy API Home Assistantu (`tests/test_ha_todo_contract.py`):
- načtení seznamu `todo.leky` v očekávaném formátu a normalizace názvů,
- odmítnutí neznámého formátu odpovědi místo předpokladu prázdného seznamu,
- bezpečné ošetření HTTP 404 při neexistující entitě,
- kontrola cílového endpointu a payloadu `todo.add_item`.

Celkem šest offline testů prošlo (`python -m unittest discover -s tests -v`). Testy používají simulované HTTP odpovědi a **nenahrazují provozní test v Home Assistantu**. Automatické založení entity ani externí dohledání podle EAN zatím nejsou implementovány. Balíček není určen k instalaci.

## RC1 (testovací sestavení)
- Připraven balíček s verzí `0.4.3-rc1` pro kontrolované testování.
- Upravena tisková CSS deklarace, která nastavovala viditelnost všem elementům stránky.
- Žádné nové externí EAN API ani automatické zakládání HA entity není deklarováno jako hotové.
