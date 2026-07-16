"""Tests rapides à lancer avec: python tests/smoke_test.py"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, '-m', 'py_compile', str(ROOT / 'server.py')], check=True)
    app = (ROOT / 'app.js').read_text(encoding='utf-8')
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    assert 'data-page="scanner"' not in html
    assert 'id="scanner"' not in html
    assert 'scanDrop' not in app
    assert (ROOT / '.gitignore').exists()
    print('Tests statiques OK')


if __name__ == '__main__':
    main()
