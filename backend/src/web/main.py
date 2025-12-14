"""
Main Application - FastAPI app factory and lifespan management
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
except ImportError:  # pragma: no cover
    RateLimitExceeded = None  # type: ignore[assignment]
    SlowAPIMiddleware = None  # type: ignore[assignment]

from .limiter import limiter
from .routers import files, health, tasks


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    print("Starting ExamPaper AI Web Server...")

    # Initialize database (if needed)
    db_path = PROJECT_ROOT / "data" / "tasks.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Database path: {db_path}")

    yield

    print("Shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title="智能试卷处理系统API",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Rate limiting
    app.state.limiter = limiter
    if SlowAPIMiddleware is not None and getattr(limiter, "enabled", False):
        app.add_middleware(SlowAPIMiddleware)

        @app.exception_handler(RateLimitExceeded)  # type: ignore[arg-type]
        async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
            """Handle rate limit exceeded with JSON response."""
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "retry_after": exc.detail},
            )

    # Global exception handlers
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle FastAPI request validation errors with clean response."""
        errors = []
        for error in exc.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            errors.append({"field": loc, "message": error["msg"]})
        logger.warning("Validation error: %s", errors)
        return JSONResponse(
            status_code=422,
            content={"detail": "Validation error", "errors": errors},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle unexpected exceptions with logging."""
        logger.exception("Unexpected error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # Include routers
    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(files.router)

    # Mount static files for Vue frontend
    frontend_dist = PROJECT_ROOT / "frontend" / "dist"
    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="vue_assets")

    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Serve the Vue frontend HTML page"""
        index_file = frontend_dist / "index.html"
        if not index_file.exists():
            return HTMLResponse(
                content="<h1>Frontend not found</h1><p>Run 'npm run build' in frontend/</p>",
                status_code=404,
            )
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("智能试卷处理系统 Web 服务")
    print("=" * 60)
    print("\n服务器启动中...")
    print("访问地址: http://localhost:8000")
    print("\n按 Ctrl+C 停止服务器\n")

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
