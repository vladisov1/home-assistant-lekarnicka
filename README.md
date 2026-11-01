# Lékárnička pro Home Assistant

Vlastní aplikace pro evidenci léků, balení a úložných boxů.

## Instalace z repozitáře

Přidejte adresu `https://github.com/vladisov1/home-assistant-lekarnicka` v Home Assistantu v části Aplikace → Repozitáře, obnovte seznam a nainstalujte Lékárničku.

**Upozornění:** Verze 0.4.2 je testovací kandidát, dosud neověřený v běžícím Home Assistantu. Před testováním zálohujte data. Instalace z GitHubu má jiný identifikátor než lokální `local_lekarnicka`; její `/data` se automaticky nepřenáší. Neodinstalovávejte původní aplikaci, dokud není přenos dat ověřen.

## Aktualizace

Při novém vydání aktualizujte soubory aplikace a hodnotu `version` v `lekarnicka/config.yaml`. Home Assistant může nabídnout aktualizaci po obnovení informací o repozitáři.

## Soukromí

Do repozitáře nevkládejte databázi `inventory.db`, `options.json`, hesla, API klíče ani tokeny.
