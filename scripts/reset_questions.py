import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv; load_dotenv()
from app.models.db import get_supabase
sb = get_supabase()

# Delete all questions (might need multiple calls if large, but there's only 180 max)
sb.table("questions").delete().neq("id", 0).execute()
print("Cleared all questions from table.")
