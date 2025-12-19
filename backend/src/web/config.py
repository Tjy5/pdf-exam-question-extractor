"""
Web Configuration - Centralized settings management
"""
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from dotenv import load_dotenv

# 加载 backend/.env 文件（避免与 Gemini CLI 冲突）
_backend_env = Path(__file__).parent.parent.parent / ".env"
if _backend_env.exists():
    load_dotenv(_backend_env)


class AppConfig(BaseModel):
    """Application configuration with environment variable support"""

    # App mode: "dev" for AI chat, "production" for PDF processing
    app_mode: str = "production"

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    # GPU settings
    use_gpu: bool = True
    gpu_memory_fraction: float = 0.8

    # Processing settings
    max_workers: int = 4
    parallel_extraction: bool = True

    # Model settings
    step1_inproc: bool = True
    step2_inproc: bool = True
    ppstructure_warmup: bool = True
    ppstructure_warmup_async: bool = True
    step1_fallback_subprocess: bool = True
    step2_fallback_subprocess: bool = True
    light_table: bool = False

    # Paths
    project_root: Path = Path(__file__).parent.parent.parent.parent
    data_dir: Path = project_root / "data"
    uploads_dir: Path = project_root / "uploads"

    # AI Configuration
    ai_provider: str = "mock"  # "mock" or "openai_compatible"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-3.5-turbo"
    ai_temperature: float = 0.7
    ai_top_p: float = 0.95
    ai_max_tokens: int = 2000
    ai_timeout: float = 60.0

    # AI Session Title Configuration (optional)
    # When AI_TITLE_MODEL is set, the backend can use it to auto-generate chat session titles.
    ai_title_model: str = ""
    ai_title_temperature: float = 0.2
    ai_title_max_tokens: int = 64

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from environment variables"""
        return cls(
            app_mode=os.getenv("APP_MODE", "production"),
            use_gpu=os.getenv("EXAMPAPER_USE_GPU", "1") == "1",
            gpu_memory_fraction=float(os.getenv("FLAGS_fraction_of_gpu_memory_to_use", "0.8")),
            max_workers=int(os.getenv("EXAMPAPER_MAX_WORKERS", "4")),
            parallel_extraction=os.getenv("EXAMPAPER_PARALLEL_EXTRACTION", "1") == "1",
            step1_inproc=os.getenv("EXAMPAPER_STEP1_INPROC", "1") == "1",
            step2_inproc=os.getenv("EXAMPAPER_STEP2_INPROC", "1") == "1",
            ppstructure_warmup=os.getenv("EXAMPAPER_PPSTRUCTURE_WARMUP", "1") == "1",
            ppstructure_warmup_async=os.getenv("EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC", "1") == "1",
            step1_fallback_subprocess=os.getenv("EXAMPAPER_STEP1_FALLBACK_SUBPROCESS", "1") == "1",
            step2_fallback_subprocess=os.getenv("EXAMPAPER_STEP2_FALLBACK_SUBPROCESS", "1") == "1",
            light_table=os.getenv("EXAMPAPER_LIGHT_TABLE", "0") == "1",
            # AI Configuration
            ai_provider=os.getenv("AI_PROVIDER", "mock"),
            ai_base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
            ai_api_key=os.getenv("AI_API_KEY", ""),
            ai_model=os.getenv("AI_MODEL", "gpt-3.5-turbo"),
            ai_temperature=float(os.getenv("AI_TEMPERATURE", "0.7")),
            ai_top_p=float(os.getenv("AI_TOP_P", "0.95")),
            ai_max_tokens=int(os.getenv("AI_MAX_TOKENS", "2000")),
            ai_timeout=float(os.getenv("AI_TIMEOUT", "60.0")),
            ai_title_model=os.getenv("AI_TITLE_MODEL", ""),
            ai_title_temperature=float(os.getenv("AI_TITLE_TEMPERATURE", "0.2")),
            ai_title_max_tokens=int(os.getenv("AI_TITLE_MAX_TOKENS", "64")),
        )

    def setup_environment(self) -> None:
        """Set environment variables based on config"""
        env_vars = {
            "EXAMPAPER_USE_GPU": "1" if self.use_gpu else "0",
            "FLAGS_fraction_of_gpu_memory_to_use": str(self.gpu_memory_fraction),
            "FLAGS_allocator_strategy": "auto_growth",
            "FLAGS_cudnn_deterministic": "0",
            "FLAGS_cudnn_batchnorm_spatial_persistent": "1",
            "FLAGS_conv_workspace_size_limit": "4096",
            "EXAMPAPER_STEP1_INPROC": "1" if self.step1_inproc else "0",
            "EXAMPAPER_STEP2_INPROC": "1" if self.step2_inproc else "0",
            "EXAMPAPER_PPSTRUCTURE_WARMUP": "1" if self.ppstructure_warmup else "0",
            "EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC": "1" if self.ppstructure_warmup_async else "0",
            "EXAMPAPER_STEP1_FALLBACK_SUBPROCESS": "1" if self.step1_fallback_subprocess else "0",
            "EXAMPAPER_STEP2_FALLBACK_SUBPROCESS": "1" if self.step2_fallback_subprocess else "0",
            "EXAMPAPER_LIGHT_TABLE": "1" if self.light_table else "0",
            "EXAMPAPER_PARALLEL_EXTRACTION": "1" if self.parallel_extraction else "0",
            "EXAMPAPER_MAX_WORKERS": str(self.max_workers),
        }
        for key, value in env_vars.items():
            os.environ.setdefault(key, value)


# Global config instance
config = AppConfig.from_env()
