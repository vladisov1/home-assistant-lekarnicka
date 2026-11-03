"""Ingress URL prefix behavior without needing Flask in the build host."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def middleware_class():
    source = (ROOT / 'lekarnicka' / 'app.py').read_text()
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'IngressPathMiddleware')
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    ns = {'INGRESS_SUPERVISOR_IP': '172.30.32.2'}
    exec(compile(module, '<ingress>', 'exec'), ns)
    return ns['IngressPathMiddleware']


def test_ingress_prefix_only_from_supervisor():
    wrapped = middleware_class()(lambda env, start: env['SCRIPT_NAME'])
    good = {'REMOTE_ADDR': '172.30.32.2', 'HTTP_X_INGRESS_PATH': '/api/hassio_ingress/token/'}
    assert wrapped(good, None) == '/api/hassio_ingress/token'
    untrusted = {'REMOTE_ADDR': '192.168.1.12', 'HTTP_X_INGRESS_PATH': '/api/hassio_ingress/token/', 'SCRIPT_NAME': ''}
    assert wrapped(untrusted, None) == ''


def test_ingress_config_non_admin_sidebar_opt_in():
    config = (ROOT / 'lekarnicka' / 'config.yaml').read_text()
    assert 'ingress: true' in config
    assert 'ingress_port: 8099' in config
    assert 'panel_admin: false' in config
    assert 'ingress_panel:' not in config  # Supervisor owns the sidebar toggle
