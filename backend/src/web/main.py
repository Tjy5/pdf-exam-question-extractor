"""
Main Application - FastAPI app factory and lifespan management
"""
import logging
import os
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
from ..db.connection import get_db_manager


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    logger.info("Starting ExamPaper AI Web Server...")

    # Initialize database
    db_path = PROJECT_ROOT / "data" / "tasks.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Database path: {db_path}")

    # Initialize DatabaseManager and create schema (idempotent)
    db = get_db_manager(db_path)
    try:
        await db.init()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.exception("Failed to initialize database")
        raise RuntimeError(f"Database initialization failed: {e}") from e

    # Warmup PP-StructureV3 model if enabled (synchronous to avoid first-page hangs)
    if os.getenv("EXAMPAPER_PPSTRUCTURE_WARMUP", "1") == "1":
        async_warmup = os.getenv("EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC", "0") == "1"
        if not async_warmup:
            logger.info("Warming up PP-StructureV3 model (synchronous)...")
            from ..services.models.model_provider import PPStructureProvider
            try:
                model_provider = PPStructureProvider.get_instance()
                success = await model_provider.warmup()
                if success:
                    logger.info("Model warmup completed successfully")
                else:
                    logger.warning(f"Model warmup failed: {model_provider.warmup_error}")
            except Exception as e:
                logger.exception("Model warmup exception")
                logger.warning(f"Will retry warmup on first request: {e}")

    yield

    # Cleanup: shutdown model provider and close database connection
    logger.info("Shutting down...")

    # Shutdown PP-StructureV3 model provider to clean up GPU executor
    try:
        from ..services.models.model_provider import PPStructureProvider
        provider = PPStructureProvider.get_instance()
        await provider.shutdown()
        logger.info("Model provider shutdown completed")
    except Exception:
        logger.exception("Failed to shutdown model provider cleanly")

    # Close database connection
    try:
        await db.close()
        logger.info("Database connection closed")
    except Exception:
        logger.exception("Failed to close database cleanly")


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
    # Current routes use /api prefix (tasks.router, files.router have prefix="/api")
    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(files.router)

    # API v1 alias - redirect /api/v1/* to /api/*
    # This provides forward compatibility for clients using versioned endpoints
    # Note: SSE streaming endpoints (/api/stream/*) should use /api directly
    # as some clients don't follow redirects for EventSource connections
    from starlette.responses import RedirectResponse

    @app.api_route(
        "/api/v1/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        include_in_schema=False,  # Hide from OpenAPI docs
    )
    async def v1_redirect(path: str, request: Request):
        """Redirect v1 API calls to current API (forward compatibility)."""
        query = f"?{request.query_params}" if request.query_params else ""
        return RedirectResponse(
            url=f"/api/{path}{query}",
            status_code=307,  # Temporary redirect, preserves method
        )

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
