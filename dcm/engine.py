import threading
from .economics import best_unit

_ENGINE_LOCK = threading.RLock()
_ENGINE_CACHE = None
_ENGINE_GENERATION = 0

def _build_engine(con):
    price_rows={r["item_id"]:r for r in con.execute("SELECT * FROM prices")}
    unit_prices={item_id:best_unit(row)[0] for item_id,row in price_rows.items()}
    recipes={}
    for r in con.execute("SELECT output_id,ingredient_id,quantity FROM recipes"):
        recipes.setdefault(r["output_id"],[]).append((r["ingredient_id"],r["quantity"]))
    memo={}; visiting=set(); calc_lock=threading.RLock()
    def unsafe_calc(item_id):
        if item_id in memo: return memo[item_id]
        buy=unit_prices.get(item_id); recipe=recipes.get(item_id)
        if item_id in visiting or not recipe:
            result={"buy":buy,"craft":None,"best":buy,
                    "mode":"acheter" if buy is not None else None,
                    "complete":buy is not None}
            memo[item_id]=result; return result
        visiting.add(item_id); total=0.0; complete=True
        for ingredient_id,quantity in recipe:
            ingredient=unsafe_calc(ingredient_id)
            if ingredient["best"] is None: complete=False; break
            total += ingredient["best"]*quantity
        visiting.discard(item_id)
        craft=total if complete else None
        candidates=[x for x in ((buy,"acheter"),(craft,"fabriquer")) if x[0] is not None]
        best,mode=min(candidates,key=lambda x:x[0]) if candidates else (None,None)
        result={"buy":buy,"craft":craft,"best":best,"mode":mode,"complete":complete}
        memo[item_id]=result; return result
    def calc(item_id):
        with calc_lock: return unsafe_calc(item_id)
    return calc,unit_prices,recipes

def invalidate_engine():
    global _ENGINE_CACHE,_ENGINE_GENERATION
    with _ENGINE_LOCK:
        _ENGINE_GENERATION += 1
        _ENGINE_CACHE = None

def engine_generation():
    with _ENGINE_LOCK: return _ENGINE_GENERATION

def build_engine(con):
    global _ENGINE_CACHE
    with _ENGINE_LOCK:
        if _ENGINE_CACHE is None:
            _ENGINE_CACHE=(_ENGINE_GENERATION,_build_engine(con))
        return _ENGINE_CACHE[1]

def craft_tree(con,item_id,quantity=1,depth=0,max_depth=8,path=None,engine=None):
    path=set(path or set())
    row=con.execute("SELECT id,name,level,category,subtype,image FROM items WHERE id=?",(item_id,)).fetchone()
    if not row: return {"id":item_id,"name":f"#{item_id}","quantity":quantity,"missing":True}
    calc,_,recipes=engine or build_engine(con)
    cost=calc(item_id); node={**dict(row),"quantity":quantity,**cost,"children":[]}
    if depth>=max_depth or item_id in path:
        node["truncated"]=True; return node
    if cost["mode"]=="fabriquer" and item_id in recipes:
        next_path=set(path); next_path.add(item_id)
        for ingredient_id,ingredient_qty in recipes[item_id]:
            node["children"].append(craft_tree(con,ingredient_id,quantity*ingredient_qty,depth+1,max_depth,next_path,(calc,{},recipes)))
    return node
