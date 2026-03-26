"""Question service.

Provides:
  - get_questions_for_team(team_id, set_assigned) → client-safe question list
  - calculate_score(team_id, set_assigned, submitted_answers) → int
"""
import hashlib
import random
import logging
from typing import Any

from app.models.db import get_supabase

log = logging.getLogger(__name__)

_LABELS = ["A", "B", "C", "D"]
_OPTION_KEYS = ["option_a", "option_b", "option_c", "option_d"]


# ---------------------------------------------------------------------------
# Seeded RNG helpers
# ---------------------------------------------------------------------------

def _make_seed(*parts: str) -> int:
    """Deterministic integer seed from arbitrary string parts."""
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(raw.encode()).hexdigest(), 16) % (2**32)


def _shuffled_indices(n: int, seed: int) -> list[int]:
    """Return a shuffled list of indices 0..n-1 using the given seed."""
    rng = random.Random(seed)
    idxs = list(range(n))
    rng.shuffle(idxs)
    return idxs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_questions_for_team(team_id: str, set_assigned: str) -> list[dict[str, Any]]:
    """Fetch and shuffle questions for a team.

    Question ORDER is shuffled using team_id as seed (stable across reloads).
    Option POSITIONS within each question are shuffled using team_id+question_id
    as seed, and the correct answer label is remapped accordingly.

    The returned dicts never include correct_answer.

    Args:
        team_id: Team identifier (used as shuffle seed).
        set_assigned: Question set ('A', 'B', or 'C').

    Returns:
        List of question dicts:
          {
            "question_number": int (1-indexed),
            "question_id":     int,
            "question_text":   str,
            "options":         [{"label": "A"|"B"|"C"|"D", "text": str}, ...],
          }

    Raises:
        RuntimeError: If no questions are found for the given set.
    """
    sb = get_supabase()
    try:
        result = (
            sb.table("questions")
            .select("id,question_text,option_a,option_b,option_c,option_d,correct_answer,base_order")
            .eq("set_id", set_assigned)
            .order("base_order")
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch questions for set {set_assigned}: {exc}") from exc

    rows: list[dict] = result.data or []
    if not rows:
        raise RuntimeError(f"No questions found for set '{set_assigned}'.")

    # ── Shuffle question order (team-level seed) ──────────────────────────
    order_seed = _make_seed(team_id, set_assigned, "order")
    order_idxs = _shuffled_indices(len(rows), order_seed)
    shuffled_rows = [rows[i] for i in order_idxs]

    output: list[dict] = []
    for q_num, row in enumerate(shuffled_rows, start=1):
        q_id = row["id"]

        # Build the 4-element option list in original DB order
        original_options = [row.get(k, "") or "" for k in _OPTION_KEYS]
        correct_db_label = (row.get("correct_answer") or "A").upper()
        correct_original_idx = _LABELS.index(correct_db_label)   # 0-3

        # ── Shuffle option positions (per question + team seed) ─────────
        opt_seed = _make_seed(team_id, str(q_id), "options")
        opt_idxs = _shuffled_indices(4, opt_seed)
        # opt_idxs[i] = original index that ends up at shuffled position i
        shuffled_option_texts = [original_options[opt_idxs[i]] for i in range(4)]

        # Find where the correct answer ended up after shuffling
        # opt_idxs[new_position] == correct_original_idx
        new_correct_pos = opt_idxs.index(correct_original_idx)
        # We store this mapping server-side only; it is NOT sent to the client

        output.append(
            {
                "question_number":   q_num,
                "question_id":       q_id,
                "question_text":     row["question_text"],
                "options": [
                    {"label": _LABELS[i], "text": shuffled_option_texts[i]}
                    for i in range(4)
                ],
                # Internal — used by calculate_score, stripped before HTTP response
                "_correct_shuffled_label": _LABELS[new_correct_pos],
            }
        )

    return output


def calculate_score(
    team_id: str,
    set_assigned: str,
    submitted_answers: dict[str, str],
) -> int:
    """Score a team's submitted answers.

    Args:
        team_id: Team identifier (needed to reproduce the same shuffle).
        set_assigned: Question set letter.
        submitted_answers: {str(question_id): selected_label (A/B/C/D)}

    Returns:
        Number of correct answers.
    """
    if not submitted_answers:
        return 0

    questions = get_questions_for_team(team_id, set_assigned)

    score = 0
    for q in questions:
        q_id_str = str(q["question_id"])
        selected  = (submitted_answers.get(q_id_str) or "").upper()
        correct   = q["_correct_shuffled_label"]
        if selected == correct:
            score += 1

    return score
