"""Dependency-independent parser tests; Flask integration needs add-on runtime."""
import ast
import io
import re
import csv
from pathlib import Path

def load_parser():
    source = Path(__file__).parents[1] / 'lekarnicka' / 'app.py'
    tree = ast.parse(source.read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign)) and (isinstance(n, ast.FunctionDef) and n.name in ('sukl_normalize_header','sukl_parse_csv') or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SUKL_FIELDS' for t in n.targets))]
    namespace = {'io': io, 're': re, 'csv': csv, 'ValueError': ValueError}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['sukl_parse_csv']

def test_sukl_csv_import():
    parser=load_parser()
    data='Kód SÚKL;Název;Doplněk názvu;ATC\n0254421;PARALEN;100MG SUP 5;N02BE01\n'
    rows=parser(data.encode('utf-8'))
    assert rows['0254421'][0:3] == ('0254421','PARALEN','100MG SUP 5')
    assert rows['0254421'][4] == 'N02BE01'

def test_sukl_csv_rejects_invalid_headers():
    parser=load_parser()
    try:
        parser(b'foo;bar\n123;abc')
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid header accepted')
