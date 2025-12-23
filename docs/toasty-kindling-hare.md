# CPU+GPU 混合 OCR 推理方案

## 目标

接着D:\1something\Learning_Files\newvl\plan.md继续，感觉还不够压榨我这台设备的性能。想要GPU 忙时，溢出任务交给 CPU 处理，让两者都不空闲。

## 架构设计

```
         HybridPipelineManager (单例)
                    |
    +---------------+---------------+
    |                               |
GPU Pipeline                   CPU Pipeline
(Eager加载)                    (Lazy加载)
Semaphore(1)                   Semaphore(2)
~5.8GB VRAM                    ~1.5GB RAM
```

**路由逻辑：**
1. 非阻塞尝试获取 GPU 锁
2. GPU 忙 → 尝试 CPU 锁（带超时）
3. 都忙 → 阻塞等待 GPU（保持原有行为）

## 新增环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXAMPAPER_HYBRID_OCR` | `0` | 启用混合模式 |
| `EXAMPAPER_CPU_OCR_SLOTS` | `2` | CPU 并行槽位数 |
| `EXAMPAPER_CPU_FALLBACK_TIMEOUT` | `0.1` | CPU 槽位等待超时(秒) |

## 实施步骤

### Step 1: 修改 `ocr_models.py` 添加 device 参数

**文件:** `backend/src/common/ocr_models.py`

```python
def _create_ppstructure(device: Optional[str] = None) -> Any:
    """
    Args:
        device: 覆盖设备 ("gpu:N" 或 "cpu")。None 时从环境变量读取。
    """
    if device is not None:
        # 直接使用指定设备，跳过检测
        ...
```

### Step 2: 创建 `HybridPipelineManager`

**文件:** `backend/src/services/models/hybrid_pipeline.py` (新建)

```python
class HybridPipelineManager:
    """GPU + CPU 双管道调度器"""

    _instance: Optional["HybridPipelineManager"] = None

    def __init__(self):
        self._gpu_pipeline = None  # Eager 加载
        self._cpu_pipeline = None  # Lazy 加载
        self._gpu_sem = Semaphore(1)
        self._cpu_sem = Semaphore(int(os.getenv("EXAMPAPER_CPU_OCR_SLOTS", "2")))

    @contextmanager
    def acquire(self, log_fn=None):
        """获取可用管道，优先 GPU，溢出到 CPU"""
        # 非阻塞尝试 GPU
        if self._gpu_sem.acquire(blocking=False):
            try:
                yield (self._gpu_pipeline, "gpu")
            finally:
                self._gpu_sem.release()
            return

        # GPU 忙 → 尝试 CPU
        timeout = float(os.getenv("EXAMPAPER_CPU_FALLBACK_TIMEOUT", "0.1"))
        if self._cpu_sem.acquire(blocking=True, timeout=timeout):
            try:
                pipe = self._ensure_cpu_pipeline()
                if log_fn:
                    log_fn("[Hybrid] GPU busy, using CPU")
                yield (pipe, "cpu")
            finally:
                self._cpu_sem.release()
            return

        # 都忙 → 阻塞等 GPU
        self._gpu_sem.acquire(blocking=True)
        try:
            yield (self._gpu_pipeline, "gpu")
        finally:
            self._gpu_sem.release()

    def _ensure_cpu_pipeline(self):
        """Lazy 加载 CPU 管道"""
        if self._cpu_pipeline is None:
            self._cpu_pipeline = _create_ppstructure(device="cpu")
        return self._cpu_pipeline
```

### Step 3: 修改 `parallel_extraction.py`

**文件:** `backend/src/services/parallel_extraction.py`

1. 添加 `_HybridLockedPipeline` 类（使用 HybridPipelineManager）
2. 修改 `ParallelPageProcessor.__init__` 接受 `hybrid_manager` 参数
3. 在 `_process_single_page` 中根据配置选择包装器

### Step 4: 修改 `model_provider.py`

**文件:** `backend/src/services/models/model_provider.py`

在 `PPStructureProvider` 中集成 hybrid manager：

```python
def __init__(self):
    ...
    self._hybrid_manager = None
    if os.getenv("EXAMPAPER_HYBRID_OCR") == "1":
        from .hybrid_pipeline import HybridPipelineManager
        self._hybrid_manager = HybridPipelineManager.get_instance()
```

### Step 5: 更新 `manage.py`

**文件:** `manage.py`

添加新环境变量到 `DEFAULT_ENV_CONFIG`：

```python
DEFAULT_ENV_CONFIG = {
    ...
    "EXAMPAPER_HYBRID_OCR": "0",  # 默认禁用
    "EXAMPAPER_CPU_OCR_SLOTS": "2",
    "EXAMPAPER_CPU_FALLBACK_TIMEOUT": "0.1",
}
```

## 关键文件清单

| 文件 | 操作 |
|------|------|
| `backend/src/services/models/hybrid_pipeline.py` | 新建 |
| `backend/src/common/ocr_models.py` | 修改 |
| `backend/src/services/parallel_extraction.py` | 修改 |
| `backend/src/services/models/model_provider.py` | 修改 |
| `manage.py` | 修改 |

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| CPU 首次加载延迟 | 中 | Lazy 加载，仅在需要时初始化 |
| 内存增加 ~1.5GB | 低 | 24GB RAM 足够 |
| 向后兼容 | 低 | 默认 `HYBRID_OCR=0` 保持原行为 |

## 预期效果

- GPU 忙时 CPU 可处理溢出任务
- CPU 虽慢（30-60s/页），但总吞吐量提升
- 两种设备都不空闲
