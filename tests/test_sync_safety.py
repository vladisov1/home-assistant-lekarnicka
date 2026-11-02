"""Static regression check for cart safety when HA confirmation fails."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'lekarnicka' / 'app.py'

class SyncSafetyTests(unittest.TestCase):
    def test_recheck_after_add_before_local_delete(self):
        tree = ast.parse(SOURCE.read_text())
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'shopping_sync')
        calls = [(n.lineno, ast.unparse(n.func)) for n in ast.walk(func) if isinstance(n, ast.Call)]
        add = min(line for line, name in calls if name == 'ha_todo')
        checks = [line for line, name in calls if name == 'ha_todo_items' and line > add]
        delete = min(line for line, name in calls if name == 'con.execute' and line > add)
        self.assertTrue(checks and min(checks) < delete, 'After add, HA must be queried before cart deletion')
