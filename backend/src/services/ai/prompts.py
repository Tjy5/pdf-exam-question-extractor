"""
AI Prompt Templates for Wrong Notebook

Contains prompt templates for image analysis, similar question generation, and re-answering.
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
4. 禁止输出任何额外文字"""

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
- harder: 挑战级，需要深度理解和多步推理"""

REANSWER_PROMPT = """【任务】
根据校正后的题目文本重新生成答案和解析。

【题目】
{question_text}

【学科】
{subject}

【输出格式】
<answer_text>正确答案</answer_text>
<analysis>详细解析（简体中文）</analysis>
<knowledge_points>知识点，逗号分隔</knowledge_points>"""


def build_analyze_prompt(subject: str = None, language: str = "zh") -> str:
    """Build image analysis prompt with optional subject hint."""
    prompt = ANALYZE_IMAGE_PROMPT
    if subject:
        prompt += f"\n\n【学科提示】本题可能是{subject}题目，请优先按此学科分析。"
    return prompt


def build_similar_prompt(
    original_question: str,
    knowledge_points: list[str],
    difficulty: str = "medium"
) -> str:
    """Build similar question generation prompt."""
    difficulty_map = {
        "easy": "比原题简单，使用更简单的数字和更直接的概念",
        "medium": "与原题难度相当",
        "hard": "比原题困难，组合多个概念或使用更复杂的数字",
        "harder": "挑战级难度，需要深度理解和多步推理"
    }
    return SIMILAR_QUESTION_PROMPT.format(
        original_question=original_question,
        knowledge_points=", ".join(knowledge_points) if knowledge_points else "未指定",
        difficulty_instruction=difficulty_map.get(difficulty, difficulty_map["medium"])
    )


def build_reanswer_prompt(question_text: str, subject: str = None) -> str:
    """Build re-answer prompt for corrected question text."""
    return REANSWER_PROMPT.format(
        question_text=question_text,
        subject=subject or "未指定"
    )
