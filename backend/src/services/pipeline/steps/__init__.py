"""
Step executors for the processing pipeline.

Each step is implemented as a class that follows the StepExecutor protocol.
"""

from .base import BaseStepExecutor, StepExecutor, StepFactory
from .pdf_to_images import PdfToImagesStep, create_pdf_to_images_step
from .extract_questions import ExtractQuestionsStep, create_extract_questions_step
from .analyze_data import AnalyzeDataStep, create_analyze_data_step
from .compose_long_image import ComposeLongImageStep, create_compose_long_image_step
from .collect_results import CollectResultsStep, create_collect_results_step

__all__ = [
    # Base
    "StepExecutor",
    "BaseStepExecutor",
    "StepFactory",
    # Step implementations
    "PdfToImagesStep",
    "ExtractQuestionsStep",
    "AnalyzeDataStep",
    "ComposeLongImageStep",
    "CollectResultsStep",
    # Factory functions
    "create_pdf_to_images_step",
    "create_extract_questions_step",
    "create_analyze_data_step",
    "create_compose_long_image_step",
    "create_collect_results_step",
]
