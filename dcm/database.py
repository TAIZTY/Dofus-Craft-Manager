import json
import sqlite3
from .config import DB, NAMES, normalize_search

def db():
    con = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA cache_size=-32768")
    try:
        con.execute("PRAGMA mmap_size=268435456")
    except sqlite3.DatabaseError:
        pass
    return con

def get_setting(con, key, default=None):
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def tax_rate(con):
    try:
        return max(0.0, min(float(get_setting(con, "sale_tax_rate", "0.02")), 1.0))
    except (TypeError, ValueError):
        return 0.02

def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_en TEXT,
            name_search TEXT, level INTEGER, category TEXT, subtype TEXT, image TEXT
        );
        CREATE TABLE IF NOT EXISTS recipes(
            output_id INTEGER NOT NULL, ingredient_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL, PRIMARY KEY(output_id, ingredient_id)
        );
        CREATE TABLE IF NOT EXISTS prices(
            item_id INTEGER PRIMARY KEY, p1 REAL, p10 REAL, p100 REAL, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS price_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
            p1 REAL, p10 REAL, p100 REAL,
            recorded_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS inventory(
            item_id INTEGER PRIMARY KEY, quantity INTEGER NOT NULL DEFAULT 0, updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
        CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
        CREATE INDEX IF NOT EXISTS idx_recipes_output ON recipes(output_id);
        CREATE INDEX IF NOT EXISTS idx_recipes_ingredient ON recipes(ingredient_id);
        CREATE INDEX IF NOT EXISTS idx_price_history_item ON price_history(item_id,recorded_at);
        CREATE INDEX IF NOT EXISTS idx_prices_updated_at ON prices(updated_at);
        CREATE INDEX IF NOT EXISTS idx_inventory_updated_at ON inventory(updated_at);
        CREATE INDEX IF NOT EXISTS idx_recipes_output_ingredient ON recipes(output_id,ingredient_id);
    """)
    columns = {r[1] for r in cur.execute("PRAGMA table_info(items)")}
    if "name_search" not in columns:
        cur.execute("ALTER TABLE items ADD COLUMN name_search TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_name_search ON items(name_search)")
    if cur.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0 and NAMES.exists():
        names = json.loads(NAMES.read_text(encoding="utf-8"))
        cur.executemany(
            "INSERT OR IGNORE INTO items(id,name,name_en,name_search) VALUES(?,?,?,?)",
            [(int(k), v.get("name_fr", ""), v.get("name_en", ""),
              normalize_search(v.get("name_fr", ""))) for k, v in names.items()],
        )
    rows = cur.execute("SELECT id,name FROM items WHERE name_search IS NULL OR name_search='' ").fetchall()
    if rows:
        cur.executemany("UPDATE items SET name_search=? WHERE id=?",
                        [(normalize_search(r['name']), r['id']) for r in rows])
    defaults = {
        'sale_tax_rate':'0.02', 'sale_tax_enabled':'1',
        'auto_refresh_enabled':'0', 'auto_refresh_seconds':'120',
        'auto_sync_enabled':'0'
    }
    cur.executemany("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", defaults.items())
    migrated = cur.execute("SELECT value FROM settings WHERE key='performance_v61_migrated'").fetchone()
    if not migrated:
        cur.execute("INSERT INTO settings(key,value) VALUES('performance_v61_migrated','1')")
        for key, value in [('auto_refresh_enabled','0'),('auto_refresh_seconds','120'),('auto_sync_enabled','0')]:
            cur.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,value))
    con.commit()
    con.close()
