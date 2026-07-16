from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB = DATA_DIR / "dofus_salar.sqlite"
NAMES = DATA_DIR / "items_names.json"
API_BASE = "https://api.dofusdu.de/dofus3/v1/fr/items"
TYPES = ["equipment", "resources", "consumables"]
HIDDEN_NAME_PATTERNS = (
    "(mj)", "timer ", "test ", "debug", "placeholder", "dummy",
    "invisible", "à supprimer", "a supprimer",
)

def normalize_search(value):
    text = str(value or "").casefold()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(ch))

def visible_item_sql(alias="i"):
    clauses = [f"LOWER({alias}.name) NOT LIKE ?" for _ in HIDDEN_NAME_PATTERNS]
    return " AND ".join(clauses), [f"%{x}%" for x in HIDDEN_NAME_PATTERNS]
