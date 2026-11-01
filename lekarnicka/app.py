import io
import csv
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
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for, send_file, Response

DB = os.environ.get('LEKARNICKA_DB', '/data/inventory.db')
OPTIONS = '/data/options.json'
app = Flask(__name__)
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
        # AUTOINCREMENT IDs are never reused.

init_db()


def protected(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not password():
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
    return {'csrf_token': csrf, 'today': date.today(), 'location_context': request.args.get('location_id', type=int), 'password_enabled': bool(password()), 'cart_count': cart_count}

@app.before_request
def check_csrf():
    if request.method == 'POST':
        if not secrets.compare_digest(request.form.get('csrf', ''), session.get('csrf', 'not-set')):
            abort(400, 'Neplatný bezpečnostní token formuláře.')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not password():
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
    with db() as con:
        loc = get_location(con, location_id)
        medicines = con.execute('SELECT * FROM medicines WHERE name LIKE ? OR CAST(id AS TEXT)=? ORDER BY name COLLATE NOCASE', ('%' + search + '%', search)).fetchall()
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
    return render_template('index.html', rows=rows, loc=loc, search=search, shopping=shopping)



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
                    existing.add(name.casefold())
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

@app.route('/medicines/new', methods=['GET', 'POST'])
@protected
def medicine_new():
    loc_id = request.values.get('location_id', type=int)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Zadejte název léku.', 'error')
        else:
            with db() as con:
                cur = con.execute('INSERT INTO medicines(name,ean,notes) VALUES(?,?,?)', (name, request.form.get('ean', '').strip(), request.form.get('notes', '').strip()))
                mid = cur.lastrowid
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
            if name:
                con.execute('UPDATE medicines SET name=?,ean=?,notes=? WHERE id=?', (name, request.form.get('ean', '').strip(), request.form.get('notes', '').strip(), mid))
                return redirect(url_for('medicine_detail', mid=mid, location_id=loc_id) if loc_id else url_for('medicine_detail', mid=mid))
            flash('Zadejte název léku.', 'error')
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
    return render_template('medicine_detail.html', m=m, loc=loc, active=active, other=other)

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
                        for item in pending:
                            con.execute('INSERT INTO packages(medicine_id,location_id,expiry) VALUES(?,?,?)',
                                        (mid, item['location_id'], item['expiry']))
                    session.pop(key, None)
                    flash(f'Uloženo {len(pending)} fyzických balení.', 'ok')
                    return redirect(url_for('medicine_detail', mid=mid, location_id=loc_id) if loc_id else url_for('medicine_detail', mid=mid))
                except (sqlite3.Error, ValueError) as exc:
                    flash('Balení nebyla uložena: ' + str(exc), 'error')
        return redirect(url_for('package_new', mid=mid, location_id=loc_id) if loc_id else url_for('package_new', mid=mid))
    code_by_id = {l['id']: l['code'] for l in locations}
    return render_template('package_new.html', m=m, locations=locations, loc_id=loc_id,
                           pending=pending, code_by_id=code_by_id)

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
            con.execute('UPDATE packages SET location_id=?,expiry=?,notes=? WHERE id=?', (chosen, expiry, request.form.get('notes', '').strip(), pid))
            flash('Balení bylo upraveno.', 'ok')
            return redirect(url_for('medicine_detail', mid=p['medicine_id'], location_id=loc_id) if loc_id else url_for('medicine_detail', mid=p['medicine_id']))
    return render_template('package_detail.html', p=p, locations=locations, loc_id=loc_id)

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
        p = con.execute('SELECT p.*,m.name FROM packages p JOIN medicines m ON m.id=p.medicine_id WHERE p.id=? AND p.discarded_at IS NULL', (pid,)).fetchone()
        if not p:
            abort(404)
    target = request.host_url.rstrip('/') + url_for('package_detail', pid=pid)
    return render_template('label.html', p=p, target=target)

@app.get('/qr')
@protected
def qr():
    target = request.args.get('url', '')
    parsed = urlparse(target)
    if parsed.scheme not in ('http', 'https') or parsed.netloc != request.host:
        abort(400)
    image = qrcode.make(target)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png')


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
    return render_template('settings.html')

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
    if not 1<=len(files)<=6:
        flash('Nahrajte 1 až 6 fotografií.','error');return redirect(url_for('import_page'))
    content=[{'type':'text','text':('Rozpoznej léčiva z fotografií. Vrať POUZE JSON objekt s polem rows. '
      'Každý záznam: name (jen obchodní název a síla, bez lékové formy), expiry (YYYY-MM nebo null), '
      'count (počet FYZICKÝCH krabiček, výchozí 1), status (otevrene/nerozbalene), ean (nepovinné), notes (nepovinné). '
      'Počet sáčků, tablet či dávek uvnitř balení NIKDY není počet fyzických krabiček. ' 'U fotografie jedné krabičky vrať jeden záznam s count=1. ' 'Lékovou formu dej do notes, ne do name. Nedomýšlej nečitelné datum ani identitu léku. '
      'Neshody či nejistoty popiš v notes, nevyplňuj odhadnuté hodnoty. '
      'Doplňující pokyny: '+request.form.get('prompt','')[:3000])}]
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
        stage_rows(unique_rows)
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
