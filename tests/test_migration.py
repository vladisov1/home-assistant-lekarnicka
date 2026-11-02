"""Run: python -m unittest discover -s tests -v (no Flask required)."""
import ast
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'lekarnicka' / 'app.py'

class MigrationTests(unittest.TestCase):
    def test_legacy_data_preserved_and_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            dbfile = os.path.join(folder, 'inventory.db')
            con = sqlite3.connect(dbfile)
            con.executescript('''
            CREATE TABLE medicines(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '');
            CREATE TABLE locations(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL UNIQUE,description TEXT NOT NULL DEFAULT '');
            CREATE TABLE packages(id INTEGER PRIMARY KEY AUTOINCREMENT,medicine_id INTEGER NOT NULL,location_id INTEGER NOT NULL,expiry TEXT,opened_at TEXT,notes TEXT NOT NULL DEFAULT '');
            CREATE TABLE shopping_items(medicine_id INTEGER PRIMARY KEY,item_name TEXT NOT NULL);
            INSERT INTO medicines VALUES(1,'Testovací lék','Poznámka');
            INSERT INTO locations VALUES(1,'A1','Box');
            INSERT INTO packages VALUES(1,1,1,'2026-12',NULL,'Poznámka balení');
            INSERT INTO shopping_items VALUES(1,'Testovací lék');
            ''')
            con.commit();con.close()
            def db():
                c=sqlite3.connect(dbfile);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
            tree=ast.parse(SOURCE.read_text())
            init=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='init_db')
            code=compile(ast.Module(body=[init],type_ignores=[]),str(SOURCE),'exec')
            scope={'db':db};exec(code,scope)
            scope['init_db']();scope['init_db']()
            with db() as c:
                self.assertEqual(c.execute('SELECT name,notes FROM medicines WHERE id=1').fetchone()['notes'],'Poznámka')
                self.assertEqual(c.execute('SELECT expiry,notes FROM packages WHERE id=1').fetchone()['notes'],'Poznámka balení')
                self.assertEqual(c.execute('SELECT quantity FROM shopping_items WHERE medicine_id=1').fetchone()['quantity'],1)
                self.assertIn('ean',[r['name'] for r in c.execute('PRAGMA table_info(medicines)')])
                self.assertEqual(c.execute('SELECT COUNT(*) FROM packages').fetchone()[0],1)

if __name__=='__main__':unittest.main()
