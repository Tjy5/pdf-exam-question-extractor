#!/usr/bin/env python3
"""
Backfill chat session titles using the configured title model.

This script updates rows in data/tasks.db (chat_sessions.title) where the title is
missing or generic (e.g. "对话") and the session has at least one user message.

Requires:
  - backend/.env configured with AI_PROVIDER=openai_compatible, AI_API_KEY, AI_BASE_URL
  - AI_TITLE_MODEL set (and optionally AI_TITLE_TEMPERATURE/AI_TITLE_MAX_TOKENS)
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
import sys
from typing import Optional
from pathlib import Path

# Ensure project root is importable when running as a standalone script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.services.ai import ChatMessage, OpenAICompatibleProvider, AIProviderError  # noqa: E402
from backend.src.web.config import config  # noqa: E402
from backend.src.web.routers.chat import (  # noqa: E402
    _fallback_session_title,
    _normalize_session_title,
    _strip_hint_mode_note,
)


GENERIC_TITLES = {"", "对话", "新对话"}


def now_iso8601() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def is_generic_title(title: Optional[str]) -> bool:
    if title is None:
        return True
    return str(title).strip() in GENERIC_TITLES


def preview(text: str, limit: int = 70) -> str:
    t = " ".join((text or "").split())
    return (t[:limit] + "…") if len(t) > limit else t


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    user_id: str
    exam_id: int
    question_no: int
    title: Optional[str]


async def generate_title(
    ai: OpenAICompatibleProvider,
    *,
    question_no: int,
    user_text: str,
    ocr_text: Optional[str],
) -> str:
    user_text_clean = " ".join((user_text or "").split()).strip()
    if not user_text_clean:
        return _fallback_session_title(question_no, "")

    ocr_snippet = ""
    if ocr_text and isinstance(ocr_text, str):
        o = " ".join(ocr_text.split()).strip()
        if o:
            ocr_snippet = o[:200]

    sys_msg = "你是一个中文助手，擅长为学习类对话生成简短标题。"
    prompt = (
        "请基于用户的提问生成一个中文标题。\n"
        "要求：\n"
        "- 只输出标题本身，不要解释，不要换行，不要引号\n"
        "- 尽量 8~16 个汉字，最多 20 个字符\n"
        "- 不要包含“对话/聊天/会话”等泛词\n"
        "- 不要包含正确答案字母或泄露答案\n\n"
        f"题号：第 {int(question_no)} 题\n"
        + (f"题目片段：{ocr_snippet}\n" if ocr_snippet else "")
        + f"用户提问：{user_text_clean}\n"
    )

    parts: list[str] = []
    async for chunk in ai.stream_chat(
        [ChatMessage(role="system", content=sys_msg), ChatMessage(role="user", content=prompt)],
        model=config.ai_title_model,
        temperature=float(getattr(config, "ai_title_temperature", 0.2) or 0.2),
        max_tokens=int(getattr(config, "ai_title_max_tokens", 64) or 64),
    ):
        if chunk.content:
            parts.append(chunk.content)
        if chunk.finish_reason:
            break

    raw = "".join(parts)
    normalized = _normalize_session_title(raw)
    return normalized or _fallback_session_title(question_no, user_text_clean)


async def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Backfill chat session titles")
    parser.add_argument("--db", default="data/tasks.db", help="SQLite DB path (default: data/tasks.db)")
    parser.add_argument("--user-id", default="", help="Only process sessions for this user_id")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of sessions processed (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    parser.add_argument("--force", action="store_true", help="Overwrite existing (non-generic) titles")
    args = parser.parse_args(argv)

    if not config.ai_title_model:
        print("[Error] AI_TITLE_MODEL is empty; set it in backend/.env (AI_TITLE_MODEL=...)")
        return 2

    if not (config.ai_provider == "openai_compatible" and bool(config.ai_api_key)):
        print("[Error] AI_PROVIDER/openai key not configured; cannot call title model.")
        print(f"        AI_PROVIDER={config.ai_provider}, has_key={bool(config.ai_api_key)}")
        return 2

    # Connect DB
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    where_user = ""
    params: list[object] = []
    if args.user_id:
        where_user = "AND cs.user_id = ?"
        params.append(args.user_id)

    # Only sessions with at least one user message
    rows = cur.execute(
        f"""
        SELECT cs.session_id, cs.user_id, cs.exam_id, cs.question_no, cs.title
        FROM chat_sessions cs
        WHERE 1=1
          {where_user}
          AND EXISTS (
            SELECT 1 FROM chat_messages cm
            WHERE cm.session_id = cs.session_id AND cm.role = 'user'
          )
        ORDER BY (cs.last_message_at IS NULL) ASC, cs.last_message_at DESC, cs.updated_at DESC
        """,
        tuple(params),
    ).fetchall()

    sessions: list[SessionRow] = [
        SessionRow(
            session_id=str(r["session_id"]),
            user_id=str(r["user_id"]),
            exam_id=int(r["exam_id"]),
            question_no=int(r["question_no"]),
            title=(str(r["title"]) if r["title"] is not None else None),
        )
        for r in rows
        if args.force or is_generic_title(r["title"])
    ]

    if args.limit and args.limit > 0:
        sessions = sessions[: args.limit]

    print(
        f"[Config] title_model={config.ai_title_model}, temp={getattr(config,'ai_title_temperature',None)}, "
        f"max_tokens={getattr(config,'ai_title_max_tokens',None)}"
    )
    print(f"[DB] sessions eligible: {len(sessions)} (user filter={args.user_id or 'ALL'})")

    if not sessions:
        return 0

    ai = OpenAICompatibleProvider(
        base_url=config.ai_base_url,
        api_key=config.ai_api_key,
        default_model=config.ai_model,
        timeout=config.ai_timeout,
    )

    updated = 0
    failed = 0
    for i, s in enumerate(sessions, start=1):
        last_user_row = cur.execute(
            "SELECT content FROM chat_messages WHERE session_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (s.session_id,),
        ).fetchone()
        if not last_user_row or last_user_row["content"] is None:
            continue

        user_text, _ = _strip_hint_mode_note(str(last_user_row["content"] or ""))

        ocr_row = cur.execute(
            "SELECT ocr_text FROM exam_questions WHERE exam_id = ? AND question_no = ?",
            (s.exam_id, s.question_no),
        ).fetchone()
        ocr_text = str(ocr_row["ocr_text"]) if (ocr_row and ocr_row["ocr_text"] is not None) else None

        try:
            title = await generate_title(ai, question_no=s.question_no, user_text=user_text, ocr_text=ocr_text)
        except AIProviderError as e:
            failed += 1
            print(f"[{i}/{len(sessions)}] FAIL session={s.session_id} err={e}")
            continue
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(sessions)}] FAIL session={s.session_id} err={e}")
            continue

        title = _normalize_session_title(title) or _fallback_session_title(s.question_no, user_text)
        print(f"[{i}/{len(sessions)}] OK  {preview(user_text)} -> {title}")

        if not args.dry_run:
            cur.execute(
                "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                (title, now_iso8601(), s.session_id),
            )
            con.commit()
            updated += 1

    print(f"[Done] updated={updated}, failed={failed}, dry_run={args.dry_run}")
    return 0 if failed == 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
