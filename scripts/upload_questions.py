#!/usr/bin/env python3
"""Upload quiz questions from JSON files to the Supabase questions table.

Reads:
    questions/set_a.json  →  set_id = 'A'
    questions/set_b.json  →  set_id = 'B'
    questions/set_c.json  →  set_id = 'C'

Each JSON file must be an array of objects with the keys:
    question_text, option_a, option_b, option_c, option_d, correct_answer

Usage:
    python scripts/upload_questions.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.models.db import get_supabase

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "questions"
SETS = [
    ("A", QUESTIONS_DIR / "set_a.json"),
    ("B", QUESTIONS_DIR / "set_b.json"),
    ("C", QUESTIONS_DIR / "set_c.json"),
]
REQUIRED_KEYS = {
    "question_text", "option_a", "option_b",
    "option_c", "option_d", "correct_answer",
}
BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path, set_id: str) -> list[dict]:
    """Load and validate a questions JSON file."""
    if not path.exists():
        raise FileNotFoundError(
            f"Question file not found: {path}\n"
            f"Create the file or copy a sample from questions/set_a.json"
        )

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"{path.name}: expected a non-empty JSON array.")

    rows = []
    for idx, item in enumerate(data, start=1):
        missing = REQUIRED_KEYS - set(item.keys())
        if missing:
            raise ValueError(
                f"{path.name}, item {idx}: missing keys {missing}"
            )

        answer = item["correct_answer"].upper()
        if answer not in ("A", "B", "C", "D"):
            raise ValueError(
                f"{path.name}, item {idx}: correct_answer must be A/B/C/D, got '{answer}'"
            )

        rows.append(
            {
                "set_id":        set_id,
                "question_text": item["question_text"],
                "option_a":      item.get("option_a"),
                "option_b":      item.get("option_b"),
                "option_c":      item.get("option_c"),
                "option_d":      item.get("option_d"),
                "correct_answer": answer,
                "base_order":    idx,
            }
        )

    return rows


def upload_rows(sb, set_id: str, rows: list[dict]) -> int:
    """Batch-insert question rows, returns count inserted."""
    inserted = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        try:
            sb.table("questions").insert(batch).execute()
            inserted += len(batch)
        except Exception as exc:
            print(
                f"  ✗  Set {set_id} batch {start + 1}–{start + len(batch)}: {exc}",
                file=sys.stderr,
            )
            raise
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== upload_questions.py ===")
    print("Connecting to Supabase…")
    sb = get_supabase()
    print("Connected.\n")

    total = 0
    errors = []

    for set_id, path in SETS:
        print(f"Processing Set {set_id} ({path.name})…")
        try:
            rows = load_json(path, set_id)
            count = upload_rows(sb, set_id, rows)
            print(f"  ✓  Set {set_id}: {count} questions inserted")
            total += count
        except FileNotFoundError as exc:
            print(f"  ⚠  Skipping Set {set_id}: {exc}", file=sys.stderr)
            errors.append(set_id)
        except Exception as exc:
            print(f"  ✗  Set {set_id} failed: {exc}", file=sys.stderr)
            errors.append(set_id)

    print(f"\n{'=' * 40}")
    print(f"Total questions inserted: {total}")
    if errors:
        print(f"Sets with errors/skipped: {', '.join(errors)}", file=sys.stderr)
    print("✅  upload_questions completed.")


if __name__ == "__main__":
    main()
