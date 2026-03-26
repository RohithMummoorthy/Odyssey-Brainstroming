import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv; load_dotenv()
from app.models.db import get_supabase
sb = get_supabase()
for s in ("A", "B", "C"):
    res = sb.table("questions").select("id").eq("set_id", s).execute()
    print(f"Set {s}: {len(res.data or [])} questions")
