"""Offline HA API contract tests using mocked responses; no Flask required."""
import ast
import io
import json
import urllib.error
import urllib.request
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'lekarnicka' / 'app.py'

class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, *args): return json.dumps(self.payload).encode()

class HomeAssistantTodoContractTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text())
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('ha_todo_items', 'ha_todo')]
        self.ns = {'json': json, 'urllib': __import__('urllib'), 'options': lambda: {'todo_entity':'todo.leky','ha_token':'test-token'}, 'os':__import__('os')}
        exec(compile(ast.Module(body=funcs, type_ignores=[]), str(SOURCE), 'exec'), self.ns)

    def test_reads_existing_items_and_normalizes_case(self):
        payloads = [{'entity_id':'todo.leky'}, {'service_response': {'todo.leky': {'items':[{'summary':'Paralen'},{'summary':'MAGNESIUM'}]}}}]
        with patch('urllib.request.urlopen', side_effect=[FakeResponse(p) for p in payloads]):
            self.assertEqual(self.ns['ha_todo_items'](), {'paralen','magnesium'})

    def test_unknown_response_rejected_not_treated_as_empty(self):
        payloads = [{'entity_id':'todo.leky'}, {'service_response': {'unexpected':'data'}}]
        with patch('urllib.request.urlopen', side_effect=[FakeResponse(p) for p in payloads]):
            with self.assertRaisesRegex(ValueError, 'neočekávaný formát'):
                self.ns['ha_todo_items']()

    def test_missing_entity_yields_manual_setup_and_no_add(self):
        err = urllib.error.HTTPError('http://example',404,'Not found',{},io.BytesIO(b''))
        with patch('urllib.request.urlopen', side_effect=err) as mocked:
            with self.assertRaisesRegex(ValueError, 'neexistuje'):
                self.ns['ha_todo_items']()
            self.assertEqual(mocked.call_count, 1)

    def test_add_uses_expected_service_and_entity(self):
        with patch('urllib.request.urlopen', return_value=FakeResponse([])) as mocked:
            self.ns['ha_todo']('add_item', 'Paralen')
            req = mocked.call_args.args[0]
            self.assertEqual(req.full_url, 'http://supervisor/core/api/services/todo/add_item')
            self.assertEqual(json.loads(req.data), {'entity_id':'todo.leky','item':'Paralen'})

if __name__ == '__main__': unittest.main()
