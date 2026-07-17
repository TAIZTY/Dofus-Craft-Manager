"""Tests rapides: python tests/smoke_test.py"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    py_files = [ROOT / 'server.py', *sorted((ROOT / 'dcm').glob('*.py'))]
    subprocess.run([sys.executable, '-m', 'py_compile', *map(str, py_files)], check=True)
    app = (ROOT / 'app.js').read_text(encoding='utf-8')
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    server = (ROOT / 'server.py').read_text(encoding='utf-8')
    assert 'data-page="scanner"' not in html
    assert 'id="scanner"' not in html
    assert 'scanDrop' not in app
    assert '/api/prices-batch' in app and '/api/prices-batch' in server
    assert 'cached_response(("dashboard",)' in server
    assert 'cached_response(("opportunities",' in server
    assert (ROOT / '.gitignore').exists()
    print('Tests statiques V6.3 OK')


if __name__ == '__main__':
    main()
