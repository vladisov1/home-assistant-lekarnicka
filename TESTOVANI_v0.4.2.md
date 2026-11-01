LÉKÁRNIČKA v0.4.2 — ZPRÁVA O OVĚŘENÍ

ÚSPĚŠNÉ OFFLINE KONTROLY
- Syntaxe zdrojového souboru app.py (AST).
- Parsování všech HTML/Jinja šablon.
- Převod expirace MM/RRRR -> YYYY-MM a zpět.
- Odmítnutí neplatného měsíce a formátu expirace.
- Rozšíření CSV počtu balení a jediné balení při count=1.
- Dvakrát provedená migrace reprezentativní databáze staršího schématu.
- Zachování vzorového léku, fyzického balení a nákupní položky.
- PRAGMA integrity_check = ok.

NEOVĚŘENO
- Běhový test Flask/Gunicorn: Flask není v kontrolním prostředí nainstalovaný.
- Skutečné odeslání do todo.leky, včetně chybových stavů.
- AI rozpoznání reálné fotografie a výsledná kontrola před importem.
- Interaktivní dvoufázové přidávání balení v prohlížeči.
- Tisk Brother QL-700.
- Migrace skutečné produkční databáze uživatele.

ZÁVĚR
Balíček je kandidát pro izolované testování, nikoli potvrzená finální produkční verze.
Do stávající instalace v0.4.1 zatím nezasahovat. Před zkušebním nasazením
vytvořit zálohu aplikace a kopii programových souborů.
