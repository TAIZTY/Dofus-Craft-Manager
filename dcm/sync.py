import json
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from .config import API_BASE,TYPES,normalize_search
from .database import db
from .engine import invalidate_engine

class Progress(dict):
    lock=threading.Lock()
    def update_safe(self,**kwargs):
        with self.lock: super().update(**kwargs)
progress=Progress(status="idle",message="Prêt",percent=0)

def fetch_json(url):
    request=urllib.request.Request(url,headers={"User-Agent":"DofusCraftManager-Salar/6.2","Accept":"application/json","Accept-Encoding":"identity"})
    with urllib.request.urlopen(request,timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))

def sync_data():
    con=db();cur=con.cursor()
    try:
        for index,item_type in enumerate(TYPES,start=1):
            progress.update_safe(status="running",message=f"Téléchargement : {item_type}",percent=int((index-1)/len(TYPES)*100))
            query=urllib.parse.urlencode({"page[size]":-1,"fields[item]":"recipe"})
            payload=fetch_json(f"{API_BASE}/{item_type}?{query}")
            rows=payload.get("items",payload if isinstance(payload,list) else [])
            item_batch=[];recipe_batches=[]
            for item in rows:
                item_id=item.get("ankama_id")
                if item_id is None:continue
                item_kind=item.get("type") or {};image=(item.get("image_urls") or {}).get("icon")
                item_batch.append((item_id,item.get("name",""),normalize_search(item.get("name","")),item.get("level"),item_type,item_kind.get("name") or item_kind.get("name_id"),image))
                recipe_batches.append((item_id,[(r.get("item_ankama_id"),r.get("quantity")) for r in item.get("recipe") or [] if r.get("item_ankama_id") is not None and r.get("quantity")]))
            cur.executemany("""INSERT INTO items(id,name,name_search,level,category,subtype,image) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,name_search=excluded.name_search,level=excluded.level,category=excluded.category,subtype=excluded.subtype,image=excluded.image""",item_batch)
            output_ids=[x[0] for x in recipe_batches]
            if output_ids:
                cur.executemany("DELETE FROM recipes WHERE output_id=?",[(x,) for x in output_ids])
            flat=[(output_id,ing,qty) for output_id,lines in recipe_batches for ing,qty in lines]
            if flat:cur.executemany("INSERT OR REPLACE INTO recipes(output_id,ingredient_id,quantity) VALUES(?,?,?)",flat)
            con.commit()
        cur.execute("INSERT INTO settings(key,value) VALUES('last_sync',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(datetime.now().isoformat(timespec="seconds"),))
        con.commit();invalidate_engine();progress.update_safe(status="done",message="Synchronisation terminée",percent=100)
    except Exception as exc:
        progress.update_safe(status="error",message=f"Erreur : {exc}",percent=0)
    finally:con.close()
