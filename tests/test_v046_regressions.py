"""Dependency-free regression checks for 0.4.6 UI contracts."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'lekarnicka'
SOURCE = (ROOT / 'app.py').read_text()
TREE = ast.parse(SOURCE)

class Version046ContractTests(unittest.TestCase):
    def test_selected_medicine_is_preserved_after_package_edit(self):
        fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'package_detail')
        text = ast.get_source_segment(SOURCE, fn)
        self.assertIn("url_for('index', selected=p['medicine_id']", text)

    def test_package_created_offers_label_and_catalog_return(self):
        page = (ROOT / 'templates/package_created.html').read_text()
        self.assertIn("url_for('package_label',pid=p.id)", page)
        self.assertIn("url_for('index',selected=m.id)", page)

    def test_quantity_counter_is_non_text_input(self):
        page = (ROOT / 'templates/package_detail.html').read_text()
        self.assertIn('secondary counter-minus', page)
        self.assertIn('secondary counter-plus', page)
        self.assertIn('type="range"', page)
        self.assertIn('name="consume_quantity"', page)
        self.assertIn('name="remaining_quantity" readonly', page)

    def test_package_list_shows_initial_and_remaining(self):
        page = (ROOT / 'templates/index.html').read_text()
        self.assertIn('p.initial_quantity', page)
        self.assertIn('p.remaining_quantity', page)

    def test_initial_quantity_can_initialize_remaining(self):
        fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'package_detail')
        text = ast.get_source_segment(SOURCE, fn)
        self.assertIn("initial, remaining, unit = apply_consumption(", text)

class Version046SafetyTests(unittest.TestCase):
    def test_inventory_is_validated_by_pure_function(self):
        fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'package_detail')
        text = ast.get_source_segment(SOURCE, fn)
        self.assertIn('apply_consumption(', text)
        self.assertNotIn("remaining = int(raw_remaining)", text)

    def test_cancel_retains_location_context(self):
        page = (ROOT / 'templates/package_detail.html').read_text()
        self.assertIn("selected=p.medicine_id,location_id=loc_id", page)

    def test_delete_disabled_when_packages_exist(self):
        page = (ROOT / 'templates/medicine_detail.html').read_text()
        self.assertIn('disabled>Odstranit lék', page)
        self.assertIn('Nejprve vyřaďte všechna fyzická balení', page)

if __name__ == '__main__':
    unittest.main()
