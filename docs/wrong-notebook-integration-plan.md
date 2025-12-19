# 错题功能集成实施方案

> 基于 Codex + Gemini 交叉验证的详细技术方案

---

## 一、项目背景

### 1.1 目标

将 `wrong-notebook-main` 项目的错题功能集成到现有的 `newvl` 智能试卷处理系统中。

### 1.2 技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 数据模型 | 扩展现有 `user_wrong_questions` 表 | 避免概念重叠，统一考试错题与独立上传错题 |
| AI图片分析 | 扩展现有 `OpenAICompatibleProvider` | 复用现有基础设施，支持多模态 |
| 用户系统 | 保持现有 `user_id` 机制 | 无需完整注册登录，简化实现 |
| 前端框架 | Vue 3 + Shadcn-Vue | 与现有前端统一，参考 wrong-notebook UI |

### 1.3 核心功能清单

- [x] 图片上传 + AI分析（OCR + 结构化解析）
- [x] 错题保存（支持考试来源 / 独立上传）
- [x] 知识点标签（层级结构 + 多对多关联）
- [x] 错题列表（多维度筛选）
- [x] 掌握度管理（待复习 / 复习中 / 已掌握）
- [ ] 变式题生成（Phase 2）
- [ ] 导出打印（Phase 2）

---

## 二、数据库设计

### 2.1 扩展 `user_wrong_questions` 表

**设计原则**：统一处理两种错题来源
- `source_type = 'exam'`：从考试中标记的错题（关联 exam_id）
- `source_type = 'upload'`：独立上传的错题图片

**新增字段**：

```sql
-- 在现有表基础上新增字段
ALTER TABLE user_wrong_questions ADD COLUMN source_type TEXT DEFAULT 'exam'
    CHECK (source_type IN ('exam', 'upload'));
ALTER TABLE user_wrong_questions ADD COLUMN original_image TEXT;      -- Base64图片
ALTER TABLE user_wrong_questions ADD COLUMN ai_question_text TEXT;    -- AI解析题目
ALTER TABLE user_wrong_questions ADD COLUMN ai_answer_text TEXT;      -- AI答案
ALTER TABLE user_wrong_questions ADD COLUMN ai_analysis TEXT;         -- AI解析
ALTER TABLE user_wrong_questions ADD COLUMN mastery_level INTEGER DEFAULT 0
    CHECK (mastery_level BETWEEN 0 AND 2);  -- 0=待复习, 1=复习中, 2=已掌握
ALTER TABLE user_wrong_questions ADD COLUMN subject TEXT;             -- 学科
ALTER TABLE user_wrong_questions ADD COLUMN source_name TEXT;         -- 来源名称
ALTER TABLE user_wrong_questions ADD COLUMN user_notes TEXT;          -- 用户笔记
ALTER TABLE user_wrong_questions ADD COLUMN error_type TEXT;          -- 错误类型
ALTER TABLE user_wrong_questions ADD COLUMN updated_at TEXT;          -- 更新时间
```

**完整表结构**（迁移后）：

```sql
CREATE TABLE user_wrong_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,

    -- 来源类型
    source_type TEXT DEFAULT 'exam' CHECK (source_type IN ('exam', 'upload')),

    -- 考试来源字段（source_type='exam' 时使用）
    exam_id INTEGER,
    question_no INTEGER,
    user_answer TEXT,

    -- 独立上传字段（source_type='upload' 时使用）
    original_image TEXT,           -- Base64 编码的原图

    -- AI 分析结果（两种来源共用）
    ai_question_text TEXT,         -- AI 解析的题目文本（Markdown + LaTeX）
    ai_answer_text TEXT,           -- AI 生成的答案
    ai_analysis TEXT,              -- AI 解析步骤

    -- 元数据
    subject TEXT,                  -- 学科：数学/物理/化学/生物/英语/其他
    source_name TEXT,              -- 来源名称：期中考试/周测等
    error_type TEXT,               -- 错误类型：计算错误/概念错误/审题错误/方法错误
    user_notes TEXT,               -- 用户笔记

    -- 状态
    status TEXT DEFAULT 'wrong',
    mastery_level INTEGER DEFAULT 0 CHECK (mastery_level BETWEEN 0 AND 2),

    -- 时间戳
    marked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- 外键
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX idx_wrong_user_source ON user_wrong_questions(user_id, source_type);
CREATE INDEX idx_wrong_user_exam ON user_wrong_questions(user_id, exam_id);
CREATE INDEX idx_wrong_mastery ON user_wrong_questions(mastery_level);
CREATE INDEX idx_wrong_subject ON user_wrong_questions(subject);
CREATE INDEX idx_wrong_updated ON user_wrong_questions(updated_at DESC);
```

### 2.2 知识点标签表

**设计原则**：
- 支持无限层级（邻接表模式）
- 区分系统预设标签 vs 用户自定义标签
- 多对多关联错题

```sql
-- 知识点标签表
CREATE TABLE IF NOT EXISTS knowledge_tags (
    id TEXT PRIMARY KEY,                    -- ULID/UUID
    name TEXT NOT NULL,                     -- 标签名：勾股定理
    subject TEXT NOT NULL,                  -- 学科：math/physics/chemistry/biology/english

    -- 层级（邻接表）
    parent_id TEXT,                         -- 父标签 ID

    -- 分类
    is_system INTEGER DEFAULT 0,            -- 1=系统预设, 0=用户自定义
    user_id TEXT,                           -- 用户自定义标签绑定的用户

    -- 排序
    sort_order INTEGER DEFAULT 0,

    -- 时间戳
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- 外键
    FOREIGN KEY (parent_id) REFERENCES knowledge_tags(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,

    -- 唯一约束：同一用户（或系统）下同一学科的标签名不重复
    UNIQUE(subject, name, user_id)
);

-- 索引
CREATE INDEX idx_tags_subject ON knowledge_tags(subject);
CREATE INDEX idx_tags_parent ON knowledge_tags(parent_id);
CREATE INDEX idx_tags_user ON knowledge_tags(user_id);
CREATE INDEX idx_tags_system ON knowledge_tags(is_system);

-- 错题-标签关联表（多对多）
CREATE TABLE IF NOT EXISTS wrong_question_tags (
    wrong_question_id INTEGER NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (wrong_question_id, tag_id),
    FOREIGN KEY (wrong_question_id) REFERENCES user_wrong_questions(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES knowledge_tags(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX idx_wqt_question ON wrong_question_tags(wrong_question_id);
CREATE INDEX idx_wqt_tag ON wrong_question_tags(tag_id);
```

### 2.3 递归查询工具函数

由于使用邻接表模式，需要 `WITH RECURSIVE` 查询标签树：

```sql
-- 获取某标签的所有子孙标签
WITH RECURSIVE tag_tree AS (
    -- 基础情况：起始标签
    SELECT id, name, parent_id, 0 AS depth
    FROM knowledge_tags
    WHERE id = ?

    UNION ALL

    -- 递归：子标签
    SELECT t.id, t.name, t.parent_id, tt.depth + 1
    FROM knowledge_tags t
    INNER JOIN tag_tree tt ON t.parent_id = tt.id
    WHERE tt.depth < 10  -- 防止无限递归
)
SELECT * FROM tag_tree;

-- 获取某学科的完整标签树（用于前端展示）
WITH RECURSIVE tag_tree AS (
    SELECT id, name, parent_id, subject, sort_order, 0 AS depth,
           name AS path
    FROM knowledge_tags
    WHERE subject = ? AND parent_id IS NULL AND (is_system = 1 OR user_id = ?)

    UNION ALL

    SELECT t.id, t.name, t.parent_id, t.subject, t.sort_order, tt.depth + 1,
           tt.path || ' > ' || t.name
    FROM knowledge_tags t
    INNER JOIN tag_tree tt ON t.parent_id = tt.id
    WHERE tt.depth < 10
)
SELECT * FROM tag_tree ORDER BY path;
```

### 2.4 迁移脚本

```sql
-- migrations/001_extend_wrong_questions.sql
-- 执行前请备份数据库

-- Step 1: 创建新表
CREATE TABLE user_wrong_questions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    source_type TEXT DEFAULT 'exam' CHECK (source_type IN ('exam', 'upload')),
    exam_id INTEGER,
    question_no INTEGER,
    user_answer TEXT,
    original_image TEXT,
    ai_question_text TEXT,
    ai_answer_text TEXT,
    ai_analysis TEXT,
    subject TEXT,
    source_name TEXT,
    error_type TEXT,
    user_notes TEXT,
    status TEXT DEFAULT 'wrong',
    mastery_level INTEGER DEFAULT 0 CHECK (mastery_level BETWEEN 0 AND 2),
    marked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
);

-- Step 2: 迁移现有数据
INSERT INTO user_wrong_questions_new
    (id, user_id, source_type, exam_id, question_no, user_answer, status, marked_at, updated_at)
SELECT
    id, user_id, 'exam', exam_id, question_no, user_answer, status, marked_at, marked_at
FROM user_wrong_questions;

-- Step 3: 删除旧表，重命名新表
DROP TABLE user_wrong_questions;
ALTER TABLE user_wrong_questions_new RENAME TO user_wrong_questions;

-- Step 4: 重建索引
CREATE INDEX idx_wrong_user_source ON user_wrong_questions(user_id, source_type);
CREATE INDEX idx_wrong_user_exam ON user_wrong_questions(user_id, exam_id);
CREATE INDEX idx_wrong_mastery ON user_wrong_questions(mastery_level);
CREATE INDEX idx_wrong_subject ON user_wrong_questions(subject);
CREATE INDEX idx_wrong_updated ON user_wrong_questions(updated_at DESC);

-- Step 5: 创建标签表
CREATE TABLE IF NOT EXISTS knowledge_tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    parent_id TEXT,
    is_system INTEGER DEFAULT 0,
    user_id TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (parent_id) REFERENCES knowledge_tags(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(subject, name, user_id)
);

CREATE INDEX idx_tags_subject ON knowledge_tags(subject);
CREATE INDEX idx_tags_parent ON knowledge_tags(parent_id);
CREATE INDEX idx_tags_user ON knowledge_tags(user_id);

-- Step 6: 创建关联表
CREATE TABLE IF NOT EXISTS wrong_question_tags (
    wrong_question_id INTEGER NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (wrong_question_id, tag_id),
    FOREIGN KEY (wrong_question_id) REFERENCES user_wrong_questions(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES knowledge_tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_wqt_question ON wrong_question_tags(wrong_question_id);
CREATE INDEX idx_wqt_tag ON wrong_question_tags(tag_id);
```

---

## 三、AI 图片分析服务

### 3.1 架构设计

```
用户上传图片
    ↓
前端压缩（>1MB 时）
    ↓
POST /api/wrong-notebook/analyze
    ↓
OpenAICompatibleProvider.analyze_image()
    ↓
SSE 流式返回结构化数据
    ↓
前端解析 XML 标签 → 填充表单
```

### 3.2 扩展 AI Provider

在 `backend/src/services/ai/openai_compatible.py` 中新增方法：

```python
async def analyze_image(
    self,
    image_base64: str,
    mime_type: str = "image/jpeg",
    subject: Optional[str] = None,
    language: str = "zh",
) -> AsyncIterator[StreamChunk]:
    """
    分析错题图片，流式返回结构化数据

    Args:
        image_base64: Base64 编码的图片数据
        mime_type: 图片 MIME 类型
        subject: 学科提示（可选）
        language: 输出语言

    Yields:
        StreamChunk: 增量文本片段
    """
    system_prompt = self._build_analyze_prompt(subject, language)

    # 构建多模态消息
    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请分析这道错题图片"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_base64}"
                    }
                }
            ]
        }
    ]

    # 复用现有流式请求逻辑
    async for chunk in self._stream_multimodal_request(messages):
        yield chunk
```

### 3.3 Prompt 模板

在 `backend/src/services/ai/prompts.py` 中定义：

```python
"""
错题分析 Prompt 模板
"""

ANALYZE_IMAGE_PROMPT = """【角色与核心任务】
你是一位专业的跨学科考试分析专家。请分析用户上传的错题图片，提取题目信息并提供解答。

【核心输出要求】
必须严格使用以下 XML 标签格式输出，禁止使用 JSON 或 Markdown 代码块。

<question_text>
题目完整文本。使用 Markdown 格式，数学公式使用 LaTeX（行内 $...$，块级 $$...$$）。
</question_text>

<answer_text>
正确答案。使用 Markdown 和 LaTeX。
</answer_text>

<analysis>
详细解题步骤。必须使用简体中文。直接使用 LaTeX 符号（如 $\\frac{1}{2}$）。
</analysis>

<subject>
学科。必须是：数学/物理/化学/生物/英语/语文/其他
</subject>

<knowledge_points>
知识点，逗号分隔。例如：勾股定理, 直角三角形
</knowledge_points>

<error_type>
可能的错误类型：计算错误/概念错误/审题错误/方法错误/其他
</error_type>

【关键约束】
1. 必须包含以上 6 个 XML 标签
2. 如果图片模糊无法识别，在对应字段说明
3. 知识点最多 5 个，使用标准化名称
4. 禁止输出任何额外文字
"""

SIMILAR_QUESTION_PROMPT = """【角色】
你是一位 K12 教育题目生成专家。请根据原题生成一道变式题。

【原题】
{original_question}

【知识点】
{knowledge_points}

【难度要求】
{difficulty_instruction}

【输出格式】
<question_text>新题目文本</question_text>
<answer_text>正确答案</answer_text>
<analysis>详细解析（简体中文）</analysis>

【难度说明】
- easy: 比原题简单，使用更简单的数字
- medium: 与原题难度相当
- hard: 比原题困难，组合多个概念
- harder: 挑战级，需要深度理解和多步推理
"""

REANSWER_PROMPT = """【任务】
根据校正后的题目文本重新生成答案和解析。

【题目】
{question_text}

【学科】
{subject}

【输出格式】
<answer_text>正确答案</answer_text>
<analysis>详细解析（简体中文）</analysis>
<knowledge_points>知识点，逗号分隔</knowledge_points>
"""


def build_analyze_prompt(subject: str = None, language: str = "zh") -> str:
    """构建图片分析 prompt"""
    prompt = ANALYZE_IMAGE_PROMPT

    if subject:
        prompt += f"\n\n【学科提示】本题可能是{subject}题目，请优先按此学科分析。"

    return prompt


def build_similar_prompt(
    original_question: str,
    knowledge_points: list[str],
    difficulty: str = "medium"
) -> str:
    """构建变式题生成 prompt"""
    difficulty_map = {
        "easy": "比原题简单，使用更简单的数字和更直接的概念",
        "medium": "与原题难度相当",
        "hard": "比原题困难，组合多个概念或使用更复杂的数字",
        "harder": "挑战级难度，需要深度理解和多步推理"
    }

    return SIMILAR_QUESTION_PROMPT.format(
        original_question=original_question,
        knowledge_points=", ".join(knowledge_points),
        difficulty_instruction=difficulty_map.get(difficulty, difficulty_map["medium"])
    )
```

### 3.4 响应解析器

```python
# backend/src/services/ai/parser.py

import re
from typing import Optional
from pydantic import BaseModel


class AnalyzeResult(BaseModel):
    """图片分析结果"""
    question_text: Optional[str] = None
    answer_text: Optional[str] = None
    analysis: Optional[str] = None
    subject: Optional[str] = None
    knowledge_points: list[str] = []
    error_type: Optional[str] = None
    requires_image: bool = False


def parse_analyze_response(text: str) -> AnalyzeResult:
    """
    解析 AI 返回的 XML 格式响应

    Args:
        text: AI 返回的完整文本

    Returns:
        AnalyzeResult: 结构化解析结果
    """
    def extract_tag(tag_name: str) -> Optional[str]:
        pattern = rf"<{tag_name}>(.*?)</{tag_name}>"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else None

    # 解析知识点（逗号分隔）
    kp_text = extract_tag("knowledge_points") or ""
    knowledge_points = [
        kp.strip()
        for kp in kp_text.split(",")
        if kp.strip()
    ][:5]  # 最多 5 个

    # 解析 requires_image
    ri_text = extract_tag("requires_image") or "false"
    requires_image = ri_text.lower() == "true"

    return AnalyzeResult(
        question_text=extract_tag("question_text"),
        answer_text=extract_tag("answer_text"),
        analysis=extract_tag("analysis"),
        subject=extract_tag("subject"),
        knowledge_points=knowledge_points,
        error_type=extract_tag("error_type"),
        requires_image=requires_image
    )
```

---

## 四、API 端点设计

### 4.1 路由结构

```
/api/wrong-notebook/
├── POST   /analyze              # 上传图片 → AI 分析（SSE）
├── GET    /items                # 获取错题列表（支持筛选）
├── POST   /items                # 保存错题
├── GET    /items/{id}           # 获取单个错题详情
├── PATCH  /items/{id}           # 更新错题
├── DELETE /items/{id}           # 删除错题
├── GET    /tags                 # 获取标签列表（树形）
├── POST   /tags                 # 创建自定义标签
├── DELETE /tags/{id}            # 删除自定义标签
├── POST   /practice/generate    # 生成变式题（SSE）
└── POST   /practice/reanswer    # 重新解答（SSE）
```

### 4.2 请求/响应模型

```python
# backend/src/web/schemas/wrong_notebook.py

from typing import Optional, List
from pydantic import BaseModel, Field


# ========== 分析 ==========

class AnalyzeRequest(BaseModel):
    """图片分析请求"""
    image_base64: str = Field(..., description="Base64 编码的图片")
    mime_type: str = Field(default="image/jpeg", description="图片 MIME 类型")
    subject: Optional[str] = Field(default=None, description="学科提示")


class AnalyzeResult(BaseModel):
    """图片分析结果"""
    question_text: Optional[str] = None
    answer_text: Optional[str] = None
    analysis: Optional[str] = None
    subject: Optional[str] = None
    knowledge_points: List[str] = []
    error_type: Optional[str] = None


# ========== 错题 CRUD ==========

class WrongItemCreate(BaseModel):
    """创建错题请求"""
    user_id: str
    source_type: str = Field(default="upload", pattern="^(exam|upload)$")

    # 考试来源
    exam_id: Optional[int] = None
    question_no: Optional[int] = None
    user_answer: Optional[str] = None

    # 独立上传
    original_image: Optional[str] = None

    # AI 分析结果
    ai_question_text: Optional[str] = None
    ai_answer_text: Optional[str] = None
    ai_analysis: Optional[str] = None

    # 元数据
    subject: Optional[str] = None
    source_name: Optional[str] = None
    error_type: Optional[str] = None
    user_notes: Optional[str] = None

    # 标签
    tag_ids: List[str] = []


class WrongItemUpdate(BaseModel):
    """更新错题请求"""
    mastery_level: Optional[int] = Field(default=None, ge=0, le=2)
    user_notes: Optional[str] = None
    tag_ids: Optional[List[str]] = None
    ai_question_text: Optional[str] = None
    ai_answer_text: Optional[str] = None
    ai_analysis: Optional[str] = None


class WrongItemResponse(BaseModel):
    """错题响应"""
    id: int
    user_id: str
    source_type: str
    exam_id: Optional[int] = None
    question_no: Optional[int] = None
    original_image: Optional[str] = None
    ai_question_text: Optional[str] = None
    ai_answer_text: Optional[str] = None
    ai_analysis: Optional[str] = None
    subject: Optional[str] = None
    source_name: Optional[str] = None
    error_type: Optional[str] = None
    user_notes: Optional[str] = None
    mastery_level: int = 0
    marked_at: str
    updated_at: str
    tags: List[dict] = []


class WrongItemListResponse(BaseModel):
    """错题列表响应"""
    items: List[WrongItemResponse]
    total: int
    page: int
    page_size: int


# ========== 标签 ==========

class TagCreate(BaseModel):
    """创建标签请求"""
    name: str
    subject: str
    parent_id: Optional[str] = None
    user_id: str


class TagResponse(BaseModel):
    """标签响应"""
    id: str
    name: str
    subject: str
    parent_id: Optional[str] = None
    is_system: bool = False
    children: List["TagResponse"] = []


# ========== 练习 ==========

class PracticeGenerateRequest(BaseModel):
    """生成变式题请求"""
    question_text: str
    knowledge_points: List[str] = []
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard|harder)$")


class ReanswerRequest(BaseModel):
    """重新解答请求"""
    question_text: str
    subject: Optional[str] = None
    image_base64: Optional[str] = None
```

### 4.3 核心端点实现

```python
# backend/src/web/routers/wrong_notebook.py

import json
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..schemas.wrong_notebook import (
    AnalyzeRequest, WrongItemCreate, WrongItemUpdate,
    WrongItemResponse, WrongItemListResponse,
    TagCreate, TagResponse, PracticeGenerateRequest, ReanswerRequest
)
from ...db import get_db_manager
from ...services.ai import OpenAICompatibleProvider
from ...services.ai.parser import parse_analyze_response
from ...services.ai.prompts import build_analyze_prompt, build_similar_prompt
from ..config import get_config

router = APIRouter(prefix="/api/wrong-notebook", tags=["wrong-notebook"])


# ==================== 辅助函数 ====================

async def _ensure_user(user_id: str):
    """确保用户存在"""
    db = get_db_manager()
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
    """生成唯一 ID"""
    return str(uuid.uuid4())


# ==================== 图片分析 ====================

@router.post("/analyze")
async def analyze_image(request: AnalyzeRequest):
    """
    上传图片进行 AI 分析

    返回 SSE 流式响应，格式：
    - {"type": "content", "text": "..."} 增量文本
    - {"type": "done", "result": {...}} 完成，包含解析结果
    - {"type": "error", "message": "..."} 错误
    """
    config = get_config()
    provider = OpenAICompatibleProvider(
        base_url=config.ai_base_url,
        api_key=config.ai_api_key,
        default_model=config.ai_model
    )

    async def event_generator():
        full_text = ""
        try:
            async for chunk in provider.analyze_image(
                request.image_base64,
                request.mime_type,
                request.subject
            ):
                if chunk.content:
                    full_text += chunk.content
                    yield f"data: {json.dumps({'type': 'content', 'text': chunk.content})}\n\n"

            # 解析完整响应
            result = parse_analyze_response(full_text)
            yield f"data: {json.dumps({'type': 'done', 'result': result.model_dump()})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ==================== 错题 CRUD ====================

@router.get("/items", response_model=WrongItemListResponse)
async def list_wrong_items(
    user_id: str,
    source_type: Optional[str] = None,
    subject: Optional[str] = None,
    mastery_level: Optional[int] = None,
    tag_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100)
):
    """获取错题列表（支持筛选）"""
    db = get_db_manager()

    # 构建动态查询
    conditions = ["w.user_id = ?"]
    params: List = [user_id]

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

    # 查询总数
    count_row = await db.fetch_one(
        f"SELECT COUNT(*) as total FROM user_wrong_questions w WHERE {where_clause}",
        tuple(params)
    )
    total = count_row["total"] if count_row else 0

    # 查询数据
    rows = await db.fetch_all(f"""
        SELECT w.*
        FROM user_wrong_questions w
        WHERE {where_clause}
        ORDER BY w.updated_at DESC
        LIMIT ? OFFSET ?
    """, (*params, page_size, offset))

    # 获取每个错题的标签
    items = []
    for row in rows:
        tags = await db.fetch_all("""
            SELECT t.id, t.name, t.subject
            FROM knowledge_tags t
            INNER JOIN wrong_question_tags wt ON t.id = wt.tag_id
            WHERE wt.wrong_question_id = ?
        """, (row["id"],))

        items.append(WrongItemResponse(
            **dict(row),
            tags=[dict(t) for t in tags]
        ))

    return WrongItemListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("/items")
async def create_wrong_item(item: WrongItemCreate):
    """保存错题"""
    db = get_db_manager()

    async with db.transaction():
        await _ensure_user(item.user_id)

        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        result = await db.execute("""
            INSERT INTO user_wrong_questions (
                user_id, source_type, exam_id, question_no, user_answer,
                original_image, ai_question_text, ai_answer_text, ai_analysis,
                subject, source_name, error_type, user_notes,
                marked_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.user_id, item.source_type, item.exam_id, item.question_no,
            item.user_answer, item.original_image, item.ai_question_text,
            item.ai_answer_text, item.ai_analysis, item.subject,
            item.source_name, item.error_type, item.user_notes, now, now
        ))

        item_id = result.lastrowid

        # 关联标签
        for tag_id in item.tag_ids:
            await db.execute(
                "INSERT OR IGNORE INTO wrong_question_tags (wrong_question_id, tag_id) VALUES (?, ?)",
                (item_id, tag_id)
            )

    return {"id": item_id, "created_at": now}


@router.get("/items/{item_id}", response_model=WrongItemResponse)
async def get_wrong_item(item_id: int):
    """获取单个错题详情"""
    db = get_db_manager()

    row = await db.fetch_one(
        "SELECT * FROM user_wrong_questions WHERE id = ?",
        (item_id,)
    )

    if not row:
        raise HTTPException(status_code=404, detail="错题不存在")

    tags = await db.fetch_all("""
        SELECT t.id, t.name, t.subject
        FROM knowledge_tags t
        INNER JOIN wrong_question_tags wt ON t.id = wt.tag_id
        WHERE wt.wrong_question_id = ?
    """, (item_id,))

    return WrongItemResponse(**dict(row), tags=[dict(t) for t in tags])


@router.patch("/items/{item_id}")
async def update_wrong_item(item_id: int, update: WrongItemUpdate):
    """更新错题"""
    db = get_db_manager()

    # 检查存在
    existing = await db.fetch_one(
        "SELECT id FROM user_wrong_questions WHERE id = ?",
        (item_id,)
    )
    if not existing:
        raise HTTPException(status_code=404, detail="错题不存在")

    async with db.transaction():
        # 构建更新字段
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

        # 更新标签关联
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
async def delete_wrong_item(item_id: int):
    """删除错题"""
    db = get_db_manager()

    result = await db.execute(
        "DELETE FROM user_wrong_questions WHERE id = ?",
        (item_id,)
    )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="错题不存在")

    return {"success": True}


# ==================== 标签管理 ====================

@router.get("/tags")
async def list_tags(
    subject: Optional[str] = None,
    user_id: Optional[str] = None,
    include_system: bool = True
):
    """获取标签列表（树形结构）"""
    db = get_db_manager()

    conditions = []
    params = []

    if subject:
        conditions.append("subject = ?")
        params.append(subject)

    # 系统标签 + 用户自定义标签
    user_conditions = []
    if include_system:
        user_conditions.append("is_system = 1")
    if user_id:
        user_conditions.append("user_id = ?")
        params.append(user_id)

    if user_conditions:
        conditions.append(f"({' OR '.join(user_conditions)})")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    rows = await db.fetch_all(f"""
        SELECT id, name, subject, parent_id, is_system, sort_order
        FROM knowledge_tags
        WHERE {where_clause}
        ORDER BY sort_order, name
    """, tuple(params))

    # 构建树结构
    return _build_tag_tree([dict(r) for r in rows])


def _build_tag_tree(tags: List[dict]) -> List[dict]:
    """将平铺的标签列表构建为树结构"""
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
async def create_tag(tag: TagCreate):
    """创建自定义标签"""
    db = get_db_manager()

    tag_id = _generate_id()
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    try:
        await db.execute("""
            INSERT INTO knowledge_tags (id, name, subject, parent_id, is_system, user_id, created_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
        """, (tag_id, tag.name, tag.subject, tag.parent_id, tag.user_id, now))
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail="标签已存在")
        raise

    return {"id": tag_id, "created_at": now}


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: str, user_id: str):
    """删除自定义标签（仅限用户自己的标签）"""
    db = get_db_manager()

    result = await db.execute(
        "DELETE FROM knowledge_tags WHERE id = ? AND user_id = ? AND is_system = 0",
        (tag_id, user_id)
    )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="标签不存在或无权删除")

    return {"success": True}


# ==================== 练习生成 ====================

@router.post("/practice/generate")
async def generate_practice(request: PracticeGenerateRequest):
    """生成变式题（SSE 流式返回）"""
    config = get_config()
    provider = OpenAICompatibleProvider(
        base_url=config.ai_base_url,
        api_key=config.ai_api_key,
        default_model=config.ai_model
    )

    prompt = build_similar_prompt(
        request.question_text,
        request.knowledge_points,
        request.difficulty
    )

    async def event_generator():
        full_text = ""
        try:
            async for chunk in provider.stream_chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=4000
            ):
                if chunk.content:
                    full_text += chunk.content
                    yield f"data: {json.dumps({'type': 'content', 'text': chunk.content})}\n\n"

            result = parse_analyze_response(full_text)
            yield f"data: {json.dumps({'type': 'done', 'result': result.model_dump()})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/practice/reanswer")
async def reanswer_question(request: ReanswerRequest):
    """重新解答题目（SSE 流式返回）"""
    config = get_config()
    provider = OpenAICompatibleProvider(
        base_url=config.ai_base_url,
        api_key=config.ai_api_key,
        default_model=config.ai_model
    )

    # 构建消息（支持图片）
    if request.image_base64:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"请重新解答这道题：\n\n{request.question_text}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{request.image_base64}"}}
                ]
            }
        ]
    else:
        messages = [{"role": "user", "content": f"请重新解答这道题：\n\n{request.question_text}"}]

    async def event_generator():
        full_text = ""
        try:
            async for chunk in provider.stream_chat(
                messages=messages,
                temperature=0.7,
                max_tokens=4000
            ):
                if chunk.content:
                    full_text += chunk.content
                    yield f"data: {json.dumps({'type': 'content', 'text': chunk.content})}\n\n"

            result = parse_analyze_response(full_text)
            yield f"data: {json.dumps({'type': 'done', 'result': result.model_dump()})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

## 五、前端设计

### 5.1 页面结构

```
frontend/src/
├── views/
│   ├── WrongNotebook.vue              # 错题本主页
│   └── WrongItemDetail.vue            # 错题详情页
├── components/wrong-notebook/
│   ├── WrongItemList.vue              # 错题列表
│   ├── WrongItemCard.vue              # 错题卡片
│   ├── WrongItemEditor.vue            # 错题编辑器（AI分析后）
│   ├── ImageUploader.vue              # 图片上传组件
│   ├── ImageCropper.vue               # 图片裁剪组件
│   ├── TagSelector.vue                # 标签选择器
│   ├── MasteryBadge.vue               # 掌握度徽章
│   ├── FilterPanel.vue                # 筛选面板
│   └── MarkdownPreview.vue            # Markdown + LaTeX 预览
└── stores/
    └── useWrongNotebookStore.ts       # 状态管理
```

### 5.2 核心组件设计

#### ImageUploader.vue

```vue
<template>
  <div
    class="upload-area"
    @drop.prevent="handleDrop"
    @dragover.prevent
    @click="triggerFileInput"
  >
    <input
      ref="fileInput"
      type="file"
      accept="image/*"
      hidden
      @change="handleFileSelect"
    />

    <div v-if="!preview" class="upload-placeholder">
      <IconUpload />
      <p>点击或拖拽上传错题图片</p>
      <p class="hint">支持 JPG、PNG，建议大小 < 5MB</p>
    </div>

    <div v-else class="preview-container">
      <img :src="preview" alt="预览" />
      <button @click.stop="clear">重新上传</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { compressImage } from '@/utils/image'

const emit = defineEmits<{
  (e: 'upload', data: { base64: string; mimeType: string }): void
}>()

const fileInput = ref<HTMLInputElement>()
const preview = ref<string>()

async function handleFile(file: File) {
  // 压缩大图片
  const compressed = file.size > 1024 * 1024
    ? await compressImage(file, { maxWidth: 2000, quality: 0.8 })
    : file

  const reader = new FileReader()
  reader.onload = (e) => {
    const base64 = (e.target?.result as string).split(',')[1]
    preview.value = e.target?.result as string
    emit('upload', { base64, mimeType: file.type })
  }
  reader.readAsDataURL(compressed)
}

function handleDrop(e: DragEvent) {
  const file = e.dataTransfer?.files[0]
  if (file?.type.startsWith('image/')) {
    handleFile(file)
  }
}

function handleFileSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) handleFile(file)
}

function triggerFileInput() {
  fileInput.value?.click()
}

function clear() {
  preview.value = undefined
}
</script>
```

#### WrongItemEditor.vue

```vue
<template>
  <div class="editor-container">
    <!-- 左侧：原图 -->
    <div class="image-panel">
      <img :src="originalImage" alt="原题图片" />
    </div>

    <!-- 右侧：AI 分析结果 -->
    <div class="content-panel">
      <!-- 题目 -->
      <div class="field">
        <label>题目</label>
        <textarea v-model="form.questionText" rows="6" />
        <MarkdownPreview :content="form.questionText" />
      </div>

      <!-- 答案 -->
      <div class="field">
        <label>答案</label>
        <textarea v-model="form.answerText" rows="3" />
      </div>

      <!-- 解析 -->
      <div class="field">
        <label>解析</label>
        <textarea v-model="form.analysis" rows="8" />
        <MarkdownPreview :content="form.analysis" />
      </div>

      <!-- 元数据 -->
      <div class="meta-row">
        <div class="field">
          <label>学科</label>
          <select v-model="form.subject">
            <option value="数学">数学</option>
            <option value="物理">物理</option>
            <option value="化学">化学</option>
            <option value="生物">生物</option>
            <option value="英语">英语</option>
            <option value="其他">其他</option>
          </select>
        </div>

        <div class="field">
          <label>来源</label>
          <input v-model="form.sourceName" placeholder="如：期中考试" />
        </div>
      </div>

      <!-- 知识点标签 -->
      <div class="field">
        <label>知识点</label>
        <TagSelector
          v-model="form.tagIds"
          :subject="form.subject"
          :user-id="userId"
        />
      </div>

      <!-- 操作按钮 -->
      <div class="actions">
        <button @click="$emit('cancel')">取消</button>
        <button class="primary" @click="save" :disabled="saving">
          {{ saving ? '保存中...' : '保存到错题本' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { useWrongNotebookStore } from '@/stores/useWrongNotebookStore'
import TagSelector from './TagSelector.vue'
import MarkdownPreview from './MarkdownPreview.vue'

interface Props {
  originalImage: string
  analyzeResult: {
    questionText?: string
    answerText?: string
    analysis?: string
    subject?: string
    knowledgePoints?: string[]
  }
  userId: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'save', data: any): void
  (e: 'cancel'): void
}>()

const store = useWrongNotebookStore()
const saving = ref(false)

const form = reactive({
  questionText: props.analyzeResult.questionText || '',
  answerText: props.analyzeResult.answerText || '',
  analysis: props.analyzeResult.analysis || '',
  subject: props.analyzeResult.subject || '数学',
  sourceName: '',
  tagIds: [] as string[]
})

async function save() {
  saving.value = true
  try {
    await store.createItem({
      userId: props.userId,
      sourceType: 'upload',
      originalImage: props.originalImage,
      aiQuestionText: form.questionText,
      aiAnswerText: form.answerText,
      aiAnalysis: form.analysis,
      subject: form.subject,
      sourceName: form.sourceName,
      tagIds: form.tagIds
    })
    emit('save', form)
  } finally {
    saving.value = false
  }
}
</script>
```

#### TagSelector.vue

```vue
<template>
  <div class="tag-selector">
    <!-- 已选标签 -->
    <div class="selected-tags">
      <span
        v-for="tag in selectedTags"
        :key="tag.id"
        class="tag"
      >
        {{ tag.name }}
        <button @click="removeTag(tag.id)">×</button>
      </span>
    </div>

    <!-- 搜索输入 -->
    <input
      v-model="searchQuery"
      placeholder="搜索或添加标签"
      @focus="showDropdown = true"
    />

    <!-- 下拉选择 -->
    <div v-if="showDropdown" class="dropdown">
      <div
        v-for="tag in filteredTags"
        :key="tag.id"
        class="tag-option"
        :class="{ selected: modelValue.includes(tag.id) }"
        @click="toggleTag(tag)"
      >
        <span class="indent" :style="{ paddingLeft: tag.depth * 16 + 'px' }">
          {{ tag.name }}
        </span>
      </div>

      <!-- 创建新标签 -->
      <div
        v-if="searchQuery && !exactMatch"
        class="create-option"
        @click="createTag"
      >
        创建标签 "{{ searchQuery }}"
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useWrongNotebookStore } from '@/stores/useWrongNotebookStore'

interface Props {
  modelValue: string[]
  subject: string
  userId: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const store = useWrongNotebookStore()
const searchQuery = ref('')
const showDropdown = ref(false)

// 扁平化标签树
const flattenedTags = computed(() => {
  const result: Array<{ id: string; name: string; depth: number }> = []

  function flatten(tags: any[], depth = 0) {
    for (const tag of tags) {
      result.push({ id: tag.id, name: tag.name, depth })
      if (tag.children?.length) {
        flatten(tag.children, depth + 1)
      }
    }
  }

  flatten(store.tags)
  return result
})

const filteredTags = computed(() => {
  if (!searchQuery.value) return flattenedTags.value
  const query = searchQuery.value.toLowerCase()
  return flattenedTags.value.filter(t =>
    t.name.toLowerCase().includes(query)
  )
})

const selectedTags = computed(() =>
  flattenedTags.value.filter(t => props.modelValue.includes(t.id))
)

const exactMatch = computed(() =>
  flattenedTags.value.some(t =>
    t.name.toLowerCase() === searchQuery.value.toLowerCase()
  )
)

function toggleTag(tag: { id: string }) {
  const newValue = props.modelValue.includes(tag.id)
    ? props.modelValue.filter(id => id !== tag.id)
    : [...props.modelValue, tag.id]
  emit('update:modelValue', newValue)
}

function removeTag(tagId: string) {
  emit('update:modelValue', props.modelValue.filter(id => id !== tagId))
}

async function createTag() {
  const newTag = await store.createTag({
    name: searchQuery.value,
    subject: props.subject,
    userId: props.userId
  })
  emit('update:modelValue', [...props.modelValue, newTag.id])
  searchQuery.value = ''
}

// 加载标签
watch(() => props.subject, () => {
  store.loadTags(props.subject, props.userId)
}, { immediate: true })
</script>
```

### 5.3 状态管理

```typescript
// frontend/src/stores/useWrongNotebookStore.ts

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

interface WrongItem {
  id: number
  userId: string
  sourceType: 'exam' | 'upload'
  originalImage?: string
  aiQuestionText?: string
  aiAnswerText?: string
  aiAnalysis?: string
  subject?: string
  sourceName?: string
  masteryLevel: number
  tags: Array<{ id: string; name: string }>
  markedAt: string
  updatedAt: string
}

interface Tag {
  id: string
  name: string
  subject: string
  parentId?: string
  children: Tag[]
}

export const useWrongNotebookStore = defineStore('wrongNotebook', () => {
  // State
  const items = ref<WrongItem[]>([])
  const tags = ref<Tag[]>([])
  const loading = ref(false)
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)

  // Filters
  const filters = ref({
    sourceType: undefined as string | undefined,
    subject: undefined as string | undefined,
    masteryLevel: undefined as number | undefined,
    tagId: undefined as string | undefined,
    search: undefined as string | undefined
  })

  // Actions
  async function loadItems(userId: string) {
    loading.value = true
    try {
      const params = new URLSearchParams({
        user_id: userId,
        page: String(page.value),
        page_size: String(pageSize.value)
      })

      if (filters.value.sourceType) params.set('source_type', filters.value.sourceType)
      if (filters.value.subject) params.set('subject', filters.value.subject)
      if (filters.value.masteryLevel !== undefined) params.set('mastery_level', String(filters.value.masteryLevel))
      if (filters.value.tagId) params.set('tag_id', filters.value.tagId)
      if (filters.value.search) params.set('search', filters.value.search)

      const { data } = await axios.get(`/api/wrong-notebook/items?${params}`)
      items.value = data.items
      total.value = data.total
    } finally {
      loading.value = false
    }
  }

  async function createItem(item: {
    userId: string
    sourceType: string
    originalImage?: string
    aiQuestionText?: string
    aiAnswerText?: string
    aiAnalysis?: string
    subject?: string
    sourceName?: string
    tagIds?: string[]
  }) {
    const { data } = await axios.post('/api/wrong-notebook/items', {
      user_id: item.userId,
      source_type: item.sourceType,
      original_image: item.originalImage,
      ai_question_text: item.aiQuestionText,
      ai_answer_text: item.aiAnswerText,
      ai_analysis: item.aiAnalysis,
      subject: item.subject,
      source_name: item.sourceName,
      tag_ids: item.tagIds || []
    })
    return data
  }

  async function updateItem(itemId: number, updates: {
    masteryLevel?: number
    userNotes?: string
    tagIds?: string[]
  }) {
    await axios.patch(`/api/wrong-notebook/items/${itemId}`, {
      mastery_level: updates.masteryLevel,
      user_notes: updates.userNotes,
      tag_ids: updates.tagIds
    })
  }

  async function deleteItem(itemId: number) {
    await axios.delete(`/api/wrong-notebook/items/${itemId}`)
    items.value = items.value.filter(i => i.id !== itemId)
  }

  async function loadTags(subject?: string, userId?: string) {
    const params = new URLSearchParams()
    if (subject) params.set('subject', subject)
    if (userId) params.set('user_id', userId)
    params.set('include_system', 'true')

    const { data } = await axios.get(`/api/wrong-notebook/tags?${params}`)
    tags.value = data
  }

  async function createTag(tag: {
    name: string
    subject: string
    userId: string
    parentId?: string
  }) {
    const { data } = await axios.post('/api/wrong-notebook/tags', {
      name: tag.name,
      subject: tag.subject,
      user_id: tag.userId,
      parent_id: tag.parentId
    })
    await loadTags(tag.subject, tag.userId)
    return data
  }

  // 分析图片（SSE）
  function analyzeImage(
    imageBase64: string,
    mimeType: string,
    subject?: string,
    onChunk?: (text: string) => void,
    onDone?: (result: any) => void,
    onError?: (error: string) => void
  ) {
    const eventSource = new EventSource(
      `/api/wrong-notebook/analyze?image_base64=${encodeURIComponent(imageBase64)}&mime_type=${mimeType}${subject ? `&subject=${subject}` : ''}`
    )

    // 注意：实际实现需要用 fetch + POST，这里简化示意
    // 推荐使用 fetch API 处理 POST + SSE
  }

  return {
    // State
    items,
    tags,
    loading,
    total,
    page,
    pageSize,
    filters,

    // Actions
    loadItems,
    createItem,
    updateItem,
    deleteItem,
    loadTags,
    createTag,
    analyzeImage
  }
})
```

---

## 六、实施步骤

### Phase 1：数据库扩展（优先级：高）

1. 备份现有数据库
2. 执行迁移脚本 `001_extend_wrong_questions.sql`
3. 更新 `schema.py` 中的 `SCHEMA_SQL`
4. 验证迁移结果

### Phase 2：AI 服务扩展（优先级：高）

1. 在 `openai_compatible.py` 中添加 `analyze_image` 方法
2. 创建 `prompts.py` 定义 Prompt 模板
3. 创建 `parser.py` 实现响应解析
4. 单元测试

### Phase 3：API 端点实现（优先级：高）

1. 创建 `routers/wrong_notebook.py`
2. 实现核心 CRUD 端点
3. 实现图片分析 SSE 端点
4. 在 `main.py` 中注册路由
5. API 测试

### Phase 4：前端页面开发（优先级：中）

1. 创建 Store 和基础组件
2. 实现图片上传 + AI 分析流程
3. 实现错题列表页
4. 实现错题详情/编辑页
5. 实现标签选择器
6. 样式优化

### Phase 5：增强功能（优先级：低）

1. 变式题生成
2. 导出打印
3. 统计仪表盘

---

## 七、风险与注意事项

### 7.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| SQLite 并发锁 | 高并发下性能下降 | 使用短事务，避免嵌套 |
| AI 响应不稳定 | 解析失败 | 渐进式降级 + 重试机制 |
| 图片存储过大 | 数据库膨胀 | 压缩图片，考虑对象存储 |
| 标签递归查询慢 | 性能问题 | 限制递归深度，缓存结果 |

### 7.2 实施注意事项

1. **数据库迁移前必须备份**
2. **AI Prompt 中的 LaTeX 转义**：直接使用 `\frac` 而非 `\\frac`
3. **SSE 连接管理**：前端需要正确处理连接断开和重连
4. **图片压缩**：前端上传前压缩，后端存储时再压缩
5. **标签一致性**：使用标准化名称，避免同义词

### 7.3 后续优化方向

1. 图片存储迁移到对象存储（MinIO/S3）
2. AI 分析结果缓存（基于图片哈希）
3. 批量上传支持
4. 全文搜索（SQLite FTS5）
5. 移动端适配（PWA）

---

## 八、参考资料

- wrong-notebook 源码：`wrong-notebook-main/wrong-notebook-main/`
- Prisma Schema：`prisma/schema.prisma`
- AI Prompt 模板：`src/lib/ai/prompts.ts`
- Shadcn-Vue：https://www.shadcn-vue.com/

---

*文档版本：v1.0*
*创建日期：2024-12-17*
*基于 Codex + Gemini 交叉验证*
