"""
AI Response Parser for Wrong Notebook

Parses XML-formatted AI responses into structured data.
"""

import re
from typing import Optional
from pydantic import BaseModel


class AnalyzeResult(BaseModel):
    """Image analysis result model."""
    question_text: Optional[str] = None
    answer_text: Optional[str] = None
    analysis: Optional[str] = None
    subject: Optional[str] = None
    knowledge_points: list[str] = []
    error_type: Optional[str] = None


def parse_analyze_response(text: str) -> AnalyzeResult:
    """
    Parse AI XML-formatted response.

    Args:
        text: Complete AI response text

    Returns:
        AnalyzeResult: Structured parsing result
    """
    def extract_tag(tag_name: str) -> Optional[str]:
        pattern = rf"<{tag_name}>(.*?)</{tag_name}>"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else None

    # Parse knowledge points (comma separated)
    kp_text = extract_tag("knowledge_points") or ""
    knowledge_points = [
        kp.strip()
        for kp in kp_text.split(",")
        if kp.strip()
    ][:5]  # Max 5 points

    return AnalyzeResult(
        question_text=extract_tag("question_text"),
        answer_text=extract_tag("answer_text"),
        analysis=extract_tag("analysis"),
        subject=extract_tag("subject"),
        knowledge_points=knowledge_points,
        error_type=extract_tag("error_type")
    )


def parse_similar_response(text: str) -> AnalyzeResult:
    """Parse similar question generation response."""
    return parse_analyze_response(text)


def parse_reanswer_response(text: str) -> AnalyzeResult:
    """Parse re-answer response."""
    return parse_analyze_response(text)
