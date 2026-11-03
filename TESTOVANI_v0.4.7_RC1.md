# Lékárnička 0.4.7 RC1 – testovací postup

1. Před instalací zazálohujte databázi. Ověřte zachování všech původních léků a balení.
2. V katalogu zkontrolujte, že každé balení má označení BAL-xxxxxx a současně umístění L-01 apod.
3. Otevřete QR štítek a zkontrolujte, že obsahuje krátkou adresu `/p/<short_id>`; vyzkoušejte fyzický tisk a sken.
4. Na rychlé kartě proveďte odečet 5 tablet, ověřte zůstatek, stav rozbaleno a historii pohybů.
5. Zkuste vrátit tablety do naskenovaného balení a potvrdit cílovou krabičku.
6. Zkuste naskenovat jedno balení a pomocí „Ukázat další balení“ vrátit tablety do jiného balení stejného léku. Zkontrolujte, že se první balení nezměnilo.
7. Zkuste neplatný odečet (více než zůstatek) a vrácení nad původní kapacitu; musí být zamítnuty.
8. Na desktopu otevřete „Pohyby a vrácení“ a vyzkoušejte filtrování; levý katalog musí zůstat viditelný.
9. Otestujte i přidání nového balení, jeho nové BAL číslo a tisk štítku.
10. Ověřte přístup z Home Assistant Ingress i přes přímou lokální adresu (pokud používáte); nevystavujte port 8099 veřejnému internetu bez ochrany.

**Poznámka:** Historie před aktualizací není k dispozici. Jde o vývojový RC1, ne produkčně ověřenou verzi.
