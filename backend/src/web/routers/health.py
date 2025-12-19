"""
Health Router - API endpoints for health checks and model status
"""
import os
from typing import Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/health", tags=["health"])


def _get_gpu_status() -> Dict[str, object]:
    """Get GPU status information"""
    use_gpu_env = os.getenv("EXAMPAPER_USE_GPU", "1")
    gpu_enabled = use_gpu_env == "1"

    if not gpu_enabled:
        return {
            "enabled": False,
            "available": False,
            "reason": "Disabled by EXAMPAPER_USE_GPU=0",
        }

    try:
        import paddle

        gpu_available = (
            paddle.device.is_compiled_with_cuda()
            and paddle.device.cuda.device_count() > 0
        )

        if not gpu_available:
            return {
                "enabled": True,
                "available": False,
                "reason": "No CUDA device found",
            }

        try:
            gpu_name = paddle.device.cuda.get_device_name(0)
            props = paddle.device.cuda.get_device_properties(0)
            memory_gb = props.total_memory / (1024**3)

            return {
                "enabled": True,
                "available": True,
                "device": gpu_name,
                "memory_total_gb": round(memory_gb, 2),
                "compute_capability": f"{props.major}.{props.minor}",
            }
        except Exception as e:
            return {
                "enabled": True,
                "available": True,
                "device": "Unknown",
                "error": str(e),
            }

    except Exception as e:
        return {
            "enabled": True,
            "available": False,
            "reason": f"Paddle import failed: {str(e)}",
        }


@router.get("/live")
async def health_live():
    """Liveness probe: server process is up"""
    return {"status": "live"}


@router.get("/config")
async def health_config():
    """Get app configuration for frontend"""
    app_mode = os.getenv("APP_MODE", "production")
    return {"app_mode": app_mode}


@router.get("/ready")
async def health_ready():
    """Readiness probe: server can accept work"""
    gpu_info = _get_gpu_status()
    ready = True  # Simplified for now
    status_code = 200 if ready else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if ready else "not_ready", "gpu": gpu_info},
    )


@router.get("/models/ppstructure")
async def health_ppstructure():
    """Get PP-StructureV3 model status"""
    gpu_info = _get_gpu_status()
    return JSONResponse(
        status_code=200,
        content={
            "ppstructure": {
                "ready": True,
                "gpu": gpu_info,
            }
        },
    )
