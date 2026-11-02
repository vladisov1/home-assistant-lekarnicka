# Lékárnička 0.4.3-rc1 — testovací kandidát

**ALPHA / RC.** Nejde o stabilní vydání. Neověřeno v běžícím Home Assistantu ani na tiskárně Brother QL-700.

## Instalace přes stávající GitHub repozitář

1. V Home Assistantu vytvořte úplnou zálohu, zvláště dat stávající Lékárničky. ZIP **není** soubor pro přímé nahrání do obchodu s doplňky; obsahuje zdrojové soubory repozitáře.
2. Pokud chcete minimalizovat riziko, testujte na samostatné instanci Home Assistantu. Aktualizace stejného add-on slugu `lekarnicka` sdílí jeho `/data` s předchozí verzí.
3. Na GitHubu v repozitáři `vladisov1/home-assistant-lekarnicka` nahraďte obsah složky `lekarnicka/` obsahem ze ZIP a přidejte případné testy a dokumentaci. Doporučujeme samostatnou větev `test-v043-rc1`, nikoliv rovnou produkční `main`.
4. Aby Home Assistant nabídl aktualizaci, musí změněné soubory být v **větvi, ze které je připojený repozitář doplňku načítán** (standardně `main`). Pouhá vedlejší větev aktualizaci nevyvolá. Na testovací instanci připojte testovací repozitář/větev podle možností HA, případně až po záloze proveďte kontrolované vydání na `main`.
5. V Home Assistantu otevřete **Nastavení → Doplňky / Aplikace → Obchod**, obnovte zdroje repozitáře a ověřte, že se nabízí verze `0.4.3-rc1`. Před instalací zkontrolujte zálohu.
6. Po instalaci otevřete webové rozhraní, vytvořte jeden **testovací lék** a jedno balení. Nezadávejte citlivé údaje ani produkční tokeny do veřejného repozitáře.

## Testovací scénáře

- [ ] Otevře se Přehled, Katalog, Úložné boxy, Expirace, Nákupní seznam, Nastavení.
- [ ] Nový lék: název, EAN, forma, účinná látka, výrobce, SÚKL, ATC, popis a poznámka se uloží.
- [ ] Vyhledání podle EAN funguje; externí ověření EAN **zatím není implementováno**.
- [ ] Dvě fotografie v AI importu představují jeden záznam; funkce vyžaduje nastavený API klíč.
- [ ] Balení lze upravit: expirace MM/RRRR, stav, umístění a poznámka.
- [ ] Expirace zobrazuje intervaly 0–7, 8–30 a prošlé.
- [ ] Štítek Brother 54 × 17 mm: QR jde načíst z fyzického výtisku (100% měřítko).
- [ ] A4 arch: zvolený počet kopií a rozmístění sedí na tiskovém náhledu.
- [ ] Nákupní seznam: po potvrzeném odeslání do HA položka zmizí z interního košíku.
- [ ] Při neexistující entitě HA se zobrazí pokyn a položky zůstanou zachované. Automatické založení entity **není implementováno**.

## Známé limity

- Externí dohledávání EAN a automatické vytvoření místního `todo` seznamu dosud chybí.
- Fyzický tisk a živá komunikace s Home Assistantem nebyly ověřeny.
- V této verzi neměňte produkční instalaci bez zálohy; zpětný downgrade databáze není garantován.

Při problému pošlete obrazovku chyby a log aplikace (bez hesel a tokenů).
