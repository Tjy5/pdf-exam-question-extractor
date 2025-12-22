"""
Wrong Notebook API Router

Provides endpoints for wrong question management, including:
- Image upload and AI analysis
- Wrong question CRUD operations
- Knowledge tag management
- Practice generation
"""

import logging
import json
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...db.connection import get_db_manager
from ...services.ai import (
    OpenAICompatibleProvider,
    MockProvider,
    ChatMessage,
    build_analyze_prompt,
    build_similar_prompt,
    build_reanswer_prompt,
    parse_analyze_response,
)
from ..config import config
from ..dependencies import get_current_user, verify_owner

router = APIRouter(prefix="/api/wrong-notebook", tags=["wrong-notebook"])
logger = logging.getLogger(__name__)


# ==================== Request/Response Models ====================

class AnalyzeRequest(BaseModel):
    """Image analysis request."""
    image_base64: str = Field(..., description="Base64 encoded image")
    mime_type: str = Field(default="image/jpeg", description="Image MIME type")
    subject: Optional[str] = Field(default=None, description="Subject hint")


class WrongItemCreate(BaseModel):
    """Create wrong question request."""
    source_type: str = Field(default="upload", pattern="^(exam|upload)$")
    exam_id: Optional[int] = None
    question_no: Optional[int] = None
    user_answer: Optional[str] = None
    original_image: Optional[str] = None
    ai_question_text: Optional[str] = None
    ai_answer_text: Optional[str] = None
    ai_analysis: Optional[str] = None
    subject: Optional[str] = None
    source_name: Optional[str] = None
    error_type: Optional[str] = None
    user_notes: Optional[str] = None
    tag_ids: List[str] = []


class WrongItemUpdate(BaseModel):
    """Update wrong question request."""
    mastery_level: Optional[int] = Field(default=None, ge=0, le=2)
    user_notes: Optional[str] = None
    tag_ids: Optional[List[str]] = None
    ai_question_text: Optional[str] = None
    ai_answer_text: Optional[str] = None
    ai_analysis: Optional[str] = None


class TagCreate(BaseModel):
    """Create tag request."""
    name: str
    subject: str
    parent_id: Optional[str] = None


class PracticeGenerateRequest(BaseModel):
    """Generate practice question request."""
    question_text: str
    knowledge_points: List[str] = []
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard|harder)$")


class ReanswerRequest(BaseModel):
    """Re-answer question request."""
    question_text: str
    subject: Optional[str] = None
    image_base64: Optional[str] = None


# ==================== Helper Functions ====================

def _get_ai_provider():
    """Get AI Provider instance."""
    if config.ai_provider == "openai_compatible" and config.ai_api_key:
        return OpenAICompatibleProvider(
            base_url=config.ai_base_url,
            api_key=config.ai_api_key,
            default_model=config.ai_model,
            timeout=config.ai_timeout
        )
    return MockProvider()


async def _ensure_user(user_id: str):
    """Ensure user exists in database."""
    db = get_db_manager()
    async with db.transaction():
        existing = await db.fetch_one(
            "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
        )
        if not existing:
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            await db.execute(
                "INSERT INTO users (user_id, created_at) VALUES (?, ?)",
                (user_id, now)
            )


def _generate_id() -> str:
    """Generate unique ID."""
    return str(uuid.uuid4())


# ==================== Image Analysis ====================

@router.post("/analyze")
async def analyze_image(request: AnalyzeRequest):
    """
    Upload image for AI analysis.

    Returns SSE stream:
    - {"type": "start"} - stream started
    - {"type": "token", "kind": "reasoning", "content": "..."} - thinking process
    - {"type": "token", "kind": "content", "content": "..."} - main content
    - {"type": "done", "result": {...}} - complete with parsed result
    - {"type": "error", "message": "..."} - error

    Legacy format (backward compatible):
    - {"type": "content", "text": "..."} - incremental text
    """
    provider = _get_ai_provider()
    system_prompt = build_analyze_prompt(request.subject)

    user_content = [
        {"type": "text", "text": "请分析这道错题图片"},
        {"type": "image_url", "image_url": {"url": f"data:{request.mime_type};base64,{request.image_base64}"}},
    ]
    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_content),
    ]

    async def event_generator():
        full_content_text = ""
        try:
            yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"

            async for chunk in provider.stream_chat(
                messages,
                temperature=0.7,
                max_tokens=4000
            ):
                if chunk.content:
                    if chunk.kind == "reasoning":
                        yield f"data: {json.dumps({'type': 'token', 'kind': 'reasoning', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                    elif chunk.kind == "content" or chunk.kind is None:
                        full_content_text += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'kind': 'content', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                if chunk.finish_reason:
                    break

            result = parse_analyze_response(full_content_text)
            yield f"data: {json.dumps({'type': 'done', 'result': result.model_dump()}, ensure_ascii=False)}\n\n"

        except Exception:
            logger.exception("Wrong notebook analyze stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Analysis failed'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ==================== Wrong Items CRUD ====================

@router.get("/items")
async def list_wrong_items(
    current_user: str = Depends(get_current_user),
    source_type: Optional[str] = None,
    subject: Optional[str] = None,
    mastery_level: Optional[int] = None,
    tag_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100)
):
    """Get wrong question list with filtering."""
    db = get_db_manager()

    conditions = ["w.user_id = ?"]
    params: List = [current_user]

    if source_type:
        conditions.append("w.source_type = ?")
        params.append(source_type)

    if subject:
        conditions.append("w.subject = ?")
        params.append(subject)

    if mastery_level is not None:
        conditions.append("w.mastery_level = ?")
        params.append(mastery_level)

    if tag_id:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM wrong_question_tags wt
                WHERE wt.wrong_question_id = w.id AND wt.tag_id = ?
            )
        """)
        params.append(tag_id)

    if search:
        conditions.append("(w.ai_question_text LIKE ? OR w.user_notes LIKE ?)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * page_size

    async with db.transaction():
        # Query total count
        count_row = await db.fetch_one(
            f"SELECT COUNT(*) as total FROM user_wrong_questions w WHERE {where_clause}",
            tuple(params)
        )
        total = count_row["total"] if count_row else 0

        # Query data
        rows = await db.fetch_all(f"""
            SELECT w.*
            FROM user_wrong_questions w
            WHERE {where_clause}
            ORDER BY w.updated_at DESC
            LIMIT ? OFFSET ?
        """, (*params, page_size, offset))

        # Get tags for each item
        items = []
        for row in rows:
            tags = await db.fetch_all("""
                SELECT t.id, t.name, t.subject
                FROM knowledge_tags t
                INNER JOIN wrong_question_tags wt ON t.id = wt.tag_id
                WHERE wt.wrong_question_id = ?
            """, (row["id"],))

            item = dict(row)
            item["tags"] = [dict(t) for t in tags]
            items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.post("/items")
async def create_wrong_item(
    item: WrongItemCreate,
    current_user: str = Depends(get_current_user),
):
    """Save wrong question."""
    db = get_db_manager()

    await _ensure_user(current_user)
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    async with db.transaction():
        result = await db.execute("""
            INSERT INTO user_wrong_questions (
                user_id, source_type, exam_id, question_no, user_answer,
                original_image, ai_question_text, ai_answer_text, ai_analysis,
                subject, source_name, error_type, user_notes,
                marked_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            current_user, item.source_type, item.exam_id, item.question_no,
            item.user_answer, item.original_image, item.ai_question_text,
            item.ai_answer_text, item.ai_analysis, item.subject,
            item.source_name, item.error_type, item.user_notes, now, now
        ))

        item_id = result.lastrowid

        # Associate tags
        for tag_id in item.tag_ids:
            await db.execute(
                "INSERT OR IGNORE INTO wrong_question_tags (wrong_question_id, tag_id) VALUES (?, ?)",
                (item_id, tag_id)
            )

    return {"id": item_id, "created_at": now}


@router.get("/items/{item_id}")
async def get_wrong_item(item_id: int, current_user: str = Depends(get_current_user)):
    """Get single wrong question detail."""
    db = get_db_manager()

    async with db.transaction():
        row = await db.fetch_one(
            "SELECT * FROM user_wrong_questions WHERE id = ?",
            (item_id,)
        )

        if not row:
            raise HTTPException(status_code=404, detail="错题不存在")
        verify_owner(row["user_id"], current_user)

        tags = await db.fetch_all("""
            SELECT t.id, t.name, t.subject
            FROM knowledge_tags t
            INNER JOIN wrong_question_tags wt ON t.id = wt.tag_id
            WHERE wt.wrong_question_id = ?
        """, (item_id,))

    result = dict(row)
    result["tags"] = [dict(t) for t in tags]
    return result


@router.patch("/items/{item_id}")
async def update_wrong_item(
    item_id: int,
    update: WrongItemUpdate,
    current_user: str = Depends(get_current_user),
):
    """Update wrong question."""
    db = get_db_manager()

    async with db.transaction():
        existing = await db.fetch_one(
            "SELECT id, user_id FROM user_wrong_questions WHERE id = ?",
            (item_id,)
        )
        if not existing:
            raise HTTPException(status_code=404, detail="错题不存在")
        verify_owner(existing["user_id"], current_user)

        # Build update fields
        updates = []
        params = []

        if update.mastery_level is not None:
            updates.append("mastery_level = ?")
            params.append(update.mastery_level)

        if update.user_notes is not None:
            updates.append("user_notes = ?")
            params.append(update.user_notes)

        if update.ai_question_text is not None:
            updates.append("ai_question_text = ?")
            params.append(update.ai_question_text)

        if update.ai_answer_text is not None:
            updates.append("ai_answer_text = ?")
            params.append(update.ai_answer_text)

        if update.ai_analysis is not None:
            updates.append("ai_analysis = ?")
            params.append(update.ai_analysis)

        if updates:
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            updates.append("updated_at = ?")
            params.append(now)
            params.append(item_id)

            await db.execute(
                f"UPDATE user_wrong_questions SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )

        # Update tag associations
        if update.tag_ids is not None:
            await db.execute(
                "DELETE FROM wrong_question_tags WHERE wrong_question_id = ?",
                (item_id,)
            )
            for tag_id in update.tag_ids:
                await db.execute(
                    "INSERT OR IGNORE INTO wrong_question_tags (wrong_question_id, tag_id) VALUES (?, ?)",
                    (item_id, tag_id)
                )

    return {"success": True}


@router.delete("/items/{item_id}")
async def delete_wrong_item(item_id: int, current_user: str = Depends(get_current_user)):
    """Delete wrong question."""
    db = get_db_manager()

    async with db.transaction():
        existing = await db.fetch_one(
            "SELECT user_id FROM user_wrong_questions WHERE id = ?",
            (item_id,)
        )
        if not existing:
            raise HTTPException(status_code=404, detail="错题不存在")
        verify_owner(existing["user_id"], current_user)

        await db.execute(
            "DELETE FROM user_wrong_questions WHERE id = ?",
            (item_id,)
        )

    return {"success": True}


# ==================== Tags Management ====================

@router.get("/tags")
async def list_tags(
    subject: Optional[str] = None,
    user_id: Optional[str] = None,
    include_system: bool = True,
    current_user: str = Depends(get_current_user),
):
    """Get tag list (tree structure)."""
    db = get_db_manager()

    conditions = []
    params = []

    if subject:
        conditions.append("subject = ?")
        params.append(subject)

    # System tags + user custom tags
    user_conditions = []
    if include_system:
        user_conditions.append("is_system = 1")

    # Determine which user's tags to include
    target_user_id = user_id
    if not include_system and not target_user_id:
        # When only custom tags requested, default to current user
        target_user_id = current_user

    if target_user_id:
        verify_owner(target_user_id, current_user)
        user_conditions.append("user_id = ?")
        params.append(target_user_id)

    if user_conditions:
        conditions.append(f"({' OR '.join(user_conditions)})")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    async with db.transaction():
        rows = await db.fetch_all(f"""
            SELECT id, name, subject, parent_id, is_system, sort_order
            FROM knowledge_tags
            WHERE {where_clause}
            ORDER BY sort_order, name
        """, tuple(params))

    # Build tree structure
    return _build_tag_tree([dict(r) for r in rows])


def _build_tag_tree(tags: List[dict]) -> List[dict]:
    """Build flat tag list into tree structure."""
    tags_map = {t["id"]: {**t, "children": []} for t in tags}
    roots = []

    for tag in tags_map.values():
        parent_id = tag.get("parent_id")
        if parent_id and parent_id in tags_map:
            tags_map[parent_id]["children"].append(tag)
        else:
            roots.append(tag)

    return roots


@router.post("/tags")
async def create_tag(
    tag: TagCreate,
    current_user: str = Depends(get_current_user),
):
    """Create custom tag."""
    db = get_db_manager()

    tag_id = _generate_id()
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    async with db.transaction():
        try:
            await db.execute("""
                INSERT INTO knowledge_tags (id, name, subject, parent_id, is_system, user_id, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
            """, (tag_id, tag.name, tag.subject, tag.parent_id, current_user, now))
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise HTTPException(status_code=400, detail="标签已存在")
            raise

    return {"id": tag_id, "created_at": now}


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: str,
    current_user: str = Depends(get_current_user),
):
    """Delete custom tag (only user's own tags)."""
    db = get_db_manager()

    async with db.transaction():
        result = await db.execute(
            "DELETE FROM knowledge_tags WHERE id = ? AND user_id = ? AND is_system = 0",
            (tag_id, current_user)
        )

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="标签不存在或无权删除")

    return {"success": True}


# ==================== Practice Generation ====================

@router.post("/practice/generate")
async def generate_practice(request: PracticeGenerateRequest):
    """Generate similar practice question (SSE stream)."""
    provider = _get_ai_provider()
    prompt = build_similar_prompt(
        request.question_text,
        request.knowledge_points,
        request.difficulty
    )

    async def event_generator():
        full_content_text = ""
        try:
            yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"

            async for chunk in provider.stream_chat(
                [ChatMessage(role="user", content=prompt)],
                temperature=0.8,
                max_tokens=4000
            ):
                if chunk.content:
                    if chunk.kind == "reasoning":
                        yield f"data: {json.dumps({'type': 'token', 'kind': 'reasoning', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                    elif chunk.kind == "content" or chunk.kind is None:
                        full_content_text += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'kind': 'content', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                if chunk.finish_reason:
                    break

            result = parse_analyze_response(full_content_text)
            yield f"data: {json.dumps({'type': 'done', 'result': result.model_dump()}, ensure_ascii=False)}\n\n"

        except Exception:
            logger.exception("Wrong notebook similar practice stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Processing error'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/practice/reanswer")
async def reanswer_question(request: ReanswerRequest):
    """Re-answer question (SSE stream)."""
    provider = _get_ai_provider()
    prompt = build_reanswer_prompt(request.question_text, request.subject)

    # Build messages (support image)
    if request.image_base64:
        messages = [
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{request.image_base64}"}},
                ],
            )
        ]
    else:
        messages = [ChatMessage(role="user", content=prompt)]

    async def event_generator():
        full_content_text = ""
        try:
            yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"

            async for chunk in provider.stream_chat(
                messages,
                temperature=0.7,
                max_tokens=4000
            ):
                if chunk.content:
                    if chunk.kind == "reasoning":
                        yield f"data: {json.dumps({'type': 'token', 'kind': 'reasoning', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                    elif chunk.kind == "content" or chunk.kind is None:
                        full_content_text += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'kind': 'content', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                if chunk.finish_reason:
                    break

            result = parse_analyze_response(full_content_text)
            yield f"data: {json.dumps({'type': 'done', 'result': result.model_dump()}, ensure_ascii=False)}\n\n"

        except Exception:
            logger.exception("Wrong notebook reanswer stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Processing error'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
