import os
import sys
import tempfile
import importlib.util
from pathlib import Path


def load_app(tmp):
    os.environ['LEKARNICKA_DB'] = str(tmp / 'inventory.db')
    spec = importlib.util.spec_from_file_location('lek_v044', Path(__file__).parents[1] / 'lekarnicka' / 'app.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_v044_migration_and_stock():
    with tempfile.TemporaryDirectory() as d:
        app = load_app(Path(d))
        with app.db() as con:
            mid = con.execute("INSERT INTO medicines(name,stock_alert_enabled,stock_alert_mode,stock_alert_threshold) VALUES('Test',1,'units',3)").lastrowid
            lid = con.execute("INSERT INTO locations(code) VALUES('A')").lastrowid
            con.execute("INSERT INTO packages(medicine_id,location_id,initial_quantity,remaining_quantity,quantity_unit) VALUES(?,?,?,?,?)", (mid,lid,20,2,'tablety'))
            con.execute("INSERT INTO packages(medicine_id,location_id,initial_quantity,remaining_quantity,quantity_unit) VALUES(?,?,?,?,?)", (mid,lid,20,10,'tablety'))
            assert app.stock_status(con,mid)['amount'] == 12
            assert not app.stock_status(con,mid)['low']
            con.execute('UPDATE packages SET remaining_quantity=1 WHERE medicine_id=?', (mid,))
            assert app.stock_status(con,mid)['low']
        app.init_db()
        assert app.valid_sukl('0254421')
        assert not app.valid_sukl('254421')


def test_forms_render():
    with tempfile.TemporaryDirectory() as d:
        mod = load_app(Path(d))
        mod.app.testing = True
        with mod.db() as con:
            mid = con.execute("INSERT INTO medicines(name) VALUES('Test')").lastrowid
            lid = con.execute("INSERT INTO locations(code) VALUES('A')").lastrowid
            pid = con.execute('INSERT INTO packages(medicine_id,location_id) VALUES(?,?)',(mid,lid)).lastrowid
        client=mod.app.test_client()
        for url in ('/', '/settings',f'/medicines/{mid}',f'/medicines/{mid}/edit',f'/packages/{pid}'):
            r=client.get(url)
            assert r.status_code == 200, (url,r.status_code,r.data[:400])
