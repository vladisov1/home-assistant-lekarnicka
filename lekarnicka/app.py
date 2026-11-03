import io
import csv
import zipfile
from openpyxl import load_workbook, Workbook
import base64
import shutil
import uuid
import re
from pathlib import Path
from werkzeug.utils import secure_filename
import json
import os
import sqlite3
import calendar
import secrets
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

import qrcode
from consumption import apply_consumption
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for, send_file, Response
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

DB = os.environ.get('LEKARNICKA_DB', '/data/inventory.db')
OPTIONS = '/data/options.json'
app = Flask(__name__)

# Single source of truth for the displayed release version.
APP_VERSION = '0.4.7-rc3'
APP_VERSION_LABEL = 'v0.4.7 RC3'

# Home Assistant Supervisor ingress proxy. Trust its ingress headers only when
# the request originates from the documented internal Supervisor address.
INGRESS_SUPERVISOR_IP = '172.30.32.2'


class IngressPathMiddleware:
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def __call__(self, environ, start_response):
        if environ.get('REMOTE_ADDR') == INGRESS_SUPERVISOR_IP:
            prefix = environ.get('HTTP_X_INGRESS_PATH', '').rstrip('/')
            if prefix.startswith('/api/hassio_ingress/') and not any(
                c in prefix for c in ('\\', '?', '#', '\r', '\n')
            ):
                environ['SCRIPT_NAME'] = prefix
        return self.wrapped(environ, start_response)


app.wsgi_app = IngressPathMiddleware(app.wsgi_app)


def is_ingress_request():
    return request.remote_addr == INGRESS_SUPERVISOR_IP and bool(
        request.headers.get('X-Ingress-Path', '').startswith('/api/hassio_ingress/')
    )

os.makedirs(os.path.dirname(DB), exist_ok=True)
secret_path = os.path.join(os.path.dirname(DB), '.session_secret')
if not os.path.exists(secret_path):
    with open(secret_path, 'w') as f:
        f.write(secrets.token_hex(32))
app.secret_key = open(secret_path).read().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')


def options():
    try:
        return json.load(open(OPTIONS)) if os.path.isfile(OPTIONS) else {}
    except (OSError, ValueError):
        return {}

def password():
    if os.path.isfile(OPTIONS):
        try:
            return json.load(open(OPTIONS)).get('app_password', '')
        except (OSError, ValueError):
            pass
    return os.environ.get('LEKARNICKA_PASSWORD', '')


def db():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=15000')
    return con


def init_db():
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS medicines (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '', ean TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS locations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS shopping_items (
          medicine_id INTEGER PRIMARY KEY REFERENCES medicines(id) ON DELETE CASCADE,
          item_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS packages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
          location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
          expiry TEXT, opened_at TEXT, notes TEXT NOT NULL DEFAULT ''
        );
        ''')
        columns = {r['name'] for r in con.execute('PRAGMA table_info(packages)')}
        for name, sql in [('is_opened','INTEGER NOT NULL DEFAULT 0'),('discarded_at','TEXT'),('import_key','TEXT')]:
            if name not in columns:
                con.execute(f'ALTER TABLE packages ADD COLUMN {name} {sql}')
        con.execute('UPDATE packages SET is_opened=1 WHERE opened_at IS NOT NULL AND is_opened=0')
        con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_import_key ON packages(import_key) WHERE import_key IS NOT NULL')
        con.execute('CREATE INDEX IF NOT EXISTS idx_packages_active ON packages(discarded_at,medicine_id,location_id)')
        shopping_columns = {r['name'] for r in con.execute('PRAGMA table_info(shopping_items)')}
        if 'quantity' not in shopping_columns:
            con.execute('ALTER TABLE shopping_items ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1')
        medcols = {r['name'] for r in con.execute('PRAGMA table_info(medicines)')}
        for field in ('ean','dosage_form','active_ingredient','manufacturer','sukl_code','atc','description'):
            if field not in medcols:
                con.execute(f"ALTER TABLE medicines ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
        for field, definition in [
            ('registered_name', "TEXT NOT NULL DEFAULT ''"),
            ('name_suffix', "TEXT NOT NULL DEFAULT ''"),
            ('package_size', "TEXT NOT NULL DEFAULT ''"),
            ('registration_number', "TEXT NOT NULL DEFAULT ''"),
            ('dispensing', "TEXT NOT NULL DEFAULT ''"),
            ('registration_status', "TEXT NOT NULL DEFAULT ''"),
            ('stock_alert_enabled', 'INTEGER NOT NULL DEFAULT 0'),
            ('stock_alert_mode', "TEXT NOT NULL DEFAULT 'packages'"),
            ('stock_alert_threshold', 'INTEGER NOT NULL DEFAULT 1')]:
            if field not in medcols:
                con.execute(f'ALTER TABLE medicines ADD COLUMN {field} {definition}')
        for field, definition in [
            ('batch', "TEXT NOT NULL DEFAULT ''"),
            ('initial_quantity', 'INTEGER'),
            ('remaining_quantity', 'INTEGER'),
            ('quantity_unit', "TEXT NOT NULL DEFAULT ''"),
            ('usage_schedule', "TEXT NOT NULL DEFAULT ''"),
            ('usage_instructions', "TEXT NOT NULL DEFAULT '[]'"),
            ('usage_custom', "TEXT NOT NULL DEFAULT ''")]:
            if field not in columns:
                con.execute(f'ALTER TABLE packages ADD COLUMN {field} {definition}')
        con.execute('CREATE INDEX IF NOT EXISTS idx_medicines_sukl ON medicines(sukl_code)')
        con.execute("""CREATE TABLE IF NOT EXISTS app_preferences (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS sukl_catalog (
            sukl_code TEXT PRIMARY KEY, registered_name TEXT NOT NULL,
            name_suffix TEXT NOT NULL DEFAULT '', active_ingredient TEXT NOT NULL DEFAULT '',
            atc TEXT NOT NULL DEFAULT '', dosage_form TEXT NOT NULL DEFAULT '',
            manufacturer TEXT NOT NULL DEFAULT '', registration_number TEXT NOT NULL DEFAULT '',
            dispensing TEXT NOT NULL DEFAULT '', registration_status TEXT NOT NULL DEFAULT '')""")
        con.execute("""CREATE TABLE IF NOT EXISTS sukl_catalog_meta (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        con.execute('CREATE INDEX IF NOT EXISTS idx_medicines_ean ON medicines(ean)')
        # v0.4.7: immutable public package number and append-only quantity movements.
        package_cols = {r['name'] for r in con.execute('PRAGMA table_info(packages)')}
        if 'short_id' not in package_cols:
            con.execute('ALTER TABLE packages ADD COLUMN short_id INTEGER')
        con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_packages_short_id ON packages(short_id)')
        con.execute('''CREATE TABLE IF NOT EXISTS package_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE RESTRICT,
            medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
            occurred_at TEXT NOT NULL,
            delta INTEGER NOT NULL CHECK(delta != 0),
            balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
            reason TEXT NOT NULL DEFAULT 'manual'
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_movement_medicine_date ON package_movements(medicine_id,occurred_at DESC,id DESC)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_movement_package_date ON package_movements(package_id,occurred_at DESC,id DESC)')
        # Existing package IDs are unique AUTOINCREMENT integers; preserve old QR identity
        # while assigning the permanent short_id to all pre-existing packages.
        con.execute('UPDATE packages SET short_id=id WHERE short_id IS NULL')
        con.execute('''CREATE TRIGGER IF NOT EXISTS trg_package_short_id AFTER INSERT ON packages WHEN NEW.short_id IS NULL BEGIN UPDATE packages SET short_id=NEW.id WHERE id=NEW.id; END''')
        # AUTOINCREMENT IDs are never reused.

init_db()


def package_code(short_id):
    return f'BAL-{int(short_id):06d}'


def quantity_movement(con, package_id, delta, reason='quick'):
    """Caller owns an IMMEDIATE transaction; never silently change unknown stock."""
    p = con.execute('SELECT * FROM packages WHERE id=?', (package_id,)).fetchone()
    if not p or p['discarded_at'] is not None:
        raise ValueError('Balení není aktivní.')
    initial, remaining = p['initial_quantity'], p['remaining_quantity']
    if initial is None or remaining is None:
        raise ValueError('U tohoto balení není evidován počet jednotek.')
    if not isinstance(delta, int) or delta == 0 or remaining + delta < 0 or remaining + delta > initial:
        raise ValueError('Počet překračuje dostupné množství nebo původní kapacitu.')
    new = remaining + delta
    now = datetime.now().isoformat(timespec='microseconds')
    con.execute('''UPDATE packages SET remaining_quantity=?,is_opened=CASE WHEN ? < 0 THEN 1 ELSE is_opened END,
        opened_at=CASE WHEN ? < 0 THEN COALESCE(opened_at,?) ELSE opened_at END
        WHERE id=?''', (new,delta,delta,now,package_id))
    con.execute('INSERT INTO package_movements(package_id,medicine_id,occurred_at,delta,balance_after,reason) VALUES(?,?,?,?,?,?)',
                (package_id,p['medicine_id'],now,delta,new,reason))
    return new


def preference(key, default='0'):
    with db() as con:
        r = con.execute('SELECT value FROM app_preferences WHERE key=?', (key,)).fetchone()
        return r['value'] if r else default


def valid_sukl(code):
    return not code or bool(re.fullmatch(r'\d{7}', code))


def stock_status(con, mid):
    med = con.execute('SELECT * FROM medicines WHERE id=?', (mid,)).fetchone()
    if not med or not med['stock_alert_enabled']:
        return None
    packs = con.execute('SELECT remaining_quantity,initial_quantity,quantity_unit FROM packages WHERE medicine_id=? AND discarded_at IS NULL', (mid,)).fetchall()
    mode = med['stock_alert_mode']
    if mode == 'units':
        if any(p['remaining_quantity'] is None for p in packs):
            return {'unknown': True, 'low': False, 'amount': None, 'mode': mode}
        units = {p['quantity_unit'] for p in packs}
        if len(units) != 1 or not units.issubset({'tablety','kapsle','sáčky','čípky','kusy'}):
            return {'unknown': True, 'low': False, 'amount': None, 'mode': mode}
        amount = sum(p['remaining_quantity'] for p in packs)
    else:
        amount = len(packs)
    return {'unknown': False, 'low': amount <= med['stock_alert_threshold'], 'amount': amount, 'mode': mode}


def protected(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not password() or is_ingress_request():
            return f(*args, **kwargs)
        if not session.get('authenticated'):
            return redirect(url_for('login', next=request.full_path.rstrip('?')))
        return f(*args, **kwargs)
    return inner


def csrf():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(24)
    return session['csrf']

@app.context_processor
def globals_():
    with db() as con:
        cart_count = con.execute('SELECT COUNT(*) FROM shopping_items').fetchone()[0]
    return {'csrf_token': csrf, 'today': date.today(), 'location_context': request.args.get('location_id', type=int), 'password_enabled': bool(password()), 'cart_count': cart_count, 'package_code': package_code, 'app_version_label': APP_VERSION_LABEL}

@app.before_request
def check_csrf():
    if request.method == 'POST':
        if not secrets.compare_digest(request.form.get('csrf', ''), session.get('csrf', 'not-set')):
            abort(400, 'Neplatný bezpečnostní token formuláře.')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not password() or is_ingress_request():
        return redirect(url_for('index'))
    if request.method == 'POST':
        if secrets.compare_digest(request.form.get('password', ''), password()):
            session.clear()
            session['authenticated'] = True
            csrf()
            nxt = request.form.get('next', '/')
            if not nxt.startswith('/') or nxt.startswith('//'):
                nxt = '/'
            return redirect(nxt)
        flash('Nesprávné heslo.', 'error')
    return render_template('login.html', next=request.args.get('next', '/'))

@app.post('/logout')
@protected
def logout():
    session.clear()
    return redirect(url_for('login'))


def expiry_state(exp):
    if not exp:
        return 'Neznámá expirace', 'unknown'
    try:
        y, m = map(int, exp.split('-'))
        d = date(y, m, calendar.monthrange(y, m)[1])
    except (ValueError, TypeError):
        return 'Neplatná expirace', 'expired'
    remaining = (d - date.today()).days
    if remaining < 0:
        return 'Po expiraci', 'expired'
    if remaining <= 7:
        return 'Brzy expiruje', 'soon'
    return 'V pořádku', 'ok'


def pretty_date(value):
    if not value:
        return 'Neuvedeno'
    try:
        return datetime.fromisoformat(value).strftime('%d. %m. %Y')
    except (ValueError, TypeError):
        return value

def pretty_exp(exp):
    if not exp:
        return 'Neuvedena'
    try:
        return datetime.strptime(exp, '%Y-%m').strftime('%m/%Y')
    except ValueError:
        return exp

app.jinja_env.globals.update(expiry_state=expiry_state, pretty_exp=pretty_exp, pretty_date=pretty_date)


def get_location(con, location_id):
    if location_id is None:
        return None
    loc = con.execute('SELECT * FROM locations WHERE id=?', (location_id,)).fetchone()
    if not loc:
        abort(404)
    return loc

@app.get('/')
@protected
def index():
    location_id = request.args.get('location_id', type=int)
    search = request.args.get('q', '').strip()
    selected_id = request.args.get('selected', type=int)
    with db() as con:
        loc = get_location(con, location_id)
        medicines = con.execute('SELECT * FROM medicines WHERE name LIKE ? OR ean LIKE ? OR active_ingredient LIKE ? OR sukl_code LIKE ? OR CAST(id AS TEXT)=? ORDER BY name COLLATE NOCASE', tuple(['%' + search + '%']*4 + [search])).fetchall()
        rows = []
        for m in medicines:
            packages = con.execute('SELECT * FROM packages WHERE medicine_id=? AND discarded_at IS NULL' + (' AND location_id=?' if loc else ''), (m['id'], location_id) if loc else (m['id'],)).fetchall()
            if loc and not packages:
                continue
            states = [expiry_state(p['expiry'])[1] for p in packages]
            box_counts = con.execute('SELECT l.code, COUNT(*) AS count FROM packages p JOIN locations l ON l.id=p.location_id WHERE p.medicine_id=? AND p.discarded_at IS NULL GROUP BY l.id ORDER BY l.code', (m['id'],)).fetchall()
            rows.append(dict(m=m, count=len(packages), usable=states.count('ok') + states.count('soon'), expired=states.count('expired'), soon=states.count('soon'), unknown=states.count('unknown'), box_counts=box_counts))
    with db() as con:
        shopping = {r['medicine_id'] for r in con.execute('SELECT medicine_id FROM shopping_items')}
    selected = None
    if selected_id:
        with db() as con:
            medicine = con.execute('SELECT * FROM medicines WHERE id=?', (selected_id,)).fetchone()
            if medicine and any(r['m']['id'] == selected_id for r in rows):
                packages = con.execute('SELECT p.*,l.code FROM packages p JOIN locations l ON l.id=p.location_id WHERE p.medicine_id=? AND p.discarded_at IS NULL ORDER BY p.expiry,p.id', (selected_id,)).fetchall()
                selected = {'medicine': medicine, 'packages': packages}
    show_movements = bool(selected and request.args.get('movements') == '1')
    movement_rows = []
    if show_movements:
        kind = request.args.get('kind','all')
        day = request.args.get('day','').strip()
        amount = request.args.get('amount',type=int)
        pack_id = request.args.get('package',type=int)
        conditions = ['pm.medicine_id=?']; args = [selected['medicine']['id']]
        if kind == 'out': conditions.append('pm.delta<0')
        elif kind == 'in': conditions.append('pm.delta>0')
        if day and re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
            conditions.append('substr(pm.occurred_at,1,10)=?');args.append(day)
        if amount and amount>0: conditions.append('ABS(pm.delta)=?');args.append(amount)
        if pack_id: conditions.append('pm.package_id=?');args.append(pack_id)
        with db() as con:
            movement_rows=con.execute('SELECT pm.*,p.short_id,l.code FROM package_movements pm JOIN packages p ON p.id=pm.package_id JOIN locations l ON l.id=p.location_id WHERE '+' AND '.join(conditions)+' ORDER BY pm.occurred_at DESC,pm.id DESC LIMIT 500',args).fetchall()
    return render_template('index.html', rows=rows, loc=loc, search=search, shopping=shopping, selected=selected, show_movements=show_movements, movement_rows=movement_rows)




@app.get('/expirace')
@protected
def expirations():
    with db() as con:
        items = con.execute('SELECT p.*,m.name,l.code FROM packages p JOIN medicines m ON m.id=p.medicine_id JOIN locations l ON l.id=p.location_id WHERE p.discarded_at IS NULL AND p.expiry IS NOT NULL ORDER BY p.expiry,p.id').fetchall()
    groups={'expired':[], 'week':[], 'month':[]}
    for p in items:
        try:
            y,m=map(int,p['expiry'].split('-'))
            remaining=(date(y,m,calendar.monthrange(y,m)[1])-date.today()).days
        except (ValueError,TypeError):
            continue
        group='expired' if remaining<0 else 'week' if remaining<=7 else 'month' if remaining<=30 else None
        if group:
            groups[group].append({'p':p,'days':remaining})
    return render_template('expirations.html',groups=groups)

@app.get('/shopping')
@protected
def shopping_cart():
    with db() as con:
        rows = con.execute('SELECT s.medicine_id, s.item_name, s.quantity FROM shopping_items s ORDER BY s.item_name COLLATE NOCASE').fetchall()
    return render_template('shopping.html', rows=rows)


def ha_todo(action, item):
    """Explicit synchronization only; never clear or replace the HA list."""
    cfg = options()
    token = cfg.get('ha_token', '').strip() or os.environ.get('SUPERVISOR_TOKEN', '')
    entity = cfg.get('todo_entity', 'todo.leky').strip()
    if not token or not entity.startswith('todo.'):
        raise ValueError('Zkontrolujte přístup k HA API a nastavení todo_entity.')
    endpoint = 'http://supervisor/core/api/services/todo/' + action
    payload = {'entity_id': entity, 'item': item}
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode('utf-8', errors='replace')
        raise ValueError('Home Assistant vrátil chybu ' + str(exc.code) + ': ' + detail) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError('Nepodařilo se spojit s Home Assistant API.') from exc


def ha_todo_items():
    """Read current HA items to avoid duplicates; do not alter existing entries."""
    cfg = options()
    token = cfg.get('ha_token', '').strip() or os.environ.get('SUPERVISOR_TOKEN', '')
    entity = cfg.get('todo_entity', 'todo.leky').strip()
    if not token or not entity.startswith('todo.'):
        raise ValueError('Není nastaven přístup k seznamu Home Assistantu.')
    state_url = 'http://supervisor/core/api/states/' + entity
    state_req = urllib.request.Request(state_url, headers={'Authorization':'Bearer '+token})
    try:
        with urllib.request.urlopen(state_req, timeout=8) as response:
            state = json.load(response)
        if not isinstance(state, dict) or state.get('entity_id') != entity:
            raise ValueError('Vybraná entita nákupního seznamu není platná.')
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError('Seznam '+entity+' v Home Assistantu neexistuje. V Nastavení → Zařízení a služby → Integrace přidejte Místní seznam úkolů s názvem Léky - nákupní seznam a nastavte jeho skutečné ID entity v konfiguraci doplňku. Ikonu mdi:cart lze upravit v sekci Entity.') from exc
        raise ValueError('Nelze ověřit seznam Home Assistantu (HTTP '+str(exc.code)+').') from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError('Nelze ověřit existenci seznamu Home Assistantu.') from exc
    endpoint = 'http://supervisor/core/api/services/todo/get_items?return_response'
    payload = json.dumps({'entity_id': entity}).encode('utf-8')
    req = urllib.request.Request(endpoint, data=payload, headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode('utf-8', errors='replace')
        raise ValueError('Nelze načíst seznam Home Assistantu (' + str(exc.code) + '): ' + detail) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ValueError('Nepodařilo se načíst položky seznamu Home Assistantu.') from exc
    # HA service calls with ?return_response normally wrap the data in
    # service_response -> entity_id -> items. Reject unknown structures:
    # treating them as an empty list could silently create duplicates.
    if isinstance(result, dict) and 'service_response' in result:
        result = result['service_response']
    if isinstance(result, dict) and entity in result:
        result = result[entity]
    if isinstance(result, dict) and 'items' in result:
        result = result['items']
    if not isinstance(result, list):
        raise ValueError('Home Assistant vrátil neočekávaný formát seznamu; nic nebylo přidáno.')
    return {str(i.get('summary', '')).strip().casefold() for i in result if isinstance(i, dict)}


@app.post('/medicines/<int:mid>/shopping')
@protected
def medicine_shopping(mid):
    loc_id = request.form.get('location_id', type=int)
    with db() as con:
        m = con.execute('SELECT * FROM medicines WHERE id=?', (mid,)).fetchone()
        if not m:
            abort(404)
        existing = con.execute('SELECT 1 FROM shopping_items WHERE medicine_id=?', (mid,)).fetchone()
        if existing:
            con.execute('DELETE FROM shopping_items WHERE medicine_id=?', (mid,))
            flash('Lék odebrán z místního košíku. Seznam Home Assistantu nebyl změněn.', 'ok')
        else:
            con.execute('INSERT INTO shopping_items(medicine_id,item_name,quantity) VALUES(?,?,1)', (mid, m['name']))
            flash('Lék přidán do místního košíku.', 'ok')
    return redirect(url_for('index', location_id=loc_id) if loc_id else url_for('index'))


@app.post('/shopping/<int:mid>/quantity')
@protected
def shopping_quantity(mid):
    try:
        quantity = int(request.form.get('quantity', '1'))
    except ValueError:
        quantity = 0
    if not 1 <= quantity <= 99:
        flash('Množství musí být od 1 do 99.', 'error')
    else:
        with db() as con:
            con.execute('UPDATE shopping_items SET quantity=? WHERE medicine_id=?', (quantity, mid))
        flash('Množství bylo uloženo.', 'ok')
    return redirect(url_for('shopping_cart'))


@app.post('/shopping/sync')
@protected
def shopping_sync():
    with db() as con:
        rows = con.execute('SELECT medicine_id,item_name,quantity FROM shopping_items ORDER BY item_name').fetchall()
    added = 0
    processed = 0
    errors = []
    try:
        existing = ha_todo_items()
        for r in rows:
            name = r['item_name'] + (f" ({r['quantity']} ks)" if r['quantity'] > 1 else '')
            try:
                if name.casefold() not in existing:
                    ha_todo('add_item', name)
                    # A successful HTTP response alone does not prove the
                    # item was persisted. Verify before removing local data.
                    confirmed = ha_todo_items()
                    if name.casefold() not in confirmed:
                        raise ValueError('Home Assistant nepotvrdil uložení položky; položka zůstává v košíku.')
                    existing = confirmed
                    added += 1
                # Existing entry is already confirmed in HA; remove only this
                # unchanged local cart row, never a newly edited row.
                with db() as con:
                    con.execute('DELETE FROM shopping_items WHERE medicine_id=? AND item_name=? AND quantity=?',
                                (r['medicine_id'], r['item_name'], r['quantity']))
                processed += 1
            except ValueError as exc:
                errors.append(f"{name}: {exc}")
        if errors:
            flash(f'Převedeno {processed} položek; zbývající zůstaly v košíku. ' + '; '.join(errors)[:350], 'error')
        else:
            flash(f'Převedeno {processed} položek, nově přidáno {added}. Položky v Home Assistantu zůstaly zachovány.', 'ok')
    except ValueError as exc:
        flash(str(exc) + ' Místní košík zůstal zachován.', 'error')
    return redirect(url_for('shopping_cart'))

def save_medicine_extras(con, mid, form):
    fields = ('registered_name','name_suffix','package_size','registration_number','dispensing','registration_status')
    values = [form.get(k,'').strip() for k in fields]
    enabled = int(form.get('stock_alert_enabled') == '1')
    mode = form.get('stock_alert_mode','packages')
    if mode not in ('packages','units'):
        mode = 'packages'
    try:
        threshold = int(form.get('stock_alert_threshold','1'))
    except ValueError:
        threshold = 1
    threshold = min(100000, max(0, threshold))
    con.execute("""UPDATE medicines SET registered_name=?,name_suffix=?,package_size=?,
        registration_number=?,dispensing=?,registration_status=?,stock_alert_enabled=?,
        stock_alert_mode=?,stock_alert_threshold=? WHERE id=?""",
        (*values,enabled,mode,threshold,mid))


@app.route('/medicines/new', methods=['GET', 'POST'])
@protected
def medicine_new():
    loc_id = request.values.get('location_id', type=int)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not valid_sukl(request.form.get('sukl_code','').strip()):
            flash('Kód SÚKL musí obsahovat přesně sedm číslic.', 'error')
        elif not name:
            flash('Zadejte název léku.', 'error')
        else:
            with db() as con:
                cur = con.execute('INSERT INTO medicines(name,ean,notes,dosage_form,active_ingredient,manufacturer,sukl_code,atc,description) VALUES(?,?,?,?,?,?,?,?,?)', (name, *(request.form.get(k,'').strip() for k in ('ean','notes','dosage_form','active_ingredient','manufacturer','sukl_code','atc','description'))))
                mid = cur.lastrowid
                save_medicine_extras(con, mid, request.form)
            return redirect(url_for('medicine_detail', mid=mid, location_id=loc_id) if loc_id else url_for('medicine_detail', mid=mid))
    return render_template('medicine_form.html', m=None, loc_id=loc_id)

@app.route('/medicines/<int:mid>/edit', methods=['GET', 'POST'])
@protected
def medicine_edit(mid):
    loc_id = request.values.get('location_id', type=int)
    if loc_id:
        abort(403, 'Katalog léků lze upravovat jen z hlavního přehledu.')
    with db() as con:
        m = con.execute('SELECT * FROM medicines WHERE id=?', (mid,)).fetchone()
        if not m:
            abort(404)
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if name and not valid_sukl(request.form.get('sukl_code','').strip()):
                flash('Kód SÚKL musí obsahovat přesně sedm číslic.', 'error')
            elif name:
                con.execute('UPDATE medicines SET name=?,ean=?,notes=?,dosage_form=?,active_ingredient=?,manufacturer=?,sukl_code=?,atc=?,description=? WHERE id=?', (name, *(request.form.get(k,'').strip() for k in ('ean','notes','dosage_form','active_ingredient','manufacturer','sukl_code','atc','description')), mid))
                save_medicine_extras(con, mid, request.form)
                return redirect(url_for('index', selected=mid))
            flash('Zadejte název léku nebo opravte kód SÚKL.', 'error')
    return render_template('medicine_form.html', m=m, loc_id=loc_id)

@app.post('/medicines/<int:mid>/delete')
@protected
def medicine_delete(mid):
    if request.form.get('location_id'):
        abort(403)
    with db() as con:
        if con.execute('SELECT 1 FROM packages WHERE medicine_id=? LIMIT 1', (mid,)).fetchone():
            flash('Lék nelze smazat, dokud má evidovaná balení.', 'error')
            return redirect(url_for('medicine_detail', mid=mid))
        con.execute('DELETE FROM medicines WHERE id=?', (mid,))
    flash('Lék byl odstraněn.', 'ok')
    return redirect(url_for('index'))

@app.get('/medicines/<int:mid>')
@protected
def medicine_detail(mid):
    loc_id = request.args.get('location_id', type=int)
    with db() as con:
        m = con.execute('SELECT * FROM medicines WHERE id=?', (mid,)).fetchone()
        if not m:
            abort(404)
        loc = get_location(con, loc_id)
        packages = con.execute('SELECT p.*,l.code FROM packages p JOIN locations l ON l.id=p.location_id WHERE p.medicine_id=? AND p.discarded_at IS NULL', (mid,)).fetchall()
    packages = sorted(packages, key=lambda p: (0 if expiry_state(p['expiry'])[1] == 'expired' else 1, p['expiry'] or '9999', p['id']))
    active = [p for p in packages if not loc or p['location_id'] == loc_id]
    other = [p for p in packages if loc and p['location_id'] != loc_id]
    with db() as con:
        stock = stock_status(con, mid)
    with db() as con:
        in_cart = bool(con.execute('SELECT 1 FROM shopping_items WHERE medicine_id=?',(mid,)).fetchone())
    tab = request.args.get('tab', 'udaje')
    if tab not in ('udaje', 'dokumenty', 'baleni', 'poznamky'):
        tab = 'udaje'
    return render_template('medicine_detail.html', m=m, loc=loc, active=active, other=other, stock=stock, in_cart=in_cart, tab=tab)

@app.route('/medicines/<int:mid>/packages/new', methods=['GET', 'POST'])
@protected
def package_new(mid):
    loc_id = request.values.get('location_id', type=int)
    key = f'pending_packages_{mid}_{loc_id or "all"}'
    with db() as con:
        m = con.execute('SELECT * FROM medicines WHERE id=?', (mid,)).fetchone()
        if not m:
            abort(404)
        locations = con.execute('SELECT * FROM locations ORDER BY code').fetchall()
    pending = session.get(key, [])
    if request.method == 'POST':
        action = request.form.get('action', 'add')
        if action == 'add':
            chosen = loc_id or request.form.get('chosen_location', type=int)
            if not any(l['id'] == chosen for l in locations):
                flash('Vyberte platnou úložnou krabici.', 'error')
            elif len(pending) >= 100:
                flash('Nejvýše 100 balení v jedné relaci.', 'error')
            else:
                try:
                    expiry = None if request.form.get('no_expiry') == '1' else parse_expiry(
                        request.form.get('month', '').strip() + '/' + request.form.get('year', '').strip())
                    if not expiry and request.form.get('no_expiry') != '1':
                        raise ValueError('Zadejte expiraci nebo zvolte bez expirace.')
                    pending.append({'expiry': expiry, 'location_id': chosen})
                    session[key] = pending
                    session.modified = True
                    flash('Balení připraveno v seznamu. Zatím nebylo uloženo do evidence.', 'ok')
                except ValueError as exc:
                    flash(str(exc), 'error')
        elif action == 'remove':
            index = request.form.get('index', type=int)
            if index is not None and 0 <= index < len(pending):
                pending.pop(index)
                session[key] = pending
                session.modified = True
        elif action == 'save':
            if not pending:
                flash('Nejdříve připravte alespoň jedno balení.', 'error')
            else:
                try:
                    with db() as con:
                        for item in pending:
                            if not con.execute('SELECT 1 FROM locations WHERE id=?', (item['location_id'],)).fetchone():
                                raise ValueError('Úložná krabice již neexistuje.')
                        created_ids = []
                        for item in pending:
                            cursor = con.execute('INSERT INTO packages(medicine_id,location_id,expiry) VALUES(?,?,?)',
                                        (mid, item['location_id'], item['expiry']))
                            created_ids.append(cursor.lastrowid)
                    session.pop(key, None)
                    flash(f'Uloženo {len(pending)} fyzických balení.', 'ok')
                    return redirect(url_for('package_created', mid=mid, pids=','.join(map(str,created_ids))))
                except (sqlite3.Error, ValueError) as exc:
                    flash('Balení nebyla uložena: ' + str(exc), 'error')
        return redirect(url_for('package_new', mid=mid, location_id=loc_id) if loc_id else url_for('package_new', mid=mid))
    code_by_id = {l['id']: l['code'] for l in locations}
    return render_template('package_new.html', m=m, locations=locations, loc_id=loc_id,
                           pending=pending, code_by_id=code_by_id)

@app.get('/medicines/<int:mid>/packages/created')
@protected
def package_created(mid):
    ids = [int(x) for x in request.args.get('pids','').split(',') if x.isdigit()][:100]
    with db() as con:
        medicine = con.execute('SELECT * FROM medicines WHERE id=?', (mid,)).fetchone()
        if not medicine:
            abort(404)
        packages = [con.execute('SELECT * FROM packages WHERE id=? AND medicine_id=?', (pid,mid)).fetchone() for pid in ids]
    return render_template('package_created.html', m=medicine, packages=[x for x in packages if x])

@app.route('/p/<int:short_id>', methods=['GET', 'POST'])
@protected
def quick_package(short_id):
    with db() as con:
        source = con.execute('''SELECT p.*,m.name,l.code FROM packages p JOIN medicines m ON m.id=p.medicine_id
            JOIN locations l ON l.id=p.location_id WHERE p.short_id=?''',(short_id,)).fetchone()
        if not source:
            abort(404)
        if source['discarded_at'] is not None:
            return render_template('quick_package.html', source=source, packs=[], movements=[], mode='inactive', error='Balení již není aktivní.')
        mode = request.values.get('mode','choose')
        if mode not in ('choose','take','return','find','inactive'):
            mode='choose'
        error=None
        if request.method=='POST':
            try:
                delta_qty=int(request.form.get('quantity','0'))
                if delta_qty < 1 or delta_qty > 100000:
                    raise ValueError('Zadejte kladný počet kusů.')
                action=request.form.get('action')
                if action not in ('take','return'):
                    raise ValueError('Neplatná operace.')
                if action=='return' and request.form.get('confirm')!='yes':
                    raise ValueError('Vrácení vyžaduje potvrzení cílového balení.')
                target_id = source['id'] if action=='take' else int(request.form.get('target_id','0'))
                if action=='return' and not request.form.get('target_id'):
                    raise ValueError('Vyberte cílové balení.')
                # Reject cross-drug movement and serialize read/modify/write.
                con.execute('BEGIN IMMEDIATE')
                target=con.execute('SELECT * FROM packages WHERE id=? AND medicine_id=?',(target_id,source['medicine_id'])).fetchone()
                if not target:
                    raise ValueError('Cílové balení není stejného léku.')
                new=quantity_movement(con,target_id,-delta_qty if action=='take' else delta_qty, 'qr')
                con.commit()
                return render_template('quick_done.html', source=source, target=target, quantity=delta_qty, action=action, balance=new)
            except (ValueError,TypeError) as exc:
                con.rollback()
                error=str(exc)
                mode='take' if request.form.get('action')=='take' else 'find' if request.form.get('target_id') and str(request.form.get('target_id'))!=str(source['id']) else 'return'
        packs=con.execute('''SELECT p.*,l.code, (SELECT pm.occurred_at FROM package_movements pm
            WHERE pm.package_id=p.id AND pm.delta<0 ORDER BY pm.occurred_at DESC,pm.id DESC LIMIT 1) AS last_take_at,
            (SELECT pm.delta FROM package_movements pm WHERE pm.package_id=p.id AND pm.delta<0
            ORDER BY pm.occurred_at DESC,pm.id DESC LIMIT 1) AS last_take_qty
            FROM packages p JOIN locations l ON l.id=p.location_id
            WHERE p.medicine_id=? AND p.discarded_at IS NULL ORDER BY last_take_at DESC,p.id''',(source['medicine_id'],)).fetchall()
        movements=con.execute('''SELECT pm.*,p.short_id,l.code FROM package_movements pm
            JOIN packages p ON p.id=pm.package_id JOIN locations l ON l.id=p.location_id
            WHERE pm.medicine_id=? ORDER BY pm.occurred_at DESC,pm.id DESC LIMIT 150''',(source['medicine_id'],)).fetchall()
    return render_template('quick_package.html',source=source,packs=packs,movements=movements,mode=mode,error=error)


@app.route('/medicines/<int:mid>/movements',methods=['GET','POST'])
@protected
def medicine_movements(mid):
    with db() as con:
        med=con.execute('SELECT * FROM medicines WHERE id=?',(mid,)).fetchone()
        if not med: abort(404)
        kind=request.args.get('kind','all')
        pack_id=request.args.get('package',type=int)
        day=request.args.get('day','').strip()
        amount=request.args.get('amount',type=int)
        conditions=['pm.medicine_id=?'];args=[mid]
        if kind=='out': conditions.append('pm.delta<0')
        if kind=='in': conditions.append('pm.delta>0')
        if pack_id: conditions.append('pm.package_id=?');args.append(pack_id)
        if day and re.fullmatch(r'\d{4}-\d{2}-\d{2}',day): conditions.append('substr(pm.occurred_at,1,10)=?');args.append(day)
        if amount and amount>0: conditions.append('ABS(pm.delta)=?');args.append(amount)
        moves=con.execute('''SELECT pm.*,p.short_id,l.code FROM package_movements pm
            JOIN packages p ON p.id=pm.package_id JOIN locations l ON l.id=p.location_id
            WHERE '''+' AND '.join(conditions)+' ORDER BY pm.occurred_at DESC,pm.id DESC LIMIT 500',args).fetchall()
        packs=con.execute('SELECT p.*,l.code FROM packages p JOIN locations l ON l.id=p.location_id WHERE p.medicine_id=? ORDER BY p.id',(mid,)).fetchall()
    return redirect(url_for('index',selected=mid,movements=1,kind=kind,package=pack_id,day=day,amount=amount))


@app.route('/packages/<int:pid>', methods=['GET', 'POST'])
@protected
def package_detail(pid):
    loc_id = request.values.get('location_id', type=int)
    with db() as con:
        p = con.execute('SELECT p.*,m.name,l.code FROM packages p JOIN medicines m ON m.id=p.medicine_id JOIN locations l ON l.id=p.location_id WHERE p.id=? AND p.discarded_at IS NULL', (pid,)).fetchone()
        if not p:
            abort(404)
        if loc_id and p['location_id'] != loc_id:
            abort(403, 'Balení není v aktuální krabici.')
        locations = con.execute('SELECT * FROM locations ORDER BY code').fetchall()
        if request.method == 'POST':
            chosen = loc_id if loc_id else request.form.get('chosen_location', type=int)
            # Context mode permits changing the location, but only of an originally in-context package.
            if loc_id:
                chosen = request.form.get('chosen_location', type=int)
            if not chosen or not con.execute('SELECT 1 FROM locations WHERE id=?', (chosen,)).fetchone():
                abort(400)
            expiry = None if request.form.get('no_expiry') == '1' else (request.form.get('expiry') or None)
            if expiry:
                try:
                    expiry = parse_expiry(expiry)
                except ValueError:
                    flash('Neplatná expirace. Zadejte MM/RRRR.', 'error')
                    return redirect(url_for('package_detail', pid=pid, location_id=loc_id) if loc_id else url_for('package_detail', pid=pid))
            opened = request.form.get('is_opened') == '1'
            opened_at = (p['opened_at'] or datetime.now().isoformat(timespec='seconds')) if opened else None
            initial, remaining, unit = p['initial_quantity'], p['remaining_quantity'], p['quantity_unit']
            if preference('detailed_consumption') == '1':
                try:
                    initial, remaining, unit = apply_consumption(
                        initial, remaining, unit,
                        request.form.get('initial_quantity', ''),
                        request.form.get('consume_quantity', '0'),
                        request.form.get('quantity_unit', ''))
                except ValueError as exc:
                    flash(str(exc), 'error')
                    return redirect(url_for('package_detail', pid=pid, location_id=loc_id) if loc_id else url_for('package_detail', pid=pid))
            old_remaining = p['remaining_quantity']
            if remaining is not None and initial is not None and remaining < initial:
                opened = True
                opened_at = opened_at or datetime.now().isoformat(timespec='seconds')
            instructions = [x for x in request.form.getlist('usage_instructions') if x in
                            ('Po jídle','Před jídlem','Před spaním','Zapít vodou','Užívat po dobu 7 dnů')]
            discarded = datetime.now().isoformat(timespec='seconds') if remaining == 0 and initial is not None and initial > 0 else None
            con.execute('''UPDATE packages SET location_id=?,expiry=?,notes=?,is_opened=?,opened_at=?,
                batch=?,initial_quantity=?,remaining_quantity=?,quantity_unit=?,usage_schedule=?,
                usage_instructions=?,usage_custom=?,discarded_at=COALESCE(?,discarded_at)
                WHERE id=?''', (chosen,expiry,request.form.get('notes','').strip(),int(opened),opened_at,
                request.form.get('batch','').strip(),initial,remaining,unit,
                request.form.get('usage_schedule','').strip(),json.dumps(instructions,ensure_ascii=False),
                request.form.get('usage_custom','').strip(),discarded,pid))
            if old_remaining is not None and remaining is not None and remaining != old_remaining:
                con.execute('INSERT INTO package_movements(package_id,medicine_id,occurred_at,delta,balance_after,reason) VALUES(?,?,?,?,?,?)',
                    (pid,p['medicine_id'],datetime.now().isoformat(timespec='microseconds'),remaining-old_remaining,remaining,'editor'))
            if discarded:
                flash('Spotřebované balení bylo automaticky archivováno.', 'ok')
            flash('Balení bylo upraveno.', 'ok')
            return redirect(url_for('index', selected=p['medicine_id'], location_id=loc_id) if loc_id else url_for('index', selected=p['medicine_id']))
    return render_template('package_detail.html', p=p, locations=locations, loc_id=loc_id, detailed=preference('detailed_consumption') == '1', usage_selected=json.loads(p['usage_instructions'] or '[]'))

@app.post('/packages/<int:pid>/open')
@protected
def package_open(pid):
    loc_id = request.form.get('location_id', type=int)
    with db() as con:
        p = con.execute('SELECT * FROM packages WHERE id=? AND discarded_at IS NULL', (pid,)).fetchone()
        if not p:
            abort(404)
        if loc_id and p['location_id'] != loc_id:
            abort(403)
        con.execute('UPDATE packages SET is_opened=1,opened_at=? WHERE id=? AND is_opened=0', (date.today().isoformat(), pid))
    return redirect(url_for('medicine_detail', mid=p['medicine_id'], location_id=loc_id) if loc_id else url_for('medicine_detail', mid=p['medicine_id']))

@app.post('/packages/<int:pid>/delete')
@protected
def package_delete(pid):
    loc_id = request.form.get('location_id', type=int)
    with db() as con:
        p = con.execute('SELECT * FROM packages WHERE id=? AND discarded_at IS NULL', (pid,)).fetchone()
        if not p:
            abort(404)
        if loc_id and p['location_id'] != loc_id:
            abort(403)
        con.execute('UPDATE packages SET discarded_at=? WHERE id=?', (datetime.now().isoformat(timespec='seconds'),pid))
    flash('Balení bylo vyřazeno.', 'ok')
    return redirect(url_for('medicine_detail', mid=p['medicine_id'], location_id=loc_id) if loc_id else url_for('medicine_detail', mid=p['medicine_id']))

@app.route('/locations', methods=['GET', 'POST'])
@protected
def locations():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        if not code:
            flash('Zadejte označení krabice.', 'error')
        else:
            try:
                with db() as con:
                    con.execute('INSERT INTO locations(code,description) VALUES(?,?)', (code, request.form.get('description', '').strip()))
                flash('Krabice byla založena.', 'ok')
            except sqlite3.IntegrityError:
                flash('Takové označení krabice už existuje.', 'error')
        return redirect(url_for('locations'))
    with db() as con:
        rows = con.execute('SELECT l.*,COUNT(p.id) AS count FROM locations l LEFT JOIN packages p ON p.location_id=l.id AND p.discarded_at IS NULL GROUP BY l.id ORDER BY l.code').fetchall()
    return render_template('locations.html', rows=rows)

@app.route('/locations/<int:lid>/edit', methods=['GET', 'POST'])
@protected
def location_edit(lid):
    with db() as con:
        loc = get_location(con, lid)
        if request.method == 'POST':
            code = request.form.get('code', '').strip().upper()
            if not code:
                flash('Zadejte označení.', 'error')
            else:
                try:
                    con.execute('UPDATE locations SET code=?,description=? WHERE id=?', (code, request.form.get('description', '').strip(), lid))
                    return redirect(url_for('locations'))
                except sqlite3.IntegrityError:
                    flash('Označení již existuje.', 'error')
    return render_template('location_edit.html', loc=loc)

@app.post('/locations/<int:lid>/delete')
@protected
def location_delete(lid):
    with db() as con:
        if con.execute('SELECT 1 FROM packages WHERE location_id=? LIMIT 1', (lid,)).fetchone():
            flash('Neprázdnou krabici nelze odstranit.', 'error')
        else:
            con.execute('DELETE FROM locations WHERE id=?', (lid,))
    return redirect(url_for('locations'))

@app.get('/labels/package/<int:pid>')
@protected
def package_label(pid):
    with db() as con:
        p = con.execute('SELECT p.*,m.name,l.code AS location_code FROM packages p JOIN medicines m ON m.id=p.medicine_id LEFT JOIN locations l ON l.id=p.location_id WHERE p.id=? AND p.discarded_at IS NULL', (pid,)).fetchone()
        if not p:
            abort(404)
    target = request.host_url.rstrip('/') + url_for('quick_package', short_id=p['short_id'])
    profiles = {
        'brother54': {'label':'Brother 54 × 17 mm (ověřený PDF tisk)', 'width':54, 'height':17, 'qr':12.50, 'font':7},
        'brother62': {'label':'Brother 62 × 29 mm', 'width':62, 'height':29, 'qr':23, 'font':10},
        'small': {'label':'Univerzální 50 × 25 mm', 'width':50, 'height':25, 'qr':19, 'font':9},
        'a4': {'label':'A4 – arch štítků', 'width':63.5, 'height':38.1, 'qr':24, 'font':10},
        'custom': {'label':'Vlastní rozměr', 'width':54, 'height':17, 'qr':14, 'font':7},
    }
    profile = request.args.get('profile', 'brother54')
    if profile not in profiles:
        profile = 'brother54'
    cfg = dict(profiles[profile])
    if profile == 'custom':
        for key, lo, hi in [('width',25,210), ('height',17,297)]:
            raw = request.args.get(key, '')
            try:
                val = float(raw)
                if not lo <= val <= hi:
                    raise ValueError()
                cfg[key] = round(val, 1)
            except (ValueError, TypeError):
                pass
        cfg['qr'] = min(cfg['height'] - 3, cfg['width'] * .42, 27)
    cfg['qr'] = min(cfg['qr'], cfg['height']-2)
    a4 = profile == 'a4'
    def bounded_int(key, default, low, high):
        try: return max(low, min(high, int(request.args.get(key, default))))
        except (TypeError, ValueError): return default
    def bounded_mm(key, default, low, high):
        try: return max(low, min(high, round(float(request.args.get(key, default)), 1)))
        except (TypeError, ValueError): return default
    sheet = {'cols':bounded_int('cols',3,1,6), 'rows':bounded_int('rows',7,1,15),
             'gap_x':bounded_mm('gap_x',2.5,0,20), 'gap_y':bounded_mm('gap_y',0,0,20),
             'margin_x':bounded_mm('margin_x',7,0,30), 'margin_y':bounded_mm('margin_y',12,0,30)}
    if a4:
        sheet['cols'] = min(sheet['cols'], 6)
        if sheet['cols']*cfg['width']+(sheet['cols']-1)*sheet['gap_x']+2*sheet['margin_x']>210 or sheet['rows']*cfg['height']+(sheet['rows']-1)*sheet['gap_y']+2*sheet['margin_y']>297:
            flash('Rozměry archu přesahují A4; upravte počet řádků, sloupců, mezery nebo okraje.', 'error')
    # Presentation-only options: do not change QR payload or package records.
    show_name = request.args.getlist('name')[-1] == '1' if request.args.getlist('name') else True
    show_expiry = request.args.getlist('expiry')[-1] == '1' if request.args.getlist('expiry') else True
    show_id = request.args.getlist('id')[-1] == '1' if request.args.getlist('id') else True
    show_location = request.args.getlist('location')[-1] == '1' if request.args.getlist('location') else False
    copies_raw = request.args.get('copies', '1')
    try:
        copies = max(1, min(120 if a4 else 12, int(copies_raw)))
    except (TypeError, ValueError):
        copies = 1
    sheet_capacity = sheet['cols'] * sheet['rows'] if a4 else 1
    page_count = (copies + sheet_capacity - 1) // sheet_capacity
    return render_template('label.html', p=p, target=target, profile=profile,
                           profiles=profiles, cfg=cfg, show_name=show_name,
                           show_expiry=show_expiry, show_id=show_id, show_location=show_location, copies=copies, a4=a4, sheet=sheet, sheet_capacity=sheet_capacity, page_count=page_count)

@app.get('/labels/package/<int:pid>/brother.pdf')
@protected
def package_label_brother_pdf(pid):
    """Exact 54x17 mm vector PDF matching the physically verified QR test 1.

    Unlike the HTML/PNG route this draws the 33x33 module matrix directly at
    12.50 mm, x=3 mm, vertically centered. No browser image rescaling.
    """
    with db() as con:
        p = con.execute('SELECT p.*, m.name, l.code AS location_code FROM packages p '
                        'JOIN medicines m ON m.id=p.medicine_id '
                        'LEFT JOIN locations l ON l.id=p.location_id '
                        'WHERE p.id=? AND p.discarded_at IS NULL', (pid,)).fetchone()
        if not p:
            abort(404)
    target = request.host_url.rstrip('/') + url_for('quick_package', short_id=p['short_id'])
    qr_code = qrcode.QRCode(version=4, error_correction=qrcode.constants.ERROR_CORRECT_M,
                            box_size=1, border=0)
    qr_code.add_data(target)
    try:
        qr_code.make(fit=False)
    except qrcode.exceptions.DataOverflowError:
        abort(422, 'Adresa je příliš dlouhá pro ověřený QR profil verze 4. Použijte kratší adresu aplikace.')
    matrix = qr_code.get_matrix()
    if len(matrix) != 33:
        abort(500, 'Neočekávaná QR matice')
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(54*mm, 17*mm), pageCompression=1)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.rect(0, 0, 54*mm, 17*mm, fill=1, stroke=0)
    module = 12.50 * mm / 33
    x0, y0 = 3*mm, (17-12.50)*mm/2
    pdf.setFillColorRGB(0, 0, 0)
    for row, line in enumerate(matrix):
        for col, bit in enumerate(line):
            if bit:
                pdf.rect(x0+col*module, y0+(32-row)*module,
                         module, module, fill=1, stroke=0)
    # Keep all additional print text to the right of the QR; ASCII-safe
    # fallback avoids missing glyphs in the default PDF Helvetica font.
    def ascii_safe(value):
        import unicodedata
        return unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    name = ascii_safe(p['name'])[:38]
    pdf.setFont('Helvetica-Bold', 7.0)
    pdf.drawString(20*mm, 11*mm, name)
    pdf.setFont('Helvetica', 6.0)
    pdf.drawString(20*mm, 8*mm, package_code(p['short_id']))
    pdf.drawString(20*mm, 5*mm, 'Box: '+ascii_safe(p['location_code'] or '-')+'  EXP: '+ascii_safe(p['expiry'] or '-'))
    pdf.showPage()
    pdf.save()
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f'Lekarnicka_{package_code(p["short_id"])}_Brother_DK11204.pdf',
                     max_age=0)


@app.get('/qr')
@protected
def qr():
    target = request.args.get('url', '')
    parsed = urlparse(target)
    if parsed.scheme not in ('http', 'https') or parsed.netloc != request.host:
        abort(400)
    # RC2: Brother QL-700 / DK-11204. QR Model 2, ECC M, version 4,
    # 4 printer dots per module including 4-module quiet zone (41*4=164 px).
    # Use exact raster modules rather than a browser-scaled SVG path.
    # Other label profiles retain automatic version selection.
    brother = request.args.get('profile') == 'brother54'
    qr_code = qrcode.QRCode(version=4 if brother else None,
                            error_correction=qrcode.constants.ERROR_CORRECT_M,
                            box_size=4 if brother else 8, border=4)
    qr_code.add_data(target)
    try:
        qr_code.make(fit=not brother)
    except qrcode.exceptions.DataOverflowError:
        # Long user-defined hostnames may not fit version 4. Preserve a
        # functional code rather than truncate the URL; warn in print UI.
        qr_code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                                box_size=4, border=4)
        qr_code.add_data(target)
        qr_code.make(fit=True)
    image = qr_code.make_image(fill_color='black', back_color='white').convert('1')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png', max_age=0)


BACKUPS = Path(os.path.dirname(DB)) / 'backups'
IMPORTS = Path(os.path.dirname(DB)) / 'imports'
MAX_IMPORT_ROWS = 300

def make_backup(label='manual'):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + label + '.sqlite3')
    source = db()
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return dest

def parse_expiry(raw):
    raw = str(raw or '').strip()
    if not raw:
        return None
    if re.fullmatch(r'(0[1-9]|1[0-2])/\d{4}', raw):
        mm, yyyy = raw.split('/')
        raw = yyyy + '-' + mm
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', raw):
        raise ValueError('Expirace musí být MM/RRRR nebo RRRR-MM.')
    return raw

def normalize_rows(rows):
    result=[]
    if len(rows)>MAX_IMPORT_ROWS:
        raise ValueError('Příliš mnoho balení v jednom importu (max. 300).')
    for idx, r in enumerate(rows,1):
        name = str(r.get('name') or r.get('lek') or r.get('název') or '').strip()
        if not name or len(name)>200:
            raise ValueError(f'Řádek {idx}: neplatný název léku.')
        count=int(r.get('count') or r.get('pocet') or 1)
        if not 1 <= count <= 100:
            raise ValueError(f'Řádek {idx}: počet musí být 1–100.')
        status=str(r.get('status') or r.get('stav') or 'nerozbalene').strip().lower()
        if status in ('otevřené','otevrene','opened','open','ano','1'):
            opened=True
        elif status in ('nerozbalené','nerozbalene','zavrene','zavřené','closed','ne','0'):
            opened=False
        else:
            raise ValueError(f'Řádek {idx}: neznámý stav balení.')
        exp=parse_expiry(r.get('expiry') or r.get('expirace'))
        for unit_index in range(count):
            result.append({'name':name,'expiry':exp,'is_opened':opened,'ean':str(r.get('ean') or '').strip()[:80], 'notes':str(r.get('notes') or r.get('poznamky') or '').strip()[:1000], 'source_index':f"{r.get('source_index', idx-1)}-{unit_index}"})
    if len(result)>MAX_IMPORT_ROWS:
        raise ValueError('Příliš mnoho balení (max. 300).')
    return result

def stage_rows(rows):
    key=uuid.uuid4().hex
    IMPORTS.mkdir(parents=True, exist_ok=True)
    # server-side staging; session cookie holds only random reference
    path=IMPORTS / (key+'.json')
    path.write_text(json.dumps({'created':datetime.now().isoformat(),'rows':normalize_rows(rows)},ensure_ascii=False),encoding='utf8')
    session['import_stage']=key

def staged_rows():
    key=session.get('import_stage','')
    if not re.fullmatch(r'[0-9a-f]{32}',key):
        abort(400)
    path=IMPORTS/(key+'.json')
    if not path.is_file():
        abort(400,'Importní náhled vypršel.')
    payload=json.loads(path.read_text(encoding='utf8'))
    if datetime.fromisoformat(payload['created']) < datetime.now()-timedelta(hours=2):
        abort(400,'Importní náhled vypršel.')
    return key,payload['rows']

@app.get('/settings')
@protected
def settings():
    return render_template('settings.html', detailed=preference('detailed_consumption') == '1')

@app.post('/settings/consumption')
@protected
def save_consumption_setting():
    with db() as con:
        con.execute('INSERT OR REPLACE INTO app_preferences(key,value) VALUES(?,?)',
                    ('detailed_consumption', '1' if request.form.get('enabled') == '1' else '0'))
    flash('Nastavení evidence spotřeby bylo uloženo.', 'ok')
    return redirect(url_for('settings'))



# The source catalogue is kept separate from user-owned medicines and packages.
# Import is opt-in while the upstream DLP CSV schema is being validated.
SUKL_FIELDS = {
    'sukl_code': ('kod_sukl', 'kod_suklu', 'sukl_kod', 'sukl_code', 'kod', 'code'),
    'registered_name': ('nazev', 'nazev_pripravku', 'nazev_lp', 'registered_name'),
    'name_suffix': ('doplnek_nazvu', 'doplnek', 'name_suffix'),
    'active_ingredient': ('leciva_latka', 'ucinna_latka', 'active_ingredient'),
    'atc': ('atc', 'atc_kod'),
    'dosage_form': ('lekova_forma', 'forma', 'dosage_form'),
    'manufacturer': ('drzitel', 'drzitel_registrace', 'manufacturer'),
    'registration_number': ('registracni_cislo', 'reg_cislo', 'registration_number'),
    'dispensing': ('zpusob_vydeje', 'vydej', 'dispensing'),
    'registration_status': ('stav_registrace', 'registration_status'),
}

def sukl_normalize_header(value):
    import unicodedata
    value = unicodedata.normalize('NFKD', str(value).lower())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '_', value).strip('_')

def sukl_parse_csv(raw):
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('CSV překračuje povolenou velikost 32 MB.')
    decoded = None
    for encoding in ('utf-8-sig', 'cp1250'):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if decoded is None:
        raise ValueError('Nepodporované kódování CSV.')
    sample = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=';,\t|')
        delim = dialect.delimiter
    except csv.Error:
        delim = ';'
    reader = csv.DictReader(io.StringIO(decoded), delimiter=delim)
    if not reader.fieldnames:
        raise ValueError('CSV nemá záhlaví.')
    cols = {sukl_normalize_header(h): h for h in reader.fieldnames if h}
    mapping = {field: next((cols[x] for x in aliases if x in cols), None)
               for field, aliases in SUKL_FIELDS.items()}
    if not mapping['sukl_code'] or not mapping['registered_name']:
        raise ValueError('CSV nemá rozpoznané sloupce kódu SÚKL a názvu. Import nebyl proveden.')
    result = {}
    for row in reader:
        code = (row.get(mapping['sukl_code']) or '').strip()
        name = (row.get(mapping['registered_name']) or '').strip()
        if not re.fullmatch(r'\d{7}', code) or not name:
            continue
        result[code] = tuple((row.get(mapping[k]) or '').strip()[:500] if mapping[k] else '' for k in SUKL_FIELDS)
        if len(result) > 100000:
            raise ValueError('Překročen maximální počet záznamů.')
    if not result:
        raise ValueError('Nenalezeny žádné platné záznamy SÚKL.')
    return result

def sukl_read_upload(upload):
    raw = upload.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('Soubor je příliš velký (max. 32 MB).')
    if upload.filename.lower().endswith('.csv'):
        return sukl_parse_csv(raw)
    if not upload.filename.lower().endswith('.zip'):
        raise ValueError('Vyberte ZIP nebo CSV.')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        candidates = [info for info in archive.infolist() if info.filename.lower().endswith('.csv') and not info.is_dir() and info.file_size <= 32 * 1024 * 1024]
        if not candidates:
            raise ValueError('Archiv neobsahuje podporované CSV.')
        # Never extract paths to disk; select CSV by verified header instead.
        for info in candidates[:30]:
            with archive.open(info) as stream:
                payload = stream.read(32 * 1024 * 1024 + 1)
            try:
                return sukl_parse_csv(payload)
            except ValueError:
                continue
    raise ValueError('V ZIP nebylo nalezeno CSV se sloupci SÚKL kód a název.')

@app.route('/settings/sukl', methods=['GET', 'POST'])
@protected
def sukl_settings():
    if request.method == 'POST':
        try:
            upload = request.files.get('catalog_file')
            if not upload or not upload.filename:
                raise ValueError('Vyberte soubor ZIP nebo CSV.')
            records = sukl_read_upload(upload)
            with db() as con:
                con.execute('CREATE TEMP TABLE sukl_stage AS SELECT * FROM sukl_catalog WHERE 0')
                con.executemany('INSERT INTO sukl_stage VALUES (?,?,?,?,?,?,?,?,?,?)', records.values())
                con.execute('DELETE FROM sukl_catalog')
                con.execute('INSERT INTO sukl_catalog SELECT * FROM sukl_stage')
                con.execute('INSERT OR REPLACE INTO sukl_catalog_meta(key,value) VALUES (?,?)', ('updated_at',datetime.now().isoformat(timespec='seconds')))
                con.execute('INSERT OR REPLACE INTO sukl_catalog_meta(key,value) VALUES (?,?)', ('source_filename',secure_filename(upload.filename)))
            flash(f'Načteno {len(records)} záznamů SÚKL. Uživatelská evidence zůstala beze změny.', 'ok')
        except (ValueError, zipfile.BadZipFile, sqlite3.Error) as exc:
            flash(f'Import SÚKL se nezdařil: {exc}', 'error')
        return redirect(url_for('sukl_settings'))
    with db() as con:
        count = con.execute('SELECT COUNT(*) FROM sukl_catalog').fetchone()[0]
        meta = dict(con.execute('SELECT key,value FROM sukl_catalog_meta').fetchall())
    return render_template('sukl_catalog.html', count=count, meta=meta)

@app.route('/import/ean', methods=['GET', 'POST'])
@protected
def import_ean():
    code = (request.form.get('ean') if request.method == 'POST' else request.args.get('ean', '')) or ''
    code = code.strip()
    match = None
    error = None
    if code:
        if not re.fullmatch(r'\d{8}|\d{12,14}', code):
            error = 'Zadejte EAN/GTIN o délce 8, 12, 13 nebo 14 číslic.'
        else:
            with db() as con:
                match = con.execute('SELECT * FROM medicines WHERE ean=? ORDER BY id LIMIT 1', (code,)).fetchone()
    return render_template('ean_import.html', code=code, match=match, error=error)

@app.get('/sukl/search')
@protected
def sukl_search():
    q = request.args.get('q', '').strip()[:100]
    rows = []
    if len(q) >= 2:
        with db() as con:
            rows = con.execute('''SELECT * FROM sukl_catalog WHERE sukl_code = ? OR registered_name LIKE ? ESCAPE '\\'
                                  ORDER BY CASE WHEN sukl_code=? THEN 0 ELSE 1 END, registered_name LIMIT 50''',
                               (q, '%' + q.replace('%','\\%').replace('_','\\_') + '%', q)).fetchall()
    return render_template('sukl_search.html', rows=rows, q=q, mid=request.args.get('mid', type=int))

@app.post('/medicines/<int:mid>/sukl-link')
@protected
def sukl_link(mid):
    code = request.form.get('sukl_code', '').strip()
    with db() as con:
        med = con.execute('SELECT id FROM medicines WHERE id=?', (mid,)).fetchone()
        record = con.execute('SELECT * FROM sukl_catalog WHERE sukl_code=?', (code,)).fetchone()
        if not med or not record:
            abort(404)
        # Preserve the user's original name, notes, EAN and every package.
        con.execute('''UPDATE medicines SET sukl_code=?,registered_name=?,name_suffix=?,
                       active_ingredient=?,atc=?,dosage_form=?,manufacturer=?,
                       registration_number=?,dispensing=?,registration_status=? WHERE id=?''',
                    tuple(record[k] for k in SUKL_FIELDS) + (mid,))
    flash('Oficiální údaje SÚKL byly přiřazeny. Uživatelské údaje a balení zůstaly zachovány.', 'ok')
    return redirect(url_for('medicine_detail', mid=mid))

@app.route('/settings/import',methods=['GET','POST'])
@protected
def import_page():
    with db() as con:
        locations=con.execute('SELECT * FROM locations ORDER BY code').fetchall()
    if request.method=='POST':
        try:
            f=request.files.get('file')
            if not f or not f.filename.lower().endswith(('.csv','.xlsx')):
                raise ValueError('Nahrajte CSV nebo XLSX soubor.')
            raw=f.read(1024*1024+1)
            if len(raw)>1024*1024:
                raise ValueError('Soubor je příliš velký.')
            if f.filename.lower().endswith('.xlsx'):
                book=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
                sheet=book.active
                cells=sheet.iter_rows(values_only=True)
                header=[str(x or '').strip() for x in next(cells)]
                rows=[dict(zip(header,values)) for values in cells if any(v is not None for v in values)]
                book.close()
            else:
                decoded=raw.decode('utf-8-sig')
                sample=decoded[:4096]
                dialect=csv.Sniffer().sniff(sample,delimiters=',;\t')
                rows=list(csv.DictReader(io.StringIO(decoded),dialect=dialect))
            stage_rows(rows)
            return redirect(url_for('import_review'))
        except (ValueError,UnicodeError,csv.Error,TypeError) as e:
            flash('Import: '+str(e),'error')
    return render_template('import.html',locations=locations,ai_enabled=bool(options().get('openai_api_key') or os.environ.get('OPENAI_API_KEY')))

@app.post('/settings/import/ai')
@protected
def ai_import():
    key=(options().get('openai_api_key') or os.environ.get('OPENAI_API_KEY') or '').strip()
    if not key:
        flash('Nejdříve nastavte OpenAI API klíč v konfiguraci doplňku.','error')
        return redirect(url_for('import_page'))
    files=request.files.getlist('photos')
    if not 1<=len(files)<=2:
        flash('Nahrajte 1 až 2 fotografie jednoho balení.','error');return redirect(url_for('import_page'))
    content=[{'type':'text','text':('Rozpoznej léčiva z fotografií. Vrať POUZE JSON objekt s polem rows. '
      'Každý záznam: name (jen obchodní název a síla, bez lékové formy), expiry (YYYY-MM nebo null), '
      'count (počet FYZICKÝCH krabiček, výchozí 1), status (otevrene/nerozbalene), ean (nepovinné), notes (nepovinné). '
      'Počet sáčků, tablet či dávek uvnitř balení NIKDY není počet fyzických krabiček. ' 'U fotografie jedné krabičky vrať jeden záznam s count=1. ' 'Lékovou formu dej do notes, ne do name. Nedomýšlej nečitelné datum ani identitu léku. '
      'Neshody či nejistoty popiš v notes, nevyplňuj odhadnuté hodnoty. '
      'Přiložené nejvýše dvě fotografie zachycují JEDNO fyzické balení (název/EAN a expiraci). Vrať právě jeden řádek. ' 'Pokud je EAN viditelný, přesně jej opiš, neodhaduj; nepředstírej internetové ověření ani externí databázové vyhledání. ' 'Doplňující pokyny: '+request.form.get('prompt','')[:3000])}]
    try:
        for f in files:
            data=f.read(5*1024*1024+1)
            if len(data)>5*1024*1024 or not data:
                raise ValueError('Fotografie musí mít nejvýše 5 MB.')
            if f.mimetype not in ('image/jpeg','image/png','image/webp'):
                raise ValueError('Podporovány jsou JPG, PNG a WEBP.')
            content.append({'type':'image_url','image_url':{'url':'data:'+f.mimetype+';base64,'+base64.b64encode(data).decode()}})
        payload={'model':(options().get('openai_model') or 'gpt-4.1-mini'),'messages':[{'role':'user','content':content}], 'response_format':{'type':'json_object'},'temperature':0}
        req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=90) as response:
            result=json.load(response)
        obj=json.loads(result['choices'][0]['message']['content'])
        # For photo recognition, never expand an AI-guessed count into packages.
        # One photo may show several sides of one box; user can add further packs manually.
        photo_rows = obj['rows']
        if not isinstance(photo_rows, list):
            raise ValueError('AI nevrátila seznam rozpoznaných léků.')
        # AI sometimes emits one row for each sachet/tablet shown on the box.
        # Collapse exact repeated medicine/expiry rows into one physical package.
        unique_rows = []
        seen = set()
        for row in photo_rows:
            row['count'] = 1
            signature = (str(row.get('name', '')).strip().casefold(), str(row.get('expiry') or ''))
            if signature not in seen:
                seen.add(signature)
                unique_rows.append(row)
        # Never turn one photographed box into dozens of packages.
        # Ambiguous multi-object photos require manual addition in the app.
        if len(unique_rows) > len(files):
            unique_rows = unique_rows[:len(files)]
            flash('AI nabídla více různých balení než bylo fotografií. Z bezpečnostních důvodů byl počet omezen; zkontrolujte náhled a případné další balení přidejte ručně.', 'error')
        if not unique_rows:
            raise ValueError('Na fotografiích nebylo rozpoznáno žádné balení.')
        stage_rows(unique_rows[:1])
        return redirect(url_for('import_review'))
    except (ValueError,KeyError,IndexError,TypeError,urllib.error.URLError,TimeoutError,json.JSONDecodeError) as e:
        flash('AI rozpoznání se nezdařilo: '+str(e)[:300],'error')
        return redirect(url_for('import_page'))

@app.route('/settings/import/review',methods=['GET','POST'])
@protected
def import_review():
    key,rows=staged_rows()
    with db() as con:
        locations=con.execute('SELECT * FROM locations ORDER BY code').fetchall()
    if request.method=='POST':
        try:
            lid=int(request.form.get('location_id',''))
            if not any(l['id']==lid for l in locations):
                raise ValueError('Vyberte platnou krabici.')
            if request.form.get('confirm')!='yes':
                raise ValueError('Potvrďte kontrolu importu.')
            # User can correct the recognized fields in the review form.
            corrected=[]
            for i,row in enumerate(rows):
                if request.form.get(f'include_{i}') != 'yes':
                    continue
                corrected.append({'source_index': i, 'name':request.form.get(f'name_{i}',''),'expiry':request.form.get(f'expiry_{i}',''), 'status':request.form.get(f'status_{i}',''), 'ean':row.get('ean',''), 'notes':request.form.get(f'notes_{i}',''), 'count':1})
            corrected=normalize_rows(corrected)
            if not corrected:
                raise ValueError('Vyberte alespoň jedno balení k importu.')
            make_backup('before_import')
            with db() as con:
                for i,row in enumerate(corrected):
                    # Repeating same staged import is idempotent.
                    import_key=f"{key}:{row['source_index']}"
                    if con.execute('SELECT 1 FROM packages WHERE import_key=?',(import_key,)).fetchone():
                        continue
                    m=con.execute('SELECT id FROM medicines WHERE name=? COLLATE NOCASE',(row['name'],)).fetchone()
                    if m:
                        mid=m['id']
                    else:
                        mid=con.execute('INSERT INTO medicines(name,ean) VALUES(?,?)',(row['name'],row['ean'])).lastrowid
                    con.execute('INSERT INTO packages(medicine_id,location_id,expiry,is_opened,notes,import_key) VALUES(?,?,?,?,?,?)',(mid,lid,row['expiry'],int(row['is_opened']),row['notes'],import_key))
            flash(f'Import dokončen: {len(corrected)} položek (opakované záznamy přeskočeny).','ok')
            return redirect(url_for('index',location_id=lid))
        except (ValueError,sqlite3.Error,OSError) as e:
            flash('Import nebyl dokončen: '+str(e),'error')
    return render_template('import_review.html',rows=rows,locations=locations)

@app.get('/settings/export.csv')
@protected
def export_csv():
    out=io.StringIO();writer=csv.writer(out,delimiter=';')
    writer.writerow(['id','name','expiry','status','opened_at','location','ean','notes','discarded_at'])
    with db() as con:
        for p in con.execute('SELECT p.*,m.name,m.ean,l.code FROM packages p JOIN medicines m ON m.id=p.medicine_id JOIN locations l ON l.id=p.location_id ORDER BY p.id'):
            writer.writerow([p['id'],p['name'],p['expiry'] or '', 'otevrene' if p['is_opened'] else 'nerozbalene',p['opened_at'] or '',p['code'],p['ean'],p['notes'],p['discarded_at'] or ''])
    return Response('\ufeff'+out.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=lekarnicka_export.csv'})

@app.get('/settings/export.xlsx')
@protected
def export_xlsx():
    book=Workbook();sheet=book.active;sheet.title='Balení'
    sheet.append(['id','name','expiry','status','opened_at','location','ean','notes','discarded_at'])
    with db() as con:
        for p in con.execute('SELECT p.*,m.name,m.ean,l.code FROM packages p JOIN medicines m ON m.id=p.medicine_id JOIN locations l ON l.id=p.location_id ORDER BY p.id'):
            sheet.append([p['id'],p['name'],p['expiry'] or '', 'otevrene' if p['is_opened'] else 'nerozbalene',p['opened_at'] or '',p['code'],p['ean'],p['notes'],p['discarded_at'] or ''])
    sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
    for col,width in {'A':12,'B':40,'C':14,'D':17,'E':18,'F':16,'G':20,'H':45,'I':22}.items():sheet.column_dimensions[col].width=width
    output=io.BytesIO();book.save(output);output.seek(0)
    return send_file(output,as_attachment=True,download_name='lekarnicka_export.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.get('/settings/import/template.xlsx')
@protected
def import_template():
    book=Workbook();sheet=book.active;sheet.title='Import'
    sheet.append(['name','expiry','status','count','ean','notes'])
    sheet.append(['Paralen 500 mg','06/2028','nerozbalene',2,'','UKÁZKA – před importem smažte'])
    sheet.append(['Paralen 500 mg','06/2028','otevrene',1,'','UKÁZKA – před importem smažte'])
    sheet.freeze_panes='A2'
    for col,width in {'A':40,'B':18,'C':20,'D':12,'E':20,'F':50}.items():sheet.column_dimensions[col].width=width
    output=io.BytesIO();book.save(output);output.seek(0)
    return send_file(output,as_attachment=True,download_name='lekarnicka_import_sablona.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.get('/settings/trash')
@protected
def trash():
    with db() as con:
        rows=con.execute('SELECT p.*,m.name,l.code FROM packages p JOIN medicines m ON m.id=p.medicine_id JOIN locations l ON l.id=p.location_id WHERE p.discarded_at IS NOT NULL ORDER BY p.discarded_at').fetchall()
    return render_template('trash.html',rows=rows,cutoff=datetime.now()-timedelta(days=30))

@app.post('/settings/trash/<int:pid>/restore')
@protected
def restore_package(pid):
    with db() as con:
        con.execute('UPDATE packages SET discarded_at=NULL WHERE id=? AND discarded_at IS NOT NULL',(pid,))
    flash('Balení bylo obnoveno.','ok');return redirect(url_for('trash'))

@app.post('/settings/trash/empty')
@protected
def empty_trash():
    if request.form.get('confirm')!='DELETE':
        flash('Vyprázdnění koše nebylo potvrzeno.','error');return redirect(url_for('trash'))
    try:
        make_backup('before_empty_trash')
        with db() as con:
            n=con.execute('DELETE FROM packages WHERE discarded_at IS NOT NULL').rowcount
        flash(f'Koš byl vyprázdněn ({n} balení). Záloha byla vytvořena.','ok')
    except (sqlite3.Error,OSError) as e:
        flash('Koš nebyl vyprázdněn: '+str(e),'error')
    return redirect(url_for('trash'))

@app.post('/packages/<int:pid>/correct-closed')
@protected
def correct_closed(pid):
    loc_id=request.form.get('location_id',type=int)
    if request.form.get('confirm')!='yes':abort(400)
    with db() as con:
        p=con.execute('SELECT * FROM packages WHERE id=? AND discarded_at IS NULL',(pid,)).fetchone()
        if not p:abort(404)
        if loc_id and p['location_id']!=loc_id:abort(403)
        con.execute('UPDATE packages SET is_opened=0,opened_at=NULL WHERE id=?',(pid,))
    flash('Stav byl opraven na nerozbalené.','ok')
    return redirect(url_for('medicine_detail',mid=p['medicine_id'],location_id=loc_id) if loc_id else url_for('medicine_detail',mid=p['medicine_id']))

@app.get('/settings/database')
@protected
def database_page():
    BACKUPS.mkdir(parents=True,exist_ok=True)
    backups=sorted(BACKUPS.glob('*.sqlite3'),reverse=True)[:30]
    return render_template('database.html',backups=backups)

@app.post('/settings/database/check')
@protected
def check_database():
    with db() as con:
        integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
        fk=con.execute('PRAGMA foreign_key_check').fetchall()
    flash('Integrita: '+integrity+'; chyby vazeb: '+str(len(fk)), 'ok' if integrity=='ok' and not fk else 'error')
    return redirect(url_for('database_page'))

@app.post('/settings/database/backup')
@protected
def backup_database():
    try:
        dest=make_backup()
        flash('Záloha vytvořena: '+dest.name,'ok')
    except (OSError,sqlite3.Error) as e:
        flash('Zálohování selhalo: '+str(e),'error')
    return redirect(url_for('database_page'))

@app.get('/settings/database/download/<filename>')
@protected
def download_backup(filename):
    if not re.fullmatch(r'\d{8}_\d{6}_\d{6}_[a-z_]+\.sqlite3',filename):abort(404)
    path=BACKUPS/filename
    if not path.is_file():abort(404)
    return send_file(path,as_attachment=True,download_name=filename)

@app.post('/settings/database/optimize')
@protected
def optimize_database():
    try:
        make_backup('before_optimize')
        with db() as con:
            con.execute('PRAGMA optimize')
        # VACUUM outside transaction.
        con=db()
        try:con.execute('VACUUM')
        finally:con.close()
        flash('Optimalizace dokončena.','ok')
    except (OSError,sqlite3.Error) as e:
        flash('Optimalizace selhala: '+str(e),'error')
    return redirect(url_for('database_page'))

@app.post('/settings/database/restore')
@protected
def restore_database():
    filename=request.form.get('filename','')
    if request.form.get('confirm')!='RESTORE' or not re.fullmatch(r'\d{8}_\d{6}_\d{6}_[a-z_]+\.sqlite3',filename):abort(400)
    source=BACKUPS/filename
    if not source.is_file():abort(404)
    try:
        with sqlite3.connect(str(source)) as chk:
            if chk.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Poškozená záloha.')
            required={r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'medicines','packages','locations'}.issubset(required):raise ValueError('Neplatná záloha Lékárničky.')
        make_backup('before_restore')
        with sqlite3.connect(str(source)) as backup_source:
            target=db()
            try:backup_source.backup(target)
            finally:target.close()
        init_db()
        flash('Databáze byla obnovena.','ok')
    except (OSError,sqlite3.Error,ValueError) as e:
        flash('Obnova selhala: '+str(e),'error')
    return redirect(url_for('database_page'))

@app.get('/health')
def health():
    return {'status': 'ok'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8099)
