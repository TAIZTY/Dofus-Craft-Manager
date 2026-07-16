import csv
import io
import json
import shutil
import sqlite3
import threading
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB = DATA_DIR / "dofus_salar.sqlite"
NAMES = DATA_DIR / "items_names.json"
API_BASE = "https://api.dofusdu.de/dofus3/v1/fr/items"
TYPES = ["equipment", "resources", "consumables"]

# Objets techniques, MJ et entrées manifestement internes à masquer dans l’interface.
HIDDEN_NAME_PATTERNS = (
    "(mj)", "timer ", "test ", "debug", "placeholder", "dummy",
    "invisible", "à supprimer", "a supprimer",
)



def normalize_search(value):
    """Retourne une version minuscule sans accents pour les recherches."""
    text = str(value or "").casefold()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def visible_item_sql(alias="i"):
    clauses = [f"LOWER({alias}.name) NOT LIKE ?" for _ in HIDDEN_NAME_PATTERNS]
    return " AND ".join(clauses), [f"%{x}%" for x in HIDDEN_NAME_PATTERNS]


def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    con = db()
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            name_en TEXT,
            name_search TEXT,
            level INTEGER,
            category TEXT,
            subtype TEXT,
            image TEXT
        );
        CREATE TABLE IF NOT EXISTS recipes(
            output_id INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            PRIMARY KEY(output_id, ingredient_id)
        );
        CREATE TABLE IF NOT EXISTS prices(
            item_id INTEGER PRIMARY KEY,
            p1 REAL,
            p10 REAL,
            p100 REAL,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS price_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            p1 REAL,
            p10 REAL,
            p100 REAL,
            recorded_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS inventory(
            item_id INTEGER PRIMARY KEY,
            quantity INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
        CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
        CREATE INDEX IF NOT EXISTS idx_recipes_output ON recipes(output_id);
        CREATE INDEX IF NOT EXISTS idx_recipes_ingredient ON recipes(ingredient_id);
        CREATE INDEX IF NOT EXISTS idx_price_history_item ON price_history(item_id,recorded_at);
        """
    )
    columns = {r[1] for r in cur.execute("PRAGMA table_info(items)")}
    if "name_search" not in columns:
        cur.execute("ALTER TABLE items ADD COLUMN name_search TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_name_search ON items(name_search)")
    if cur.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0 and NAMES.exists():
        names = json.loads(NAMES.read_text(encoding="utf-8"))
        cur.executemany(
            "INSERT OR IGNORE INTO items(id,name,name_en,name_search) VALUES(?,?,?,?)",
            [(int(k), v.get("name_fr", ""), v.get("name_en", ""), normalize_search(v.get("name_fr", ""))) for k, v in names.items()],
        )
    rows_to_normalize = cur.execute("SELECT id,name FROM items WHERE name_search IS NULL OR name_search=''").fetchall()
    if rows_to_normalize:
        cur.executemany("UPDATE items SET name_search=? WHERE id=?", [(normalize_search(r['name']), r['id']) for r in rows_to_normalize])
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('sale_tax_rate','0.02')")
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('sale_tax_enabled','1')")
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('auto_refresh_enabled','1')")
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('auto_refresh_seconds','30')")
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('auto_sync_enabled','1')")
    con.commit()
    con.close()




def lot_purchase_plan(quantity, p1, p10, p100):
    """Return the cheapest way to buy at least quantity units using HDV lots x1/x10/x100."""
    quantity = max(int(quantity or 0), 0)
    prices = {1: p1 if p1 and p1 > 0 else None, 10: p10 if p10 and p10 > 0 else None, 100: p100 if p100 and p100 > 0 else None}
    if quantity <= 0:
        return {"quantity": 0, "cost": 0, "units": 0, "overbuy": 0, "lots": {"x1": 0, "x10": 0, "x100": 0}, "label": "aucun achat", "options": []}

    options = []
    for size, key in ((1, "x1"), (10, "x10"), (100, "x100")):
        price = prices[size]
        if price is not None:
            count = (quantity + size - 1) // size
            units = count * size
            options.append({"type": key, "lots": count, "units": units, "overbuy": units - quantity, "cost": count * price})

    best = None
    max100 = (quantity + 99) // 100 + 1
    max10 = (quantity + 9) // 10 + 10
    for n100 in range(max100 + 1):
        if n100 and prices[100] is None:
            continue
        for n10 in range(max10 + 1):
            if n10 and prices[10] is None:
                continue
            units = n100 * 100 + n10 * 10
            remaining = max(quantity - units, 0)
            if remaining and prices[1] is None:
                continue
            n1 = remaining
            if n1 and prices[1] is None:
                continue
            total_units = units + n1
            if total_units < quantity:
                continue
            cost = n100 * (prices[100] or 0) + n10 * (prices[10] or 0) + n1 * (prices[1] or 0)
            candidate = (cost, total_units - quantity, n100 + n10 + n1, n1, n10, n100)
            if best is None or candidate < best[0]:
                best = (candidate, {"quantity": quantity, "cost": cost, "units": total_units, "overbuy": total_units - quantity,
                                    "lots": {"x1": n1, "x10": n10, "x100": n100}})

    result = best[1] if best else {"quantity": quantity, "cost": None, "units": 0, "overbuy": 0, "lots": {"x1": 0, "x10": 0, "x100": 0}}
    parts = []
    for key in ("x100", "x10", "x1"):
        if result["lots"].get(key):
            parts.append(f'{result["lots"][key]} lot{"s" if result["lots"][key] > 1 else ""} {key}')
    result["label"] = " + ".join(parts) if parts else "prix manquant"
    result["options"] = options
    return result

def best_unit(row):
    values = []
    if row and row["p1"] not in (None, 0):
        values.append((float(row["p1"]), "x1"))
    if row and row["p10"] not in (None, 0):
        values.append((float(row["p10"]) / 10, "x10"))
    if row and row["p100"] not in (None, 0):
        values.append((float(row["p100"]) / 100, "x100"))
    return min(values) if values else (None, None)


def get_setting(con, key, default=None):
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def tax_rate(con):
    try:
        return max(0.0, min(float(get_setting(con, "sale_tax_rate", "0.02")), 1.0))
    except (TypeError, ValueError):
        return 0.02


def build_engine(con):
    price_rows = {r["item_id"]: r for r in con.execute("SELECT * FROM prices")}
    unit_prices = {item_id: best_unit(row)[0] for item_id, row in price_rows.items()}
    recipes = {}
    for r in con.execute("SELECT output_id,ingredient_id,quantity FROM recipes"):
        recipes.setdefault(r["output_id"], []).append((r["ingredient_id"], r["quantity"]))

    memo = {}
    visiting = set()

    def calc(item_id):
        if item_id in memo:
            return memo[item_id]
        buy = unit_prices.get(item_id)
        recipe = recipes.get(item_id)
        if item_id in visiting or not recipe:
            result = {
                "buy": buy,
                "craft": None,
                "best": buy,
                "mode": "acheter" if buy is not None else None,
                "complete": buy is not None,
            }
            memo[item_id] = result
            return result

        visiting.add(item_id)
        total = 0.0
        complete = True
        for ingredient_id, quantity in recipe:
            ingredient = calc(ingredient_id)
            if ingredient["best"] is None:
                complete = False
                break
            total += ingredient["best"] * quantity
        visiting.remove(item_id)

        craft = total if complete else None
        candidates = [(buy, "acheter"), (craft, "fabriquer")]
        candidates = [x for x in candidates if x[0] is not None]
        best, mode = min(candidates, key=lambda x: x[0]) if candidates else (None, None)
        result = {
            "buy": buy,
            "craft": craft,
            "best": best,
            "mode": mode,
            "complete": complete,
        }
        memo[item_id] = result
        return result

    return calc, unit_prices, recipes


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DofusCraftManager-Salar/5.0",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))


class Progress(dict):
    lock = threading.Lock()

    def update_safe(self, **kwargs):
        with self.lock:
            super().update(**kwargs)


progress = Progress(status="idle", message="Prêt", percent=0)


def sync_data():
    con = db()
    cur = con.cursor()
    try:
        for index, item_type in enumerate(TYPES, start=1):
            progress.update_safe(
                status="running",
                message=f"Téléchargement : {item_type}",
                percent=int((index - 1) / len(TYPES) * 100),
            )
            query = urllib.parse.urlencode({"page[size]": -1, "fields[item]": "recipe"})
            payload = fetch_json(f"{API_BASE}/{item_type}?{query}")
            rows = payload.get("items", payload if isinstance(payload, list) else [])
            for item in rows:
                item_id = item.get("ankama_id")
                if item_id is None:
                    continue
                item_kind = item.get("type") or {}
                image = (item.get("image_urls") or {}).get("icon")
                cur.execute(
                    """
                    INSERT INTO items(id,name,name_search,level,category,subtype,image)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        name_search=excluded.name_search,
                        level=excluded.level,
                        category=excluded.category,
                        subtype=excluded.subtype,
                        image=excluded.image
                    """,
                    (
                        item_id,
                        item.get("name", ""),
                        normalize_search(item.get("name", "")),
                        item.get("level"),
                        item_type,
                        item_kind.get("name") or item_kind.get("name_id"),
                        image,
                    ),
                )
                cur.execute("DELETE FROM recipes WHERE output_id=?", (item_id,))
                for recipe_line in item.get("recipe") or []:
                    ingredient_id = recipe_line.get("item_ankama_id")
                    quantity = recipe_line.get("quantity")
                    if ingredient_id is not None and quantity:
                        cur.execute(
                            "INSERT OR REPLACE INTO recipes(output_id,ingredient_id,quantity) VALUES(?,?,?)",
                            (item_id, ingredient_id, quantity),
                        )
            con.commit()
        cur.execute(
            "INSERT INTO settings(key,value) VALUES('last_sync',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        con.commit()
        progress.update_safe(status="done", message="Synchronisation terminée", percent=100)
    except Exception as exc:
        progress.update_safe(status="error", message=f"Erreur : {exc}", percent=0)
    finally:
        con.close()


def craft_tree(con, item_id, quantity=1, depth=0, max_depth=8, path=None):
    path = set(path or set())
    row = con.execute("SELECT id,name,level,category,subtype,image FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return {"id": item_id, "name": f"#{item_id}", "quantity": quantity, "missing": True}
    calc, _, recipes = build_engine(con)
    cost = calc(item_id)
    node = {**dict(row), "quantity": quantity, **cost, "children": []}
    if depth >= max_depth or item_id in path:
        node["truncated"] = True
        return node
    if cost["mode"] == "fabriquer" and item_id in recipes:
        next_path = set(path)
        next_path.add(item_id)
        for ingredient_id, ingredient_qty in recipes[item_id]:
            node["children"].append(
                craft_tree(con, ingredient_id, quantity * ingredient_qty, depth + 1, max_depth, next_path)
            )
    return node



def build_workshop_plan(con, selections):
    """Plan léger : stock, choix acheter/fabriquer et regroupement des achats."""
    calc, _, recipes = build_engine(con)
    item_rows = {r["id"]: dict(r) for r in con.execute("SELECT id,name,category,subtype,image FROM items")}
    price_rows = {r["item_id"]: r for r in con.execute("SELECT * FROM prices")}
    available = {r["item_id"]: int(r["quantity"] or 0) for r in con.execute("SELECT item_id,quantity FROM inventory")}
    purchases, crafts, stock_used, missing = {}, {}, {}, {}
    visiting=set()
    def add(target,item_id,qty): target[item_id]=target.get(item_id,0)+int(qty)
    def fulfill(item_id,qty):
        qty=max(int(qty or 0),0)
        if not qty:return
        use=min(available.get(item_id,0),qty)
        if use: available[item_id]-=use;add(stock_used,item_id,use);qty-=use
        if not qty:return
        state=calc(item_id);recipe=recipes.get(item_id)
        if item_id not in visiting and recipe and state.get('mode')=='fabriquer':
            add(crafts,item_id,qty);visiting.add(item_id)
            for ing,amount in recipe:fulfill(ing,qty*amount)
            visiting.remove(item_id);return
        row=price_rows.get(item_id)
        old=purchases.get(item_id);total=qty+(old['quantity'] if old else 0)
        plan=lot_purchase_plan(total,row['p1'] if row else None,row['p10'] if row else None,row['p100'] if row else None)
        if plan.get('cost') is None:add(missing,item_id,qty)
        else:purchases[item_id]=plan
    for entry in selections or []:fulfill(int(entry.get('item_id') or 0),int(entry.get('quantity') or 0))
    def decorate(mapping):
        return sorted([{**item_rows.get(i,{'name':f'#{i}'}),'item_id':i,'quantity':q} for i,q in mapping.items()],key=lambda x:x.get('name',''))
    buy=[];total=0.0
    for i,plan in purchases.items():
        total+=float(plan.get('cost') or 0);buy.append({**item_rows.get(i,{'name':f'#{i}'}),'item_id':i,**plan})
    buy.sort(key=lambda x:x.get('name',''))
    return {'purchases':buy,'crafts':decorate(crafts),'stock_used':decorate(stock_used),'missing':decorate(missing),'total_cost':total,'complete':not bool(missing)}

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        parsed = urllib.parse.urlparse(path).path
        return str(ROOT / ("index.html" if parsed == "/" else parsed.lstrip("/")))

    def send_json(self, obj, status=200, headers=None):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)

        if url.path == "/api/status":
            con = db()
            last_sync = con.execute("SELECT value FROM settings WHERE key='last_sync'").fetchone()
            stats = {
                "items": con.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                "recipes": con.execute("SELECT COUNT(DISTINCT output_id) FROM recipes").fetchone()[0],
                "ingredients": con.execute("SELECT COUNT(*) FROM recipes").fetchone()[0],
                "prices": con.execute(
                    "SELECT COUNT(*) FROM prices WHERE COALESCE(p1,p10,p100) IS NOT NULL"
                ).fetchone()[0],
                "last_sync": last_sync[0] if last_sync else None,
                **progress,
            }
            con.close()
            return self.send_json(stats)

        if url.path == "/api/categories":
            con = db()
            visibility_sql, visibility_params = visible_item_sql("i")
            rows = con.execute(
                f"SELECT category,subtype,COUNT(*) count FROM items i WHERE category IS NOT NULL AND {visibility_sql} GROUP BY category,subtype ORDER BY category,subtype",
                visibility_params,
            ).fetchall()
            con.close()
            return self.send_json([dict(r) for r in rows])

        if url.path == "/api/items":
            term = query.get("q", [""])[0].strip()
            view = query.get("view", ["recent"])[0].strip()
            category = query.get("category", [""])[0].strip()
            limit = min(max(int(query.get("limit", ["100"])[0]), 1), 500)
            con = db()
            visibility_sql, visibility_params = visible_item_sql("i")
            clauses = [visibility_sql]
            params = list(visibility_params)
            if term:
                clauses.append("i.name_search LIKE ?")
                params.append(f"%{normalize_search(term)}%")
            if category:
                clauses.append("i.category=?")
                params.append(category)
            if not term:
                if view == "recent":
                    clauses.append("p.item_id IS NOT NULL AND (p.p1 IS NOT NULL OR p.p10 IS NOT NULL OR p.p100 IS NOT NULL)")
                elif view == "useful":
                    clauses.append("EXISTS(SELECT 1 FROM recipes r WHERE r.ingredient_id=i.id)")
                elif view == "missing":
                    clauses.append("EXISTS(SELECT 1 FROM recipes r WHERE r.ingredient_id=i.id)")
                    clauses.append("(p.item_id IS NULL OR (p.p1 IS NULL AND p.p10 IS NULL AND p.p100 IS NULL))")
            where = " AND ".join(clauses)
            if term:
                normalized_term = normalize_search(term)
                order = "CASE WHEN i.name_search=? THEN 0 WHEN i.name_search LIKE ? THEN 1 ELSE 2 END, i.name"
                params.extend([normalized_term, f"{normalized_term}%"])
            elif view == "recent":
                order = "p.updated_at DESC, i.name"
            else:
                order = "i.name"
            params.append(limit)
            rows = con.execute(
                f"""
                SELECT i.*,p.p1,p.p10,p.p100,p.updated_at,
                       EXISTS(SELECT 1 FROM recipes rc WHERE rc.output_id=i.id) AS is_craftable,
                       (SELECT COUNT(DISTINCT ru.output_id) FROM recipes ru WHERE ru.ingredient_id=i.id) AS used_in_count
                FROM items i LEFT JOIN prices p ON p.item_id=i.id
                WHERE {where}
                ORDER BY {order}
                LIMIT ?
                """, params
            ).fetchall()
            con.close()
            return self.send_json([dict(r) for r in rows])

        if url.path == "/api/crafts":
            term = query.get("q", [""])[0].strip()
            category = query.get("category", [""])[0].strip()
            min_level = int(query.get("min_level", ["0"])[0] or 0)
            max_level = int(query.get("max_level", ["200"])[0] or 200)
            only_complete = query.get("complete", ["0"])[0] == "1"
            only_profitable = query.get("profitable", ["0"])[0] == "1"
            sort = query.get("sort", ["profit"])[0]
            ingredient_id = int(query.get("ingredient_id", ["0"])[0] or 0)
            limit = min(max(int(query.get("limit", ["300"])[0]), 1), 1500)

            con = db()
            calc, prices, _ = build_engine(con)
            enabled = get_setting(con, "sale_tax_enabled", "1") != "0"
            rate = tax_rate(con) if enabled else 0.0
            visibility_sql, visibility_params = visible_item_sql("i")
            sql = f"""
                SELECT i.* FROM items i
                WHERE EXISTS(SELECT 1 FROM recipes r WHERE r.output_id=i.id)
                  AND i.name_search LIKE ?
                  AND COALESCE(i.level,0) BETWEEN ? AND ?
                  AND {visibility_sql}
            """
            params = [f"%{normalize_search(term)}%", min_level, max_level, *visibility_params]
            if category:
                sql += " AND i.category=?"
                params.append(category)
            if ingredient_id:
                sql += " AND EXISTS(SELECT 1 FROM recipes rf WHERE rf.output_id=i.id AND rf.ingredient_id=?)"
                params.append(ingredient_id)
            sql += " ORDER BY i.name"
            rows = con.execute(sql, params).fetchall()
            output = []
            for row in rows:
                values = calc(row["id"])
                sale = prices.get(row["id"])
                tax = sale * rate if sale is not None else None
                net_sale = sale - tax if sale is not None else None
                profit = net_sale - values["best"] if net_sale is not None and values["best"] is not None else None
                roi = profit / values["best"] * 100 if profit is not None and values["best"] else None
                craft = {**dict(row), **values, "sale": sale, "tax": tax, "net_sale": net_sale, "tax_rate": rate, "profit": profit, "roi": roi}
                if only_complete and (sale is None or values["best"] is None):
                    continue
                if only_profitable and (profit is None or profit <= 0):
                    continue
                output.append(craft)
            con.close()

            sort_keys = {
                "profit": lambda x: (x["profit"] is not None, x["profit"] or -10**30),
                "roi": lambda x: (x["roi"] is not None, x["roi"] or -10**30),
                "level": lambda x: (x["level"] is not None, x["level"] or -1),
                "name": lambda x: x["name"].casefold(),
            }
            if sort == "name":
                output.sort(key=sort_keys["name"])
            elif sort == "profit":
                output.sort(key=lambda x: (-(x["profit"] if x["profit"] is not None else -10**30), -(x["roi"] if x["roi"] is not None else -10**30), x["name"].casefold()))
            elif sort == "roi":
                output.sort(key=lambda x: (-(x["roi"] if x["roi"] is not None else -10**30), -(x["profit"] if x["profit"] is not None else -10**30), x["name"].casefold()))
            else:
                metric = sort_keys.get(sort, sort_keys["profit"])
                output.sort(key=lambda x: (x["profit"] is not None and x["profit"] > 0, x["sale"] is not None and x["best"] is not None, metric(x)), reverse=True)
            return self.send_json(output[:limit])

        if url.path == "/api/recipe":
            item_id = int(query.get("id", ["0"])[0])
            con = db()
            calc, _, _ = build_engine(con)
            output_row = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            lines = con.execute(
                """
                SELECT r.ingredient_id,r.quantity,i.name,i.level,i.category,i.subtype,i.image,
                       p.p1,p.p10,p.p100,p.updated_at
                FROM recipes r
                LEFT JOIN items i ON i.id=r.ingredient_id
                LEFT JOIN prices p ON p.item_id=r.ingredient_id
                WHERE r.output_id=? ORDER BY i.name
                """,
                (item_id,),
            ).fetchall()
            cost = calc(item_id)
            price_row = con.execute("SELECT * FROM prices WHERE item_id=?", (item_id,)).fetchone()
            sale = best_unit(price_row)[0]
            enabled = get_setting(con, "sale_tax_enabled", "1") != "0"
            rate = tax_rate(con) if enabled else 0.0
            tax = sale * rate if sale is not None else None
            net_sale = sale - tax if sale is not None else None
            profit = net_sale - cost["best"] if net_sale is not None and cost["best"] is not None else None
            roi = profit / cost["best"] * 100 if profit is not None and cost["best"] else None
            output = {
                "item": dict(output_row) if output_row else None,
                "cost": cost,
                "sale": sale, "tax": tax, "net_sale": net_sale, "tax_rate": rate, "profit": profit, "roi": roi,
                "ingredients": [{**dict(r), **calc(r["ingredient_id"]),
                                 "purchase_plan": lot_purchase_plan(r["quantity"], r["p1"], r["p10"], r["p100"])} for r in lines],
            }
            con.close()
            return self.send_json(output)

        if url.path == "/api/tree":
            item_id = int(query.get("id", ["0"])[0])
            quantity = max(int(query.get("quantity", ["1"])[0]), 1)
            con = db()
            tree = craft_tree(con, item_id, quantity)
            con.close()
            return self.send_json(tree)

        if url.path == "/api/dashboard":
            con = db()
            calc, prices, _ = build_engine(con)
            enabled = get_setting(con, "sale_tax_enabled", "1") != "0"
            rate = tax_rate(con) if enabled else 0.0
            visibility_sql, visibility_params = visible_item_sql("i")
            rows = con.execute(
                f"SELECT i.* FROM items i WHERE EXISTS(SELECT 1 FROM recipes r WHERE r.output_id=i.id) AND {visibility_sql}",
                visibility_params,
            ).fetchall()
            profitable = []
            complete_count = 0
            for row in rows:
                cost = calc(row["id"])
                sale = prices.get(row["id"])
                if sale is not None and cost["best"] is not None:
                    complete_count += 1
                    tax = sale * rate
                    net_sale = sale - tax
                    profit = net_sale - cost["best"]
                    roi = profit / cost["best"] * 100 if cost["best"] else None
                    if profit > 0:
                        profitable.append({**dict(row), **cost, "sale": sale, "tax": tax, "net_sale": net_sale, "tax_rate": rate, "profit": profit, "roi": roi})
            profitable.sort(key=lambda x: (-x["profit"], -(x["roi"] or -10**30), x["name"].casefold()))
            result = {
                "complete": complete_count,
                "profitable": len(profitable),
                "top_profit": profitable[:20],
                "top_roi": sorted(profitable, key=lambda x: (-(x["roi"] or -10**30), -x["profit"], x["name"].casefold()))[:20],
            }
            con.close()
            return self.send_json(result)



        if url.path == "/api/priorities":
            limit = min(max(int(query.get("limit", ["50"])[0]), 1), 250)
            con = db()
            calc, unit_prices, recipes = build_engine(con)
            item_rows = {r["id"]: dict(r) for r in con.execute("SELECT id,name,level,category,subtype,image FROM items")}
            visibility_sql, visibility_params = visible_item_sql("i")
            outputs = [r[0] for r in con.execute(
                f"SELECT i.id FROM items i WHERE EXISTS(SELECT 1 FROM recipes rr WHERE rr.output_id=i.id) AND {visibility_sql}",
                visibility_params,
            )]
            missing_memo = {}
            visiting = set()
            def missing_for_cost(item_id):
                if unit_prices.get(item_id) is not None:
                    return frozenset()
                if item_id in missing_memo:
                    return missing_memo[item_id]
                if item_id in visiting or item_id not in recipes:
                    return frozenset((item_id,))
                visiting.add(item_id)
                missing = set()
                for ingredient_id, _qty in recipes[item_id]:
                    missing.update(missing_for_cost(ingredient_id))
                visiting.discard(item_id)
                result = frozenset(missing)
                missing_memo[item_id] = result
                return result
            exact = {}
            potential = {}
            for output_id in outputs:
                missing = set(missing_for_cost(output_id))
                if unit_prices.get(output_id) is None:
                    missing.add(output_id)  # prix de vente manquant
                for item_id in missing:
                    potential[item_id] = potential.get(item_id, 0) + 1
                if len(missing) == 1:
                    item_id = next(iter(missing))
                    exact[item_id] = exact.get(item_id, 0) + 1
            result=[]
            for item_id, score in potential.items():
                row=item_rows.get(item_id)
                if not row: continue
                result.append({**row,"unlocks":exact.get(item_id,0),"potential":score,
                               "used_in":con.execute("SELECT COUNT(DISTINCT output_id) FROM recipes WHERE ingredient_id=?",(item_id,)).fetchone()[0]})
            result.sort(key=lambda x:(-x["unlocks"],-x["potential"],x["name"].casefold()))
            priced=con.execute("SELECT COUNT(*) FROM prices WHERE COALESCE(p1,p10,p100) IS NOT NULL").fetchone()[0]
            con.close()
            return self.send_json({"priced":priced,"items":result[:limit]})

        if url.path == "/api/opportunities":
            try: budget=max(0.0,float(query.get("budget",["5000000"])[0] or 0))
            except ValueError: budget=5000000.0
            con=db(); calc, prices, _=build_engine(con)
            rate=tax_rate(con) if get_setting(con,"sale_tax_enabled","1") != "0" else 0.0
            visibility_sql, visibility_params=visible_item_sql("i")
            rows=con.execute(f"SELECT i.* FROM items i WHERE EXISTS(SELECT 1 FROM recipes r WHERE r.output_id=i.id) AND {visibility_sql}",visibility_params).fetchall()
            opportunities=[]
            now=datetime.now()
            for row in rows:
                sale=prices.get(row["id"]); cost=calc(row["id"])
                if sale is None or cost["best"] is None: continue
                net=sale*(1-rate); profit=net-cost["best"]
                if profit <= 0: continue
                roi=profit/cost["best"]*100 if cost["best"] else None
                price_row=con.execute("SELECT updated_at FROM prices WHERE item_id=?",(row["id"],)).fetchone()
                age_days=999
                if price_row and price_row[0]:
                    try: age_days=max(0,(now-datetime.fromisoformat(price_row[0])).days)
                    except ValueError: pass
                confidence=max(20,100-min(age_days*4,60))
                qty=int(budget//cost["best"]) if cost["best"] else 0
                opportunities.append({**dict(row),**cost,"sale":sale,"net_sale":net,"profit":profit,"roi":roi,
                                      "confidence":confidence,"budget_qty":qty,"budget_profit":qty*profit})
            by_profit=sorted(opportunities,key=lambda x:(-x["profit"],-(x["roi"] or 0),x["name"].casefold()))
            by_roi=sorted(opportunities,key=lambda x:(-(x["roi"] or 0),-x["profit"],x["name"].casefold()))
            by_budget=sorted([x for x in opportunities if x["budget_qty"]>0],key=lambda x:(-x["budget_profit"],-x["profit"]))
            low=[x for x in by_profit if x["best"]<=500000][:30]
            high=[x for x in by_profit if x["best"]>=10000000][:30]
            advice=[]
            if by_budget:
                x=by_budget[0]; advice.append(f"Avec {int(budget):,} K, le meilleur potentiel actuel est {x['name']} ×{x['budget_qty']} pour environ {int(x['budget_profit']):,} K nets.")
            if by_roi:
                x=by_roi[0]; advice.append(f"Le meilleur rendement est {x['name']} avec {x['roi']:.1f} % de ROI net.")
            if by_profit:
                x=by_profit[0]; advice.append(f"Le plus gros bénéfice unitaire est {x['name']} : environ {int(x['profit']):,} K nets.")
            con.close()
            return self.send_json({"budget":budget,"count":len(opportunities),"top_profit":by_profit[:30],"top_roi":by_roi[:30],"budget_best":by_budget[:30],"low_budget":low,"high_budget":high,"advice":advice})

        if url.path == "/api/item-search":
            term=query.get("q",[""])[0].strip(); limit=min(max(int(query.get("limit",["20"])[0]),1),50)
            con=db(); visibility_sql, visibility_params=visible_item_sql("i")
            rows=con.execute(f"SELECT i.id,i.name,i.image,i.category,i.subtype FROM items i WHERE i.name_search LIKE ? AND {visibility_sql} ORDER BY CASE WHEN i.name_search=? THEN 0 WHEN i.name_search LIKE ? THEN 1 ELSE 2 END,i.name LIMIT ?",(f"%{normalize_search(term)}%",*visibility_params,normalize_search(term),f"{normalize_search(term)}%",limit)).fetchall() if term else []
            con.close(); return self.send_json([dict(r) for r in rows])

        if url.path == "/api/settings":
            con = db()
            enabled = get_setting(con, "sale_tax_enabled", "1") != "0"
            rate = tax_rate(con)
            auto_refresh_enabled = get_setting(con, "auto_refresh_enabled", "1") != "0"
            try:
                auto_refresh_seconds = max(10, min(int(get_setting(con, "auto_refresh_seconds", "30")), 300))
            except (TypeError, ValueError):
                auto_refresh_seconds = 30
            auto_sync_enabled = get_setting(con, "auto_sync_enabled", "1") != "0"
            con.close()
            return self.send_json({"sale_tax_enabled": enabled, "sale_tax_rate": rate, "auto_refresh_enabled": auto_refresh_enabled, "auto_refresh_seconds": auto_refresh_seconds, "auto_sync_enabled": auto_sync_enabled})

        if url.path == "/api/inventory":
            term=query.get("q",[""])[0].strip();limit=min(max(int(query.get("limit",["300"])[0]),1),1000)
            con=db();params=[];where="inv.quantity>0"
            if term: where+=" AND i.name_search LIKE ?";params.append(f"%{normalize_search(term)}%")
            params.append(limit)
            rows=con.execute(f"SELECT i.id,i.name,i.category,i.subtype,i.image,inv.quantity,inv.updated_at FROM inventory inv JOIN items i ON i.id=inv.item_id WHERE {where} ORDER BY i.name LIMIT ?",params).fetchall();con.close()
            return self.send_json([dict(r) for r in rows])

        if url.path == "/api/history":
            item_id = int(query.get("id", ["0"])[0] or 0)
            limit = min(max(int(query.get("limit", ["30"])[0]), 1), 365)
            con = db()
            if item_id:
                rows = con.execute(
                    "SELECT h.*,i.name FROM price_history h JOIN items i ON i.id=h.item_id WHERE h.item_id=? ORDER BY h.recorded_at DESC,h.id DESC LIMIT ?",
                    (item_id, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT h.*,i.name FROM price_history h JOIN items i ON i.id=h.item_id ORDER BY h.recorded_at DESC,h.id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            con.close()
            return self.send_json([dict(r) for r in rows])

        if url.path == "/api/diagnostics":
            con = db()
            visibility_sql, visibility_params = visible_item_sql("i")
            result = {
                "hidden_items": con.execute("SELECT COUNT(*) FROM items i WHERE NOT (" + visibility_sql + ")", visibility_params).fetchone()[0],
                "recipes_without_output": con.execute("SELECT COUNT(*) FROM recipes r LEFT JOIN items i ON i.id=r.output_id WHERE i.id IS NULL").fetchone()[0],
                "ingredients_without_item": con.execute("SELECT COUNT(*) FROM recipes r LEFT JOIN items i ON i.id=r.ingredient_id WHERE i.id IS NULL").fetchone()[0],
                "crafts_without_any_price": con.execute("SELECT COUNT(DISTINCT r.output_id) FROM recipes r LEFT JOIN prices p ON p.item_id=r.output_id WHERE p.item_id IS NULL OR (p.p1 IS NULL AND p.p10 IS NULL AND p.p100 IS NULL)").fetchone()[0],
                "priced_items": con.execute("SELECT COUNT(*) FROM prices WHERE p1 IS NOT NULL OR p10 IS NOT NULL OR p100 IS NOT NULL").fetchone()[0],
            }
            con.close()
            result["ok"] = result["recipes_without_output"] == 0 and result["ingredients_without_item"] == 0
            return self.send_json(result)

        if url.path == "/api/export-prices":
            con = db()
            output = [dict(r) for r in con.execute("SELECT * FROM prices ORDER BY item_id")]
            con.close()
            return self.send_json(
                output,
                headers={"Content-Disposition": 'attachment; filename="prix_salar.json"'},
            )

        if url.path == "/api/export-prices-csv":
            con = db()
            rows = con.execute(
                """
                SELECT i.id,i.name,p.p1,p.p10,p.p100,p.updated_at
                FROM prices p JOIN items i ON i.id=p.item_id ORDER BY i.name
                """
            ).fetchall()
            con.close()
            stream = io.StringIO()
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(["item_id", "name", "p1", "p10", "p100", "updated_at"])
            writer.writerows([tuple(r) for r in rows])
            raw = stream.getvalue().encode("utf-8-sig")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="prix_salar.csv"')
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if url.path == "/api/backup":
            backup_dir = DATA_DIR / "backups"
            backup_dir.mkdir(exist_ok=True)
            target = backup_dir / f"dofus_salar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite"
            shutil.copy2(DB, target)
            return self.send_json({"ok": True, "file": str(target.name)})

        return super().do_GET()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)

        if url.path == "/api/prices":
            data = self.read_json()
            con = db()
            item_id = int(data["item_id"])
            values = (data.get("p1"), data.get("p10"), data.get("p100"))
            con.execute(
                """
                INSERT INTO prices(item_id,p1,p10,p100,updated_at)
                VALUES(?,?,?,?,datetime('now','localtime'))
                ON CONFLICT(item_id) DO UPDATE SET
                    p1=excluded.p1,p10=excluded.p10,p100=excluded.p100,updated_at=excluded.updated_at
                """,
                (item_id, *values),
            )
            con.execute("INSERT INTO price_history(item_id,p1,p10,p100) VALUES(?,?,?,?)", (item_id, *values))
            con.commit()
            row = con.execute("SELECT * FROM prices WHERE item_id=?", (item_id,)).fetchone()
            unit, lot = best_unit(row)
            con.close()
            return self.send_json({"ok": True, "item_id": item_id, "best_unit": unit, "best_lot": lot})

        if url.path == "/api/inventory":
            data=self.read_json();item_id=int(data.get("item_id") or 0);quantity=max(int(data.get("quantity") or 0),0);con=db()
            if quantity: con.execute("INSERT INTO inventory(item_id,quantity,updated_at) VALUES(?,?,datetime('now','localtime')) ON CONFLICT(item_id) DO UPDATE SET quantity=excluded.quantity,updated_at=excluded.updated_at",(item_id,quantity))
            else: con.execute("DELETE FROM inventory WHERE item_id=?",(item_id,))
            con.commit();con.close();return self.send_json({"ok":True,"item_id":item_id,"quantity":quantity})

        if url.path == "/api/workshop-plan":
            data=self.read_json();con=db()
            try: result=build_workshop_plan(con,data.get("selections") or [])
            finally: con.close()
            return self.send_json(result)

        if url.path == "/api/settings":
            data = self.read_json()
            con = db()
            current_enabled = get_setting(con, "sale_tax_enabled", "1") != "0"
            current_rate = tax_rate(con)
            enabled = "1" if bool(data.get("sale_tax_enabled", current_enabled)) else "0"
            try:
                rate = max(0.0, min(float(data.get("sale_tax_rate", current_rate)), 1.0))
            except (TypeError, ValueError):
                rate = current_rate
            if "sale_tax_enabled" in data:
                con.execute("INSERT INTO settings(key,value) VALUES('sale_tax_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (enabled,))
            if "sale_tax_rate" in data:
                con.execute("INSERT INTO settings(key,value) VALUES('sale_tax_rate',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(rate),))
            if "auto_refresh_enabled" in data:
                auto_refresh_enabled = "1" if bool(data.get("auto_refresh_enabled")) else "0"
                con.execute("INSERT INTO settings(key,value) VALUES('auto_refresh_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (auto_refresh_enabled,))
            if "auto_refresh_seconds" in data:
                try:
                    seconds = max(10, min(int(data.get("auto_refresh_seconds", 30)), 300))
                except (TypeError, ValueError):
                    seconds = 30
                con.execute("INSERT INTO settings(key,value) VALUES('auto_refresh_seconds',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(seconds),))
            if "auto_sync_enabled" in data:
                auto_sync_enabled = "1" if bool(data.get("auto_sync_enabled")) else "0"
                con.execute("INSERT INTO settings(key,value) VALUES('auto_sync_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (auto_sync_enabled,))
            con.commit(); con.close()
            return self.send_json({"ok": True, "sale_tax_enabled": enabled == "1", "sale_tax_rate": rate})

        if url.path == "/api/import-prices":
            rows = self.read_json()
            con = db()
            con.executemany(
                """
                INSERT INTO prices(item_id,p1,p10,p100,updated_at)
                VALUES(?,?,?,?,datetime('now','localtime'))
                ON CONFLICT(item_id) DO UPDATE SET
                    p1=excluded.p1,p10=excluded.p10,p100=excluded.p100,updated_at=excluded.updated_at
                """,
                [(int(x["item_id"]), x.get("p1"), x.get("p10"), x.get("p100")) for x in rows],
            )
            con.commit()
            con.close()
            return self.send_json({"ok": True, "count": len(rows)})

        if url.path == "/api/sync":
            if progress.get("status") == "running":
                return self.send_json({"ok": False, "message": "Synchronisation déjà en cours"}, 409)
            progress.update_safe(status="running", message="Démarrage", percent=0)
            threading.Thread(target=sync_data, daemon=True).start()
            return self.send_json({"ok": True})

        return self.send_json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


if __name__ == "__main__":
    init_db()
    print("Dofus Craft Manager V5.2")
    print("Ouvre http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
