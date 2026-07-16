import csv
import io
import json
import shutil
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from dcm.config import ROOT, DATA_DIR, DB, normalize_search, visible_item_sql
from dcm.database import db, init_db, get_setting, tax_rate
from dcm.economics import best_unit, lot_purchase_plan
from dcm.engine import build_engine, invalidate_engine, craft_tree, engine_generation
from dcm.workshop import make_workshop_context, build_workshop_plan, strict_budget_plan
from dcm.sync import progress, sync_data

_RESPONSE_CACHE = {}
_RESPONSE_CACHE_LOCK = threading.RLock()

def invalidate_response_cache():
    with _RESPONSE_CACHE_LOCK:
        _RESPONSE_CACHE.clear()

def cached_response(key, producer):
    generation = engine_generation()
    cache_key = (generation, key)
    with _RESPONSE_CACHE_LOCK:
        if cache_key in _RESPONSE_CACHE:
            return _RESPONSE_CACHE[cache_key]
    value = producer()
    with _RESPONSE_CACHE_LOCK:
        _RESPONSE_CACHE.clear() if len(_RESPONSE_CACHE) > 32 else None
        _RESPONSE_CACHE[cache_key] = value
    return value

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
        started = time.perf_counter()
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
            engine = build_engine(con)
            tree = craft_tree(con, item_id, quantity, engine=engine)
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
            workshop_context = make_workshop_context(con, use_inventory=False)
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
                qty, actual_spend = strict_budget_plan(con, row["id"], budget, cost["best"], workshop_context)
                budget_profit = qty * net - actual_spend if qty else 0.0
                opportunities.append({**dict(row),**cost,"sale":sale,"net_sale":net,"profit":profit,"roi":roi,
                                      "confidence":confidence,"budget_qty":qty,"budget_spend":actual_spend,
                                      "budget_profit":budget_profit})
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
            invalidate_engine()
            invalidate_response_cache()
            row = con.execute("SELECT * FROM prices WHERE item_id=?", (item_id,)).fetchone()
            unit, lot = best_unit(row)
            con.close()
            return self.send_json({"ok": True, "item_id": item_id, "best_unit": unit, "best_lot": lot})

        if url.path == "/api/inventory":
            data=self.read_json();item_id=int(data.get("item_id") or 0);quantity=max(int(data.get("quantity") or 0),0);con=db()
            if quantity: con.execute("INSERT INTO inventory(item_id,quantity,updated_at) VALUES(?,?,datetime('now','localtime')) ON CONFLICT(item_id) DO UPDATE SET quantity=excluded.quantity,updated_at=excluded.updated_at",(item_id,quantity))
            else: con.execute("DELETE FROM inventory WHERE item_id=?",(item_id,))
            con.commit();con.close();invalidate_response_cache();return self.send_json({"ok":True,"item_id":item_id,"quantity":quantity})

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
            invalidate_response_cache()
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
            invalidate_engine()
            invalidate_response_cache()
            con.close()
            return self.send_json({"ok": True, "count": len(rows)})

        if url.path == "/api/sync":
            if progress.get("status") == "running":
                return self.send_json({"ok": False, "message": "Synchronisation déjà en cours"}, 409)
            progress.update_safe(status="running", message="Démarrage", percent=0)
            invalidate_response_cache()
            threading.Thread(target=sync_data, daemon=True).start()
            return self.send_json({"ok": True})

        return self.send_json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


if __name__ == "__main__":
    init_db()
    print("Dofus Craft Manager V6.2 Architecture & Performance")
    print("Ouvre http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
