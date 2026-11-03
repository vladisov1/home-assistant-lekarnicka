# Lékárnička pro Home Assistant — 0.4.7 RC3 (TESTOVACÍ VERZE)

Vývojový kandidát, **nikoliv stabilní vydání**. Před aktualizací zálohujte databázi.

## Změny RC3
- Brother QL-700 / DK-11204: nový tisk přes přesné vektorové PDF 54 × 17 mm s QR maticí 12,50 mm podle fyzicky úspěšného testu 1. Ověření tisku přímo z aplikace zatím čeká na test.
- Jednotné označení verze v UI z centrální konstanty; aktualizace config.yaml, README a CHANGELOG.
- Ostatní funkce navazují na RC2; nedokončené funkce nejsou označeny za hotové.

Podrobnosti: [CHANGELOG.md](CHANGELOG.md), [testovací postup RC3](TESTOVANI_v0.4.7_RC3.md).

**Pozor:** QR PDF vytváří odkaz podle adresy, ze které je Lékárnička otevřena. Pro štítky používané na telefonu ji otevřete přes stabilní dosažitelnou adresu. U dlouhých adres, které se nevejdou do QR verze 4, aplikace vrátí chybu namísto tisku neověřeného kódu.

Do repozitáře neukládejte databáze, tokeny, hesla ani `options.json`.
