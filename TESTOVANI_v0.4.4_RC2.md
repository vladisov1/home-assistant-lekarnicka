# Testování 0.4.4-rc2

1. Používejte pouze testovací instanci Home Assistantu. Nejprve proveďte zálohu datového adresáře add-onu (`/data/inventory.db`).
2. Ověřte, že se zobrazují původní léky, jejich balení, expirace a nákupní seznam.
3. V Nastavení otevřete „Správa katalogu SÚKL“. Nahrajte malý CSV soubor se sloupci `Kód SÚKL;Název;Doplněk názvu;ATC` a jedním testovacím řádkem `0254421;PARALEN;100MG SUP 5;N02BE01`.
4. Ověřte, že vyhledávání podle `0254421` i `PARALEN` najde záznam.
5. Otevřete existující testovací lék a přes „Vyhledat a přiřadit ze SÚKL“ potvrďte správný záznam. Ověřte, že původní název, poznámky, EAN a fyzická balení zůstaly nezměněny.
6. Nahrajte neplatné CSV a ověřte, že dříve importovaný katalog zůstal zachován.
7. Ověřte hlídání zásob, archivaci prázdných kusových balení a individuální pokyny.

**Omezení:** Skutečná kompatibilita se soubory DLP SÚKL, produkční instalace a kompletní integrační testy nebyly ověřeny.
