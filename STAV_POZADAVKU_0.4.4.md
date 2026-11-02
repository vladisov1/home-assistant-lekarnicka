# Lékárnička 0.4.4 – závazný přehled požadavků

Stav odpovídá pouze kontrole zdrojového kódu a dostupným testům; **není** potvrzením funkčnosti v Home Assistantu.

| Požadavek | Stav | Co zbývá |
|---|---|---|
| Schválený redesign tmavě modré navigace a dvoupanelového katalogu | částečně | srovnání s původní referencí, funkční testy a mobilní zobrazení |
| Čtyři záložky karty léku | implementováno RC3 | test zobrazení v HA; Dokumenty zatím bez oficiálních souborů |
| Místní katalog SÚKL, sedmimístný kód | částečně RC2 | ověřit export a automatické aktualizace |
| PIL/SmPC/text na obalu | neimplementováno | spolehlivě mapovat na konkrétní variantu |
| AI fotografie, 1–2 fotografie na jeden lék | částečně původní | ověřit scénáře a oddělení balení/obsahu |
| EAN ruční / čtečka | částečně RC3 | pouze lokální shoda; GTIN check digit a nové identifikace |
| Fotografie EAN / GS1 Data Matrix | neimplementováno | dekódování a kontrola |
| Fyzická balení, šarže, QR, stav, expirace | částečně | integrační test a migrace |
| Detailní odečty tablet/kapslí/sáčků a archivace | částečně RC1 | integrační test, přísné jednotky |
| Kapky/sirupy/masti: bez detailních odečtů | schváleno | ověřit, že UI nenabízí odečty |
| Minimální zásoba za celý lék, volitelně | částečně RC1 | všechny hraniční scénáře a duplicity košíku |
| Pokyny k užívání pro konkrétní balení | částečně RC1 | ověřit UI a uložení |
| Expirace 0–7, 8–30, prošlé | existuje | regresní test |
| Úložné boxy, odstranění duplicit a formulářů | neověřeno | cílený audit |
| Nákupní košík a Home Assistant todo | neověřeno | test úspěchu, neúspěchu a konfigurace entity |
| Tisk štítků a QR | existuje | regresní test |
| Zachování databáze při aktualizaci | neověřeno | test na kopii reálné 0.4.3 databáze |
| Apify | vědomě odloženo | **neimplementovat** |

## Podmínky pro stabilní vydání
Žádný neověřený bod neoznačovat za hotový. Před instalací přes produkční verzi vytvořit zálohu; provést migrační test na kopii databáze a integrační testy v Home Assistantu.
