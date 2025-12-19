"""Answer key PDF extraction and parsing service."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


DATA_ANALYSIS_SUB_QNO_START = 111
DATA_ANALYSIS_SUB_QNO_END = 130
DATA_ANALYSIS_GROUP_SIZE = 5
DATA_ANALYSIS_BIG_QNO_BASE = 1000  # 1001-1004
DATA_ANALYSIS_GROUP_COUNT = (
    (DATA_ANALYSIS_SUB_QNO_END - DATA_ANALYSIS_SUB_QNO_START + 1) // DATA_ANALYSIS_GROUP_SIZE
)
DATA_ANALYSIS_BIG_QNO_MIN = DATA_ANALYSIS_BIG_QNO_BASE + 1
DATA_ANALYSIS_BIG_QNO_MAX = DATA_ANALYSIS_BIG_QNO_BASE + DATA_ANALYSIS_GROUP_COUNT

_HALFWIDTH_TRANS = str.maketrans({
    **{chr(ord("０") + i): chr(ord("0") + i) for i in range(10)},
    **{chr(ord("Ａ") + i): chr(ord("A") + i) for i in range(26)},
    **{chr(ord("ａ") + i): chr(ord("a") + i) for i in range(26)},
    "（": "(", "）": ")", "【": "[", "】": "]",
    "，": ",", "。": ".", "：": ":", "；": ";",
    "－": "-", "—": "-", "–": "-", "～": "-",
})


def _to_halfwidth(s: str) -> str:
    return (s or "").translate(_HALFWIDTH_TRANS)


def _extract_answer_letters(s: str, *, allowed_re: str = "A-E") -> str:
    """Extract allowed answer letters from text (default A-E)."""
    if not s:
        return ""
    txt = _to_halfwidth(str(s)).upper()
    return re.sub(rf"[^{allowed_re}]", "", txt)


def is_data_analysis_sub_qno(qno: int) -> bool:
    return DATA_ANALYSIS_SUB_QNO_START <= int(qno) <= DATA_ANALYSIS_SUB_QNO_END


def is_data_analysis_big_qno(qno: int) -> bool:
    return DATA_ANALYSIS_BIG_QNO_MIN <= int(qno) <= DATA_ANALYSIS_BIG_QNO_MAX


def fold_data_analysis_answers_for_exam(
    answer_map: Dict[int, str],
    *,
    question_count: int = 0,
    force: bool = False,
) -> Tuple[Dict[int, str], List[str]]:
    """
    Fold data analysis sub-question answers (Q111-130) into big-question answers (Q1001-1004).

    When `question_count` only counts normal questions (e.g. 110), answer keys often still use
    Q111-130 for the 20 sub-questions. In DB we store 4 big questions as Q1001-1004, each
    containing 5 sub-answers.

    Returns:
        (new_answer_map, errors)

    Notes:
        - Only folds when `question_count` is non-zero AND less than `DATA_ANALYSIS_SUB_QNO_START`.
        - Requires each big question to have all 5 sub-answers; otherwise records an error and
          does not create that big-question answer.
        - Folded sub-question keys (111-130) are removed from the returned map.
    """
    errs: List[str] = []

    # Heuristic: in the new schema, question_count is the count of normal questions (<=110).
    if not force and (not question_count or int(question_count) >= DATA_ANALYSIS_SUB_QNO_START):
        return dict(answer_map), errs

    out: Dict[int, str] = dict(answer_map)
    groups: Dict[int, List[Optional[str]]] = {}

    for qno in range(DATA_ANALYSIS_SUB_QNO_START, DATA_ANALYSIS_SUB_QNO_END + 1):
        if qno not in out:
            continue
        raw = out.get(qno, "")
        letters = _extract_answer_letters(raw)
        if not letters:
            errs.append(f"Q{qno}: invalid answer {raw!r}")
            del out[qno]
            continue
        ch = letters[0]

        big_order = (qno - DATA_ANALYSIS_SUB_QNO_START) // DATA_ANALYSIS_GROUP_SIZE + 1
        big_qno = DATA_ANALYSIS_BIG_QNO_BASE + big_order
        idx = (qno - DATA_ANALYSIS_SUB_QNO_START) % DATA_ANALYSIS_GROUP_SIZE
        slots = groups.setdefault(big_qno, [None] * DATA_ANALYSIS_GROUP_SIZE)

        prev = slots[idx]
        if prev and prev != ch:
            errs.append(f"Q{qno}: duplicate (kept {prev})")
        else:
            slots[idx] = ch
        del out[qno]

    for big_qno, slots in groups.items():
        big_order = int(big_qno) - DATA_ANALYSIS_BIG_QNO_BASE
        missing_qnos = [
            DATA_ANALYSIS_SUB_QNO_START + (big_order - 1) * DATA_ANALYSIS_GROUP_SIZE + idx
            for idx, v in enumerate(slots)
            if not v
        ]
        if missing_qnos:
            missing_str = ", ".join(f"Q{n}" for n in missing_qnos)
            errs.append(f"Q{big_qno}: missing sub-answers ({missing_str})")
            continue

        folded = "".join([v or "" for v in slots])
        existing = out.get(big_qno)
        if existing:
            existing_letters = _extract_answer_letters(existing)
            if existing_letters[:DATA_ANALYSIS_GROUP_SIZE] != folded:
                errs.append(f"Q{big_qno}: conflict with existing answer {existing!r} (kept existing)")
                continue

        out[big_qno] = folded

    return out, errs


def normalize_exam_name(name: str) -> str:
    """Normalize exam name for fuzzy matching."""
    s = _to_halfwidth(name).strip()
    if s.lower().endswith(".pdf"):
        s = s[:-4]
    if "__" in s:
        s = s.split("__", 1)[0]
    s = s.lower()
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)
    return s


def extract_variant_index(name: str) -> Optional[int]:
    """Extract exam variant index from name patterns."""
    s = _to_halfwidth(name).strip()
    if s.lower().endswith(".pdf"):
        s = s[:-4]
    if "__" in s:
        s = s.split("__", 1)[0]
    patterns = [
        r"[\(（]\s*(\d{1,3})\s*[\)）]",
        r"冲刺\s*(\d{1,3})",
        r"(?:^|[_\-\s])(\d{1,3})\s*$",
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


@dataclass(frozen=True)
class ParsedAnswerKey:
    answers: Dict[int, str]
    errors: List[str]


def parse_answer_key_text(text: str) -> ParsedAnswerKey:
    """Parse answer key text with format like '1--5 DDCCA'."""
    s = _to_halfwidth(text).upper()
    s = re.sub(r"[~～－—–−﹣]", "-", s)

    answers: Dict[int, str] = {}
    errors: List[str] = []

    range_re = re.compile(
        r"(?P<start>\d{1,3})\s*-\s*-?\s*(?P<end>\d{1,3})\s*(?P<answers>(?:[A-E](?:\s*[A-E]){0,500}))",
        re.IGNORECASE,
    )

    for m in range_re.finditer(s):
        try:
            start, end = int(m.group("start")), int(m.group("end"))
        except ValueError:
            continue

        if start <= 0 or end <= 0 or end < start or (end - start + 1) > 500:
            errors.append(f"Invalid range: {m.group(0)!r}")
            continue

        raw = m.group("answers")
        letters = re.sub(r"[^A-E]", "", raw.upper())
        expected = end - start + 1

        if len(letters) < expected:
            errors.append(f"Range {start}-{end} expects {expected}, got {len(letters)}")
            continue

        if len(letters) > expected:
            letters = letters[:expected]

        for i, ch in enumerate(letters):
            qno = start + i
            prev = answers.get(qno)
            if prev and prev != ch:
                errors.append(f"Duplicate Q{qno}: kept {prev}")
                continue
            answers[qno] = ch

    single_re = re.compile(r"(?<!\d)(?P<qno>\d{1,3})\s*[:：]?\s*(?P<answer>[A-E])\b", re.IGNORECASE)
    for m in single_re.finditer(s):
        try:
            qno = int(m.group("qno"))
        except ValueError:
            continue
        if qno > 0 and qno not in answers:
            answers[qno] = m.group("answer").upper()

    return ParsedAnswerKey(answers=answers, errors=errors)


def extract_text_from_pdf(pdf: Path | bytes | bytearray | memoryview) -> str:
    """Extract text from PDF using PyMuPDF.

    Accepts either a filesystem path or in-memory PDF bytes.
    """
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError("PyMuPDF not installed (pip install pymupdf)") from e

    if isinstance(pdf, Path):
        if not pdf.exists():
            raise FileNotFoundError(str(pdf))
        doc = fitz.open(str(pdf))
    else:
        data = pdf if isinstance(pdf, bytes) else bytes(pdf)
        doc = fitz.open(stream=data, filetype="pdf")
    try:
        parts = [doc[i].get_text("text") or "" for i in range(len(doc))]
        return "\n".join(parts)
    finally:
        doc.close()


@dataclass(frozen=True)
class ExamInfo:
    id: int
    exam_dir_name: str
    display_name: Optional[str]
    question_count: int


@dataclass(frozen=True)
class MatchCandidate:
    exam: ExamInfo
    score: float


@dataclass(frozen=True)
class MatchResult:
    exam: Optional[ExamInfo]
    score: float
    candidates: List[MatchCandidate]
    reason: str


def match_exam_for_pdf(
    pdf_filename: str,
    exams: Sequence[ExamInfo],
    *,
    extracted_max_qno: Optional[int] = None,
    min_score: float = 0.62,
    ambiguity_delta: float = 0.02,
) -> MatchResult:
    """Match PDF filename to exam using fuzzy matching."""
    pdf_key = normalize_exam_name(pdf_filename)
    pdf_idx = extract_variant_index(pdf_filename)

    scored: List[MatchCandidate] = []
    for ex in exams:
        ex_name = ex.display_name or ex.exam_dir_name
        ex_key = normalize_exam_name(ex_name)

        name_score = difflib.SequenceMatcher(None, pdf_key, ex_key).ratio()

        idx_score = 0.0
        ex_idx = extract_variant_index(ex.exam_dir_name) or extract_variant_index(ex.display_name or "")
        if pdf_idx is not None and ex_idx is not None and pdf_idx == ex_idx:
            idx_score = 1.0

        count_score = 0.0
        if extracted_max_qno and ex.question_count:
            diff = abs(int(ex.question_count) - int(extracted_max_qno))
            count_score = max(0.0, 1.0 - (diff / 50.0))

        score = 0.65 * name_score + 0.25 * count_score + 0.10 * idx_score
        scored.append(MatchCandidate(exam=ex, score=score))

    scored.sort(key=lambda c: c.score, reverse=True)
    top = scored[0] if scored else None

    if not top or top.score < min_score:
        return MatchResult(
            exam=None,
            score=top.score if top else 0.0,
            candidates=scored[:3],
            reason=f"No match above threshold ({min_score:.2f})",
        )

    if len(scored) > 1 and scored[1].score >= (top.score - ambiguity_delta):
        return MatchResult(
            exam=None,
            score=top.score,
            candidates=scored[:3],
            reason="Ambiguous match (top candidates too close)",
        )

    return MatchResult(
        exam=top.exam,
        score=top.score,
        candidates=scored[:3],
        reason="ok",
    )
