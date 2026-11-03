# Lékárnička 0.4.7 RC2 – test QR na Brother QL-700

1. Před aktualizací zálohujte databázi Lékárničky. Jde o vývojovou verzi.
2. Zvolte jedno fyzické balení → Tisk štítku → Brother 54 × 17 mm.
3. V dialogu Brother nastavte DK-11204, měřítko 100 %, bez přizpůsobení stránce, bez automatických okrajů.
4. Vytiskněte **jeden** štítek. Ověřte, zda QR obsahuje celou krátkou adresu `/p/<short_id>` a zda otevře správné balení.
5. Pokud QR nejde přečíst, pošlete snímek tisku a nastavení ovladače. Nepřelepujte ostatní balení.

Technické parametry RC2: QR Model 2, ECC M, cílová verze 4, PNG 164×164 pixelů, 4 tiskové body/modul včetně čtyřmodulového okraje, fyzický rozměr 13,885 mm při 300 dpi. U příliš dlouhé URL se verze zvýší automaticky.
