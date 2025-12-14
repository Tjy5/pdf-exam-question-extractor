# 项目架构优化方案 (plan2.md)

## 项目概述

**ExamPaper AI** - 智能试卷自动化处理系统
- 后端: Python/FastAPI + SQLite + PaddleOCR
- 前端: Vue 3 + TypeScript + Pinia + Tailwind CSS
- 核心功能: PDF试卷 → OCR识别 → 结构检测 → 题目裁剪 → 结果输出

---

## 当前架构评估

### 后端架构 (✅ 良好)

```
backend/src/
├── common/          # 共享工具 (image, io, ocr_models, paths, types, utils)
├── db/              # SQLite持久化 (connection, crud, schema)
├── services/
│   ├── models/      # ML模型提供者
│   ├── pipeline/    # 核心处理流水线
│   │   ├── contracts.py    # StepContext, StepResult, TaskSnapshot
│   │   ├── runner.py       # PipelineRunner (带重试)
│   │   ├── impl/           # 步骤实现
│   │   └── steps/          # 步骤执行器
│   ├── recovery/    # 恢复服务
│   └── tasks/       # 任务管理
└── web/
    ├── main.py      # FastAPI应用
    ├── schemas.py   # Pydantic模型
    ├── routers/     # API端点
    └── services/    # Web服务 (task_service, task_executor, event_bus)
```

**优点:**
- Pipeline模式设计清晰，5步流水线易于理解
- 步骤执行器抽象良好 (BaseStepExecutor)
- SSE实时进度推送
- 硬件自动检测与参数优化

**问题:**
- 内存任务状态 + SQLite混合，水平扩展困难
- EventBus进程内通信，多实例无法共享
- Pipeline步骤与DB/Web层存在隐式耦合

### 前端架构 (✅ 良好)

```
frontend/src/
├── components/
│   ├── common/      # ErrorBoundary, SkeletonCard
│   └── dashboard/   # UploadZone, LogTerminal, PipelineView, ResultGallery, StepItem
├── composables/     # useAutoScroll, useDragDrop, useEventSource
├── services/        # api.ts, types.ts
└── stores/          # useTaskStore.ts (~400行)
```

**优点:**
- 组件职责清晰
- Composables复用良好
- TypeScript类型定义完整

**问题:**
- 单一Store过大 (~400行)
- SSE重连/重放机制不完善
- 缺少多任务并发支持

---

## 优化方案

### Phase 1: 基础架构加固 (低风险)

#### 1.1 后端接口抽象

**目标:** 解耦Pipeline核心与外部依赖

**新增接口定义:** `backend/src/services/pipeline/ports.py`

```python
from abc import ABC, abstractmethod
from typing import Protocol, Any

class ArtifactStore(Protocol):
    """工件存储接口"""
    def save(self, task_id: str, step: str, name: str, data: bytes) -> str: ...
    def load(self, task_id: str, step: str, name: str) -> bytes: ...
    def list(self, task_id: str, step: str) -> list[str]: ...

class EventPublisher(Protocol):
    """事件发布接口"""
    def publish(self, event_type: str, payload: dict) -> None: ...

class TaskRepository(Protocol):
    """任务仓库接口"""
    def get(self, task_id: str) -> dict | None: ...
    def update_status(self, task_id: str, status: str) -> None: ...
    def append_log(self, task_id: str, log: dict) -> None: ...
```

**收益:**
- 步骤执行器可独立测试
- 未来可替换存储后端 (S3, Redis等)
- 支持多实例部署

#### 1.2 前端Store拆分

**目标:** 单一Store拆分为领域Store

**当前:** `useTaskStore.ts` (~400行)

**拆分方案:**

```typescript
// stores/useTaskStore.ts - 任务核心状态
export const useTaskStore = defineStore('task', () => {
  const taskId = ref<string | null>(null)
  const status = ref<TaskStatus>('idle')
  const steps = ref<Step[]>([])
  // ... 任务相关状态和方法
})

// stores/useLogsStore.ts - 日志管理
export const useLogsStore = defineStore('logs', () => {
  const logs = ref<LogEntry[]>([])
  const cursor = ref(0)
  const seenIds = ref<Set<string>>(new Set())
  // ... 日志相关方法
})

// stores/useConnectionStore.ts - 连接管理
export const useConnectionStore = defineStore('connection', () => {
  const eventSource = ref<EventSource | null>(null)
  const pollTimer = ref<number | null>(null)
  const connectionStatus = ref<'connected' | 'disconnected' | 'reconnecting'>('disconnected')
  // ... SSE/轮询相关方法
})

// stores/useResultsStore.ts - 结果管理
export const useResultsStore = defineStore('results', () => {
  const results = ref<ImageResult[]>([])
  // ... 结果加载和下载方法
})
```

**收益:**
- 各Store职责单一，易于维护
- 支持未来多任务并发
- 便于添加新功能模块

#### 1.3 SSE可靠性增强

**目标:** 支持断线重连和事件重放

**后端改动:** `backend/src/web/routers/tasks.py`

```python
@router.get("/stream/{task_id}")
async def stream_task(
    task_id: str,
    last_event_id: str | None = Header(None, alias="Last-Event-ID")
):
    """SSE流，支持断点续传"""
    async def event_generator():
        # 从last_event_id重放历史事件
        if last_event_id:
            missed_events = await get_events_since(task_id, last_event_id)
            for event in missed_events:
                yield _format_sse(event)

        # 继续实时推送
        async for event in subscribe_events(task_id):
            yield _format_sse(event, event_id=event.id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**前端改动:** `composables/useEventSource.ts`

```typescript
export function useEventSource(url: Ref<string>) {
  const lastEventId = ref<string | null>(null)
  const retryCount = ref(0)
  const maxRetries = 5

  function connect() {
    const es = new EventSource(url.value)

    es.onmessage = (e) => {
      lastEventId.value = e.lastEventId
      retryCount.value = 0
      // ... 处理消息
    }

    es.onerror = () => {
      es.close()
      if (retryCount.value < maxRetries) {
        const delay = Math.min(1000 * 2 ** retryCount.value, 30000)
        setTimeout(() => {
          retryCount.value++
          connect()
        }, delay)
      }
    }
  }

  return { connect, lastEventId, retryCount }
}
```

---

### Phase 2: 可扩展性增强 (中等风险)

#### 2.1 Pipeline步骤注册机制

**目标:** 支持动态添加新步骤

**当前问题:** 步骤硬编码在`task_executor.py`

**改进方案:** `backend/src/services/pipeline/registry.py`

```python
from typing import Callable, Dict
from .contracts import StepExecutor

StepFactory = Callable[..., StepExecutor]

class StepRegistry:
    """步骤注册表"""
    _steps: Dict[str, StepFactory] = {}
    _order: list[str] = []

    @classmethod
    def register(cls, name: str, order: int = -1):
        """装饰器: 注册步骤"""
        def decorator(factory: StepFactory):
            cls._steps[name] = factory
            if order >= 0:
                cls._order.insert(order, name)
            else:
                cls._order.append(name)
            return factory
        return decorator

    @classmethod
    def get(cls, name: str) -> StepFactory:
        return cls._steps[name]

    @classmethod
    def get_ordered_steps(cls) -> list[str]:
        return cls._order.copy()

# 使用示例
@StepRegistry.register("pdf_to_images", order=0)
def create_pdf_to_images_step(...) -> StepExecutor:
    return PdfToImagesStep(...)

@StepRegistry.register("extract_questions", order=1)
def create_extract_questions_step(...) -> StepExecutor:
    return ExtractQuestionsStep(...)
```

**收益:**
- 新步骤只需添加文件并注册
- 支持条件性步骤 (如: 仅数据分析题执行特定步骤)
- 便于插件化扩展

#### 2.2 前端组件层级优化

**目标:** 支持复杂功能模块

**当前结构:**
```
components/
├── common/
└── dashboard/
```

**优化结构:**
```
components/
├── common/           # 通用基础组件
│   ├── ErrorBoundary.vue
│   ├── SkeletonCard.vue
│   ├── Modal.vue
│   └── Toast.vue
├── task/             # 任务相关组件
│   ├── TaskCard.vue
│   ├── TaskList.vue
│   └── TaskDetail.vue
├── pipeline/         # 流水线相关组件
│   ├── PipelineView.vue
│   ├── StepItem.vue
│   └── StepDetail.vue
├── upload/           # 上传相关组件
│   ├── UploadZone.vue
│   └── FilePreview.vue
├── results/          # 结果相关组件
│   ├── ResultGallery.vue
│   ├── ImageViewer.vue
│   └── ExportOptions.vue
└── logs/             # 日志相关组件
    ├── LogTerminal.vue
    └── LogFilter.vue
```

**收益:**
- 按功能域组织，易于定位
- 支持懒加载优化
- 便于团队协作

#### 2.3 API版本化

**目标:** 支持API演进而不破坏现有客户端

**改动:** `backend/src/web/main.py`

```python
from fastapi import APIRouter

# API版本路由
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(tasks_router)
v1_router.include_router(files_router)

# 兼容旧路由 (重定向到v1)
legacy_router = APIRouter(prefix="/api")
legacy_router.include_router(tasks_router)  # 保持兼容

app.include_router(v1_router)
app.include_router(legacy_router)
```

---

### Phase 3: 生产就绪 (高价值)

#### 3.1 任务队列分离

**目标:** Web进程与Pipeline执行分离

**架构变更:**

```
当前:
[FastAPI] → [TaskExecutor] → [PipelineRunner] → [GPU]
           (同进程)

优化后:
[FastAPI] → [Redis Queue] → [Worker进程] → [PipelineRunner] → [GPU]
           (API进程)        (独立进程)
```

**实现方案:** 使用 `arq` (轻量级异步任务队列)

```python
# backend/src/worker/tasks.py
from arq import create_pool
from arq.connections import RedisSettings

async def run_pipeline(ctx, task_id: str, step_from: int = 0):
    """Worker任务: 执行Pipeline"""
    runner = PipelineRunner(...)
    await runner.run(task_id, start_from=step_from)

class WorkerSettings:
    functions = [run_pipeline]
    redis_settings = RedisSettings(host='localhost')

# backend/src/web/services/task_executor.py
class TaskExecutorService:
    async def start_full_pipeline(self, task_id: str):
        redis = await create_pool(RedisSettings())
        await redis.enqueue_job('run_pipeline', task_id)
```

**收益:**
- API响应不受Pipeline阻塞
- 支持多Worker水平扩展
- 任务可靠性提升 (队列持久化)

#### 3.2 数据库迁移准备

**目标:** 为PostgreSQL迁移做准备

**当前SQLite Schema问题:**
- 无迁移工具
- 类型约束弱
- 并发写入受限

**改进方案:**

1. 引入Alembic迁移工具
2. 使用SQLAlchemy ORM (可选)
3. 抽象数据库连接

```python
# backend/src/db/base.py
from contextlib import contextmanager
from typing import Protocol

class DatabaseConnection(Protocol):
    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchone(self) -> dict | None: ...
    def fetchall(self) -> list[dict]: ...

@contextmanager
def get_connection() -> DatabaseConnection:
    """获取数据库连接 (可切换SQLite/PostgreSQL)"""
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/tasks.db")
    if db_url.startswith("sqlite"):
        yield SQLiteConnection(db_url)
    else:
        yield PostgresConnection(db_url)
```

#### 3.3 工件存储抽象

**目标:** 支持本地/云存储切换

```python
# backend/src/services/artifacts/store.py
from abc import ABC, abstractmethod

class ArtifactStore(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def load(self, key: str) -> bytes: ...

    @abstractmethod
    def get_url(self, key: str) -> str: ...

class LocalArtifactStore(ArtifactStore):
    """本地文件系统存储"""
    def __init__(self, base_path: Path):
        self.base_path = base_path

    def save(self, key: str, data: bytes) -> str:
        path = self.base_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

class S3ArtifactStore(ArtifactStore):
    """S3兼容存储 (未来扩展)"""
    pass
```

---

## 实施优先级

| 优先级 | 任务 | 风险 | 收益 | 预估工作量 |
|--------|------|------|------|------------|
| P0 | 1.2 前端Store拆分 | 低 | 高 | 4h |
| P0 | 1.3 SSE可靠性增强 | 低 | 高 | 3h |
| P1 | 1.1 后端接口抽象 | 低 | 中 | 6h |
| P1 | 2.2 前端组件层级优化 | 低 | 中 | 4h |
| P2 | 2.1 Pipeline步骤注册 | 中 | 高 | 4h |
| P2 | 2.3 API版本化 | 低 | 中 | 2h |
| P3 | 3.1 任务队列分离 | 高 | 高 | 8h |
| P3 | 3.2 数据库迁移准备 | 中 | 中 | 6h |
| P3 | 3.3 工件存储抽象 | 中 | 中 | 4h |

---

## 新功能扩展指南

### 添加新Pipeline步骤

1. 创建步骤执行器: `backend/src/services/pipeline/steps/new_step.py`
2. 实现`BaseStepExecutor`接口
3. 注册到`StepRegistry`
4. 前端`useTaskStore`添加步骤定义

### 添加新API端点

1. 创建路由: `backend/src/web/routers/new_feature.py`
2. 定义Schema: `backend/src/web/schemas.py`
3. 注册到`main.py`
4. 前端`api.ts`添加调用方法

### 添加新前端功能模块

1. 创建组件目录: `frontend/src/components/new_feature/`
2. 创建Store (如需要): `frontend/src/stores/useNewFeatureStore.ts`
3. 创建Composable (如需要): `frontend/src/composables/useNewFeature.ts`
4. 集成到`App.vue`或路由

---

## 风险与回退

| 改动 | 风险点 | 回退方案 |
|------|--------|----------|
| Store拆分 | 状态同步问题 | 保留原Store作为facade |
| SSE重连 | 事件丢失 | 轮询fallback |
| 接口抽象 | 过度设计 | 渐进式重构 |
| 任务队列 | 运维复杂度 | 保留同进程模式 |

---

## 监控指标

优化后需关注:

1. **API响应时间** - P95 < 200ms
2. **SSE连接稳定性** - 重连成功率 > 99%
3. **任务完成率** - > 99%
4. **前端首屏加载** - < 2s
5. **Store更新频率** - 无不必要的重渲染

---

## 总结

当前项目架构**整体良好**，主要优化方向:

1. **短期 (P0-P1):** Store拆分、SSE增强、接口抽象
2. **中期 (P2):** 步骤注册、组件重组、API版本化
3. **长期 (P3):** 任务队列、数据库迁移、云存储支持

建议按优先级逐步实施，每个Phase完成后进行回归测试，确保稳定性。
