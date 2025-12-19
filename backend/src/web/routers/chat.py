"""
Chat Router - AI 聊天对话（SSE 流式）
"""

from typing import List, Optional, Dict, Any
import logging
import base64
import os
import json
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...common.types import DEFAULT_DATA_DIR, LEGACY_PDF_IMAGES_DIR
from ...db.connection import get_db_manager
from ...services.ai import ChatMessage, AIProvider, AIProviderError
from ..config import config

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


# ==================== Request/Response Models ====================

class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    user_id: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_\-]+$')
    exam_id: int = Field(..., gt=0)
    question_no: int = Field(..., gt=0)
    title: Optional[str] = Field(None, max_length=200)


class CreateSessionResponse(BaseModel):
    """创建会话响应"""
    session_id: str
    created_at: str


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    content: str = Field(..., min_length=1, max_length=8000)
    question_no: Optional[int] = Field(
        None,
        gt=0,
        description="Override question_no for this message (allows one session across multiple questions)",
    )
    model: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    hint_mode: Optional[bool] = Field(False)
    use_image: Optional[bool] = Field(True, description="Attach question image (vision) when available")
    show_reasoning: Optional[bool] = Field(True, description="Include a student-visible reasoning section")


class GenerateSessionTitleRequest(BaseModel):
    """生成会话标题请求"""
    user_id: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_\-]+$')
    question_no: Optional[int] = Field(None, gt=0)
    force: bool = Field(False, description="Regenerate even if title already exists")
    model: Optional[str] = Field(None, max_length=100, description="Override title model")


class GenerateSessionTitleResponse(BaseModel):
    """生成会话标题响应"""
    title: str


class DeleteSessionResponse(BaseModel):
    """删除会话响应"""
    deleted: bool


class DeleteAllSessionsResponse(BaseModel):
    """批量删除会话响应"""
    deleted_count: int


HINT_MODE_NOTE_PREFIX = "\n\n[System Note: The user has enabled 'Hint Mode'."
HINT_MODE_SYSTEM_PROMPT = (
    "Hint Mode is enabled. Provide guidance and hints with Socratic questioning. "
    "Avoid giving the full complete answer directly."
)


def _strip_hint_mode_note(text: str) -> tuple[str, bool]:
    """
    Backward-compat: older frontends appended a 'System Note' into user content.
    Strip it so it won't pollute DB/history, and infer hint_mode=True.
    """
    if not text:
        return text, False
    idx = text.find(HINT_MODE_NOTE_PREFIX)
    if idx == -1:
        return text, False
    return text[:idx].rstrip(), True


def _is_generic_session_title(title: Optional[str]) -> bool:
    if title is None:
        return True
    t = str(title).strip()
    if not t:
        return True
    return t in {"对话", "新对话"}


def _normalize_session_title(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""

    # Keep only the first non-empty line
    for line in t.splitlines():
        line = line.strip()
        if line:
            t = line
            break

    t = t.strip().strip('"').strip("'").strip("“”‘’`")
    # Remove common markdown heading/bullets
    t = re.sub(r"^[#\-\*\s:：]+", "", t).strip()
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    # Avoid generic titles
    if t in {"对话", "聊天", "会话"}:
        return ""

    # Limit length (characters)
    max_len = 20
    if len(t) > max_len:
        t = t[:max_len].rstrip() + "…"
    return t


def _fallback_session_title(question_no: int, user_text: str) -> str:
    base = re.sub(r"\s+", " ", (user_text or "").strip())
    base = _normalize_session_title(base)
    if not base:
        return f"第{int(question_no)}题"

    # Remove overly-long leading punctuation that may remain
    base = base.lstrip("，,。.;；:：-— ")
    if not base:
        return f"第{int(question_no)}题"
    return f"第{int(question_no)}题：{base}"


async def _generate_session_title(
    ai: AIProvider,
    *,
    question_no: int,
    user_text: str,
    ocr_text: Optional[str] = None,
    model_override: Optional[str] = None,
) -> str:
    """
    Generate a short Chinese title for a session.

    Uses AI_TITLE_MODEL when configured and AI is available; otherwise falls back to heuristics.
    """
    user_text_clean = re.sub(r"\s+", " ", (user_text or "").strip())
    if not user_text_clean:
        return _fallback_session_title(question_no, "")

    title_model = (model_override or "").strip() or (config.ai_title_model or "").strip()
    if not title_model:
        # No dedicated title model configured; avoid extra cost by using heuristics only.
        return _fallback_session_title(question_no, user_text_clean)

    if not (config.ai_provider == "openai_compatible" and bool(config.ai_api_key)):
        return _fallback_session_title(question_no, user_text_clean)

    ocr_snippet = ""
    if ocr_text and isinstance(ocr_text, str):
        o = re.sub(r"\s+", " ", ocr_text.strip())
        if o:
            ocr_snippet = o[:200]

    sys = "你是一个中文助手，擅长为学习类对话生成简短标题。"
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

    try:
        parts: list[str] = []
        async for chunk in ai.stream_chat(
            [ChatMessage(role="system", content=sys), ChatMessage(role="user", content=prompt)],
            model=title_model,
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
    except Exception:
        # Never break chat for title generation issues
        return _fallback_session_title(question_no, user_text_clean)


class MessageOut(BaseModel):
    """消息输出"""
    id: int
    role: str
    content: str
    created_at: str


class SessionOut(BaseModel):
    """会话输出"""
    session_id: str
    exam_id: int
    question_no: int
    title: Optional[str]
    last_message_at: Optional[str]
    message_count: int


# ==================== AI Provider Dependency ====================

def get_ai_provider() -> AIProvider:
    """获取 AI Provider 实例"""
    from ...services.ai import OpenAICompatibleProvider, MockProvider
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"[AI Provider] ai_provider={config.ai_provider}, has_api_key={bool(config.ai_api_key)}")

    if config.ai_provider == "openai_compatible" and config.ai_api_key:
        logger.info(f"[AI Provider] 使用 OpenAICompatibleProvider: base_url={config.ai_base_url}, model={config.ai_model}")
        return OpenAICompatibleProvider(
            base_url=config.ai_base_url,
            api_key=config.ai_api_key,
            default_model=config.ai_model,
            timeout=config.ai_timeout
        )
    else:
        # 默认使用 Mock Provider（开发测试）
        logger.warning(f"[AI Provider] 使用 MockProvider（模拟AI）")
        return MockProvider()


# ==================== Helper Functions ====================

async def _ensure_user(user_id: str) -> None:
    """确保用户存在，不存在则自动创建（需在事务中调用）"""
    db = get_db_manager()

    await db.execute(
        """
        INSERT INTO users (user_id, display_name, last_active_at)
        VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(user_id) DO UPDATE SET
            last_active_at = excluded.last_active_at
        """,
        (user_id, f"用户_{user_id[:8]}")
    )


async def _build_system_prompt(exam_id: int, question_no: int, *, show_reasoning: bool, use_native_thinking: bool = False) -> str:
    """构建系统提示词（Gemini 3 Pro 优化版）

    Args:
        exam_id: 试卷ID
        question_no: 题号
        show_reasoning: 是否显示推理过程
        use_native_thinking: 是否使用模型原生thinking模式(DeepSeek R1/Gemini Thinking)
                            若为True则不在提示词中要求<think>标签(避免双重推理)
    """
    db = get_db_manager()

    # 获取题目和答案信息
    question = await db.fetch_one(
        """
        SELECT eq.ocr_text, ea.answer
        FROM exam_questions eq
        LEFT JOIN exam_answers ea ON eq.exam_id = ea.exam_id AND eq.question_no = ea.question_no
        WHERE eq.exam_id = ? AND eq.question_no = ?
        """,
        (exam_id, question_no)
    )

    ocr_text = question["ocr_text"] if question and question["ocr_text"] else "（无OCR文本）"
    correct_answer = question["answer"] if question and question["answer"] else "（无标准答案）"

    reasoning_req = ""
    if show_reasoning and not use_native_thinking:
        # 仅在非原生thinking模式下要求使用<think>标签
        # 原生thinking模式会自动在reasoning_content字段返回推理过程
        reasoning_req = (
            "- **思考过程（必须使用 <think> 标签）**：将你的详细推理过程放在 <think></think> 标签中，例如：\n"
            "  <think>\n"
            "  1. 分析题干：识别题目类型和关键信息...\n"
            "  2. 判断考点：本题考查的核心知识点是...\n"
            "  3. 分析选项：逐一分析各选项的正确性...\n"
            "  4. 确定答案：排除错误选项，选择正确答案...\n"
            "  </think>\n"
            "  **重要**：思考过程必须放在 <think> 标签内，标签外输出简洁的解题步骤。\n"
        )

    system_prompt = f"""你是一位经验丰富的公务员考试辅导老师，擅长解析行测题目并进行教学式讲解。

【题目信息】
题号：第 {question_no} 题
题目内容：{ocr_text}
正确答案：{correct_answer}

【写作要求】
1) 只输出给学生看的内容（允许“推理要点/依据”，但不要输出隐藏推理草稿/链路）。
2) 用中文输出，允许使用 Markdown 排版（不要输出 JSON、不要输出代码块包裹的 JSON）。
3) 若题目 OCR 文本缺失：优先以“题目图片”为准进行作答；若图片也无法识别，再说明缺失信息并给出通用解题思路（不要编造题干细节）。
4) 若“正确答案”存在：以此为准，解析要能自洽地解释为什么选它，以及其他选项常见错因/迷惑点。

【输出结构（Markdown）】
你必须按下面顺序输出小节（缺一不可）：
- **答案**：一句话给出结论（可直接引用“正确答案”）。
{reasoning_req}- **解析**：考点 → 方法 → 本题抓手（引用题干/图片里的关键信息）→ 常见陷阱 → 快速检验。
- **知识点**：列出 5–8 个知识点（用要点列表），并用“关联：A → B（关系）”给出 3–6 条关联。
"""

    return system_prompt


def _safe_png_filename(filename: str) -> None:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only PNG files allowed")


PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _decode_image_data_base64(image_data: str) -> Optional[bytes]:
    """Decode Base64 image data from database with PNG validation."""
    if not image_data:
        return None
    s = str(image_data).strip()
    if not s:
        return None
    if s.startswith("data:"):
        comma = s.find(",")
        if comma != -1:
            s = s[comma + 1:]
    try:
        decoded = base64.b64decode(s, validate=True)
        # Validate PNG signature
        if not decoded.startswith(PNG_SIGNATURE):
            return None
        return decoded
    except Exception:
        return None


def _write_bytes_atomic(path, data: bytes) -> None:
    """Write bytes to file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp_{uuid.uuid4().hex}")
    tmp.write_bytes(data)
    try:
        tmp.replace(path)
    except Exception:
        path.write_bytes(data)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


async def _get_question_image_path(exam_id: int, question_no: int):
    db = get_db_manager()
    row = await db.fetch_one(
        """
        SELECT e.exam_dir_name, eq.image_filename, eq.image_data
        FROM exams e
        JOIN exam_questions eq ON eq.exam_id = e.id
        WHERE e.id = ? AND eq.question_no = ?
        """,
        (exam_id, question_no),
    )
    if not row:
        return None

    exam_dir_name = str(row["exam_dir_name"] or "")
    image_filename = str(row["image_filename"] or "")
    image_data = row["image_data"]
    if not exam_dir_name or "/" in exam_dir_name or "\\" in exam_dir_name:
        return None
    _safe_png_filename(image_filename)

    base_dir = LEGACY_PDF_IMAGES_DIR.resolve()
    exam_dir = (base_dir / exam_dir_name).resolve()
    try:
        exam_dir.relative_to(base_dir)
    except ValueError:
        return None

    image_path = (exam_dir / "all_questions" / image_filename).resolve()
    try:
        image_path.relative_to(exam_dir)
    except ValueError:
        return None

    if not image_path.exists() or not image_path.is_file():
        # Fallback: materialize from DB to a local cache file
        if image_data:
            png_bytes = _decode_image_data_base64(str(image_data))
            if not png_bytes:
                return None

            cache_root = (DEFAULT_DATA_DIR / "question_image_cache").resolve()
            cache_exam_dir = (cache_root / f"exam_{int(exam_id)}").resolve()
            try:
                cache_exam_dir.relative_to(cache_root)
            except ValueError:
                return None

            cache_path = (cache_exam_dir / image_filename).resolve()
            try:
                cache_path.relative_to(cache_exam_dir)
            except ValueError:
                return None

            if not cache_path.exists():
                try:
                    _write_bytes_atomic(cache_path, png_bytes)
                except Exception:
                    return None

            if cache_path.exists() and cache_path.is_file():
                return cache_path

        return None
    return image_path


def _image_path_to_data_url(image_path) -> Optional[str]:
    """
    Convert a local PNG to a data URL for OpenAI-compatible vision inputs.
    Applies a size cap with a best-effort downscale if Pillow is available.
    """
    try:
        max_bytes = int(os.getenv("EXAMPAPER_CHAT_VISION_MAX_BYTES", "1500000"))
    except (TypeError, ValueError):
        max_bytes = 1500000

    try:
        raw = image_path.read_bytes()
    except Exception:
        return None

    mime = "image/png"
    data_bytes = raw

    if max_bytes > 0 and len(data_bytes) > max_bytes:
        try:
            from PIL import Image  # type: ignore
            import io as _io

            with Image.open(image_path) as im:
                im.load()
                max_dim = 1280
                w, h = im.size
                scale = min(1.0, float(max_dim) / float(max(w, h)))
                if scale < 1.0:
                    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                    im = im.resize(new_size)

                buf = _io.BytesIO()
                im.save(buf, format="PNG", optimize=True)
                png_bytes = buf.getvalue()
                if len(png_bytes) <= max_bytes:
                    data_bytes = png_bytes
                    mime = "image/png"
                else:
                    buf = _io.BytesIO()
                    im_rgb = im.convert("RGB")
                    im_rgb.save(buf, format="JPEG", quality=82, optimize=True, progressive=True)
                    data_bytes = buf.getvalue()
                    mime = "image/jpeg"
        except Exception:
            # PIL failed - enforce size cap strictly, return None if too large
            if len(raw) > max_bytes:
                return None
            data_bytes = raw
            mime = "image/png"

    # Final size check to ensure we never exceed the cap
    if max_bytes > 0 and len(data_bytes) > max_bytes:
        return None

    b64 = base64.b64encode(data_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


# ==================== API Endpoints ====================

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """创建聊天会话"""
    db = get_db_manager()

    # 使用事务确保原子性
    async with db.transaction():
        # 确保用户存在（不存在则自动创建）
        await _ensure_user(request.user_id)

        # 验证试卷存在
        exam = await db.fetch_one("SELECT id FROM exams WHERE id = ?", (request.exam_id,))
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")

        # 生成会话 ID
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # 创建会话
        await db.execute(
            """
            INSERT INTO chat_sessions (session_id, user_id, exam_id, question_no, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, request.user_id, request.exam_id, request.question_no, request.title, now, now)
        )

    return CreateSessionResponse(session_id=session_id, created_at=now)


@router.get("/sessions", response_model=List[SessionOut])
async def list_sessions(user_id: str, exam_id: Optional[int] = None):
    """获取用户的聊天会话列表"""
    db = get_db_manager()

    if exam_id is not None:
        query = """
            SELECT session_id, exam_id, question_no, title, last_message_at,
                   (SELECT COUNT(*) FROM chat_messages WHERE session_id = cs.session_id) as message_count
            FROM chat_sessions cs
            WHERE user_id = ? AND exam_id = ?
            ORDER BY (last_message_at IS NULL) ASC, last_message_at DESC, created_at DESC
        """
        params = (user_id, exam_id)
    else:
        query = """
            SELECT session_id, exam_id, question_no, title, last_message_at,
                   (SELECT COUNT(*) FROM chat_messages WHERE session_id = cs.session_id) as message_count
            FROM chat_sessions cs
            WHERE user_id = ?
            ORDER BY (last_message_at IS NULL) ASC, last_message_at DESC, created_at DESC
        """
        params = (user_id,)

    rows = await db.fetch_all(query, params)

    return [SessionOut(**dict(row)) for row in rows]


@router.delete("/sessions/{session_id}", response_model=DeleteSessionResponse)
async def delete_session(session_id: str, user_id: str):
    """删除单个会话（会级别删除，消息表会通过外键级联删除）"""
    db = get_db_manager()

    session = await db.fetch_one(
        "SELECT user_id FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(session["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    async with db.transaction():
        await db.execute(
            "DELETE FROM chat_sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )

    return DeleteSessionResponse(deleted=True)


@router.delete("/sessions", response_model=DeleteAllSessionsResponse)
async def delete_all_sessions(user_id: str, exam_id: Optional[int] = None):
    """删除用户会话（可选按试卷 exam_id 过滤）"""
    db = get_db_manager()

    async with db.transaction():
        if exam_id is not None:
            row = await db.fetch_one(
                "SELECT COUNT(*) AS c FROM chat_sessions WHERE user_id = ? AND exam_id = ?",
                (user_id, int(exam_id)),
            )
            deleted_count = int((row["c"] if row is not None else 0) or 0)
            await db.execute(
                "DELETE FROM chat_sessions WHERE user_id = ? AND exam_id = ?",
                (user_id, int(exam_id)),
            )
        else:
            row = await db.fetch_one(
                "SELECT COUNT(*) AS c FROM chat_sessions WHERE user_id = ?",
                (user_id,),
            )
            deleted_count = int((row["c"] if row is not None else 0) or 0)
            await db.execute(
                "DELETE FROM chat_sessions WHERE user_id = ?",
                (user_id,),
            )

    return DeleteAllSessionsResponse(deleted_count=deleted_count)


@router.get("/sessions/{session_id}/messages", response_model=List[MessageOut])
async def get_messages(session_id: str):
    """获取会话的所有消息"""
    db = get_db_manager()

    rows = await db.fetch_all(
        """
        SELECT id, role, content, created_at
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY id
        """,
        (session_id,)
    )

    out: List[MessageOut] = []
    for row in rows:
        data = dict(row)
        if data.get("role") == "user" and isinstance(data.get("content"), str):
            data["content"], _ = _strip_hint_mode_note(data["content"])
        out.append(MessageOut(**data))
    return out


@router.post("/sessions/{session_id}/title:generate", response_model=GenerateSessionTitleResponse)
async def generate_session_title(
    session_id: str,
    request: GenerateSessionTitleRequest,
    ai: AIProvider = Depends(get_ai_provider),
):
    """为会话生成标题（可用于补齐历史对话标题）"""
    db = get_db_manager()

    session = await db.fetch_one(
        "SELECT user_id, exam_id, question_no, title FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if str(session["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    current_title = session["title"]
    if not request.force and not _is_generic_session_title(current_title):
        return GenerateSessionTitleResponse(title=str(current_title))

    qno = int(request.question_no) if request.question_no else int(session["question_no"])

    last_user = await db.fetch_one(
        """
        SELECT content
        FROM chat_messages
        WHERE session_id = ? AND role = 'user'
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
    )
    if not last_user or last_user["content"] is None:
        raise HTTPException(status_code=400, detail="No user message found")

    user_text, _ = _strip_hint_mode_note(str(last_user["content"] or ""))

    ocr_text: Optional[str] = None
    try:
        ocr_row = await db.fetch_one(
            "SELECT ocr_text FROM exam_questions WHERE exam_id = ? AND question_no = ?",
            (int(session["exam_id"]), qno),
        )
        if ocr_row and isinstance(ocr_row["ocr_text"], str):
            ocr_text = ocr_row["ocr_text"]
    except Exception:
        ocr_text = None

    title = await _generate_session_title(
        ai,
        question_no=qno,
        user_text=user_text,
        ocr_text=ocr_text,
        model_override=request.model,
    )
    title = _normalize_session_title(title) or _fallback_session_title(qno, user_text)

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    async with db.transaction():
        await db.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (title, now, session_id),
        )

    return GenerateSessionTitleResponse(title=title)



@router.post("/sessions/{session_id}/messages:stream")
async def stream_message(
    session_id: str,
    request: SendMessageRequest,
    ai: AIProvider = Depends(get_ai_provider)
):
    """
    发送消息并流式接收 AI 回复（SSE）

    使用 Server-Sent Events 协议，前端需用 fetch() + ReadableStream 读取
    """
    db = get_db_manager()

    # 验证会话存在
    session = await db.fetch_one(
        "SELECT user_id, exam_id, question_no FROM chat_sessions WHERE session_id = ?",
        (session_id,)
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    exam_id = session["exam_id"]
    question_no = int(request.question_no) if request.question_no else int(session["question_no"])

    # 输入验证和参数准备
    raw_content = (request.content or "").strip()
    content, inferred_hint_mode = _strip_hint_mode_note(raw_content)
    hint_mode = bool(request.hint_mode) or inferred_hint_mode
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    model = (request.model or "").strip() or config.ai_model
    temperature = request.temperature if request.temperature is not None else config.ai_temperature
    # 暂时禁用 top_p，某些 API 代理不支持此参数
    # top_p = request.top_p if request.top_p is not None else config.ai_top_p
    top_p = None
    use_image = True if request.use_image is None else bool(request.use_image)
    show_reasoning = True if request.show_reasoning is None else bool(request.show_reasoning)

    # 1. 保存用户消息（短事务：避免在长连接流式期间持锁）
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    async with db.transaction():
        await db.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, created_at)
            VALUES (?, 'user', ?, ?)
            """,
            (session_id, content, now)
        )

    # 2. 构建对话历史
    history_rows = await db.fetch_all(
        """
        SELECT role, content
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY id
        """,
        (session_id,)
    )

    # 检测是否使用原生thinking模式(避免双重推理)
    use_native_thinking = False
    if show_reasoning:
        model_lower = model.lower()
        # DeepSeek R1 系列自动输出 reasoning_content
        if "deepseek" in model_lower and "r1" in model_lower:
            use_native_thinking = True
        # Gemini Thinking 模型
        elif "gemini" in model_lower and "thinking" in model_lower:
            use_native_thinking = True

    # 只传递最小信息：题目和答案
    messages: List[ChatMessage] = []

    # 获取题目答案信息
    question_info = await db.fetch_one(
        """
        SELECT eq.ocr_text, ea.answer
        FROM exam_questions eq
        LEFT JOIN exam_answers ea ON eq.exam_id = ea.exam_id AND eq.question_no = ea.question_no
        WHERE eq.exam_id = ? AND eq.question_no = ?
        """,
        (exam_id, question_no)
    )

    ocr_text_for_title: Optional[str] = None
    if question_info:
        ocr_text = question_info["ocr_text"] or ""
        ocr_text_for_title = ocr_text if isinstance(ocr_text, str) else None
        correct_answer = question_info["answer"] or ""

        # 只提供最小上下文，不加任何角色设定和输出格式要求
        minimal_context = f"Question #{question_no}"
        if ocr_text:
            minimal_context += f"\nContent: {ocr_text}"
        if correct_answer:
            minimal_context += f"\nCorrect Answer: {correct_answer}"

        messages.append(ChatMessage(role="system", content=minimal_context))

    image_data_url: Optional[str] = None
    if use_image:
        try:
            image_path = await _get_question_image_path(int(exam_id), int(question_no))
            if image_path is not None:
                image_data_url = _image_path_to_data_url(image_path)
        except Exception:
            image_data_url = None

    last_user_idx: Optional[int] = None
    for i, row in enumerate(history_rows):
        if row["role"] == "user":
            last_user_idx = i

    for i, row in enumerate(history_rows):
        role = row["role"]
        row_content = row["content"] or ""
        if role == "user":
            row_content, _ = _strip_hint_mode_note(row_content)
        if role == "user" and image_data_url and last_user_idx is not None and i == last_user_idx:
            messages.append(
                ChatMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": f"{row_content}\n\n请结合题目图片作答。"},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                )
            )
        else:
            messages.append(ChatMessage(role=role, content=row_content))

    # 3. SSE 流式生成函数
    async def event_generator():
        """SSE 事件生成器"""
        assistant_content_parts: List[str] = []

        try:
            # 发送流开始事件
            yield f"data: {json.dumps({'type': 'start'})}\n\n"

            # 记录请求参数（用于调试）
            logger.info(f"[AI Request] model={model}, temperature={temperature}, top_p={top_p}, max_tokens={config.ai_max_tokens}, show_reasoning={show_reasoning}, use_native_thinking={use_native_thinking}")

            # 根据 use_native_thinking 决定是否启用thinking参数
            thinking_param = None
            if use_native_thinking:
                # Gemini 2.0 Flash Thinking 需要显式启用thinking参数
                if "gemini" in model.lower() and "thinking" in model.lower():
                    thinking_param = {"type": "enabled"}
                # DeepSeek R1 会自动在 reasoning_content 字段返回推理过程
                # 无需特殊参数,backend 会自动处理 reasoning_content 并包装成 <think> 标签

            async def _stream_once(msgs: List[ChatMessage]):
                async for chunk in ai.stream_chat(
                    msgs,
                    model=model,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=config.ai_max_tokens,
                    thinking=thinking_param,
                ):
                    if chunk.content:
                        assistant_content_parts.append(chunk.content)
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
                    if chunk.finish_reason:
                        break

            # Stream once; if provider rejects vision payload, retry once without image.
            tried_fallback = False
            while True:
                try:
                    async for ev in _stream_once(messages):
                        yield ev
                    break
                except AIProviderError:
                    if tried_fallback or not image_data_url or assistant_content_parts:
                        raise
                    tried_fallback = True
                    logger.warning("Vision request failed; retrying without image")
                    no_image_messages: List[ChatMessage] = []
                    for m in messages:
                        if isinstance(m.content, list):
                            text_parts: List[str] = []
                            for item in m.content:
                                if (
                                    isinstance(item, dict)
                                    and item.get("type") == "text"
                                    and isinstance(item.get("text"), str)
                                ):
                                    text_parts.append(item["text"])
                            no_image_messages.append(ChatMessage(role=m.role, content="\n".join(text_parts).strip()))
                        else:
                            no_image_messages.append(m)
                    messages[:] = no_image_messages

            # 4. 保存助手消息到数据库（事务确保原子性）
            full_response = "".join(assistant_content_parts)
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            async with db.transaction():
                await db.execute(
                    """
                    INSERT INTO chat_messages (session_id, role, content, created_at, model)
                    VALUES (?, 'assistant', ?, ?, ?)
                    """,
                    (session_id, full_response, now, model)
                )

                # 更新会话的 last_message_at
                await db.execute(
                    """
                    UPDATE chat_sessions
                    SET last_message_at = ?, updated_at = ?, question_no = ?
                    WHERE session_id = ?
                    """,
                    (now, now, int(question_no), session_id)
                )

            # 5. Auto-generate session title (best-effort; never break chat)
            try:
                title_row = await db.fetch_one(
                    "SELECT title FROM chat_sessions WHERE session_id = ?",
                    (session_id,),
                )
                if title_row is not None and _is_generic_session_title(title_row["title"]):
                    generated = await _generate_session_title(
                        ai,
                        question_no=int(question_no),
                        user_text=content,
                        ocr_text=ocr_text_for_title,
                    )
                    normalized = _normalize_session_title(generated) or _fallback_session_title(int(question_no), content)
                    async with db.transaction():
                        await db.execute(
                            """
                            UPDATE chat_sessions
                            SET title = ?, updated_at = ?
                            WHERE session_id = ?
                            """,
                            (normalized, now, session_id),
                        )
            except Exception:
                # Ignore title generation failures
                pass

            # 发送完成事件
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except AIProviderError as e:
            # AI 调用错误
            error_msg = str(e)
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"

        except Exception as e:
            # 其他异常（不泄露内部错误详情）
            logger.exception("Chat stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Internal error'})}\n\n"

    # 返回 SSE 流式响应
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )
