"""
Test folding data analysis sub-question answers into big-question answers.

Run with: python tests/test_answer_data_analysis_fold.py
"""

import io
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.services.answers.answer_pdf_importer import (
    DATA_ANALYSIS_BIG_QNO_BASE,
    DATA_ANALYSIS_GROUP_SIZE,
    DATA_ANALYSIS_SUB_QNO_START,
    fold_data_analysis_answers_for_exam,
)


def _make_da_answers() -> dict[int, str]:
    # 4 groups * 5 = 20 answers for Q111-130
    seq = list("ABCDE") * 4  # deterministic
    out: dict[int, str] = {}
    for i, qno in enumerate(range(DATA_ANALYSIS_SUB_QNO_START, DATA_ANALYSIS_SUB_QNO_START + 20)):
        out[qno] = seq[i]
    return out


def test_fold_when_question_count_is_normal_only():
    base = {1: "A", 110: "B"}
    base.update(_make_da_answers())

    folded, errors = fold_data_analysis_answers_for_exam(base, question_count=110)
    assert not errors, f"unexpected fold errors: {errors}"

    # sub-questions removed
    assert all(qno not in folded for qno in range(111, 131))

    # big questions added
    assert folded[DATA_ANALYSIS_BIG_QNO_BASE + 1] == "ABCDE"
    assert len(folded[DATA_ANALYSIS_BIG_QNO_BASE + 1]) == DATA_ANALYSIS_GROUP_SIZE
    assert folded[DATA_ANALYSIS_BIG_QNO_BASE + 4] == "ABCDE"

    # normal questions kept
    assert folded[1] == "A"
    assert folded[110] == "B"


def test_no_fold_when_question_count_includes_sub_questions():
    base = {1: "A"}
    base.update(_make_da_answers())

    folded, errors = fold_data_analysis_answers_for_exam(base, question_count=130)
    assert not errors
    assert folded.get(111) == "A"
    assert (DATA_ANALYSIS_BIG_QNO_BASE + 1) not in folded


def test_incomplete_group_records_error():
    base = _make_da_answers()
    del base[112]

    folded, errors = fold_data_analysis_answers_for_exam(base, question_count=110)
    assert errors, "expected fold errors for missing sub-answer"
    assert (DATA_ANALYSIS_BIG_QNO_BASE + 1) not in folded, "should not create incomplete big-question answer"


def main() -> int:
    test_fold_when_question_count_is_normal_only()
    test_no_fold_when_question_count_includes_sub_questions()
    test_incomplete_group_records_error()
    print("test_answer_data_analysis_fold: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
