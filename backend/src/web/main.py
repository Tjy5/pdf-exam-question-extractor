"""
Main Application - FastAPI app factory and lifespan management
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routers import files, health, tasks


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
