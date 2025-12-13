"""
Web Configuration - Centralized settings management
"""
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class AppConfig(BaseModel):
    """Application configuration with environment variable support"""

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

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from environment variables"""
        return cls(
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
