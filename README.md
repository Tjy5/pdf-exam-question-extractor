# PDF试卷自动切题与结构化工具 v2.3.1

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104.1-green.svg)
![Vue](https://img.shields.io/badge/Vue-3.x-brightgreen.svg)
![PaddleOCR](https://img.shields.io/badge/PaddleOCR-3.x-orange.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

基于 **PaddleOCR + PP-StructureV3** 的智能试卷处理平台，集PDF切题、AI答疑、错题管理于一体。核心功能包括：
- **PDF智能切题**：自动将 PDF 试卷切分成题目图片（普通题输出单题图，资料分析输出大题合并图）
- **AI聊天答疑**：集成LLM提供题目解析、教学指导和个性化答疑
- **错题本系统**：完整的错题收集、AI分析、知识标签和复习训练
- **实时进度推送**：基于 SSE 的实时处理状态和AI流式回复
- **手动分步执行**：灵活的处理流程控制，支持断点续跑和失败重试
- **GPU加速**：PaddleOCR GPU加速实现3-10倍性能提升

> **版本说明**: README 版本号为 v2.3.1，OpenAPI 文档版本暂为 v2.0.0（待对齐）

---

## 特性

### 核心能力
- **智能识别**: 自动识别题号、大题标题、跨页续接
- **结构化输出**: JSON 格式题目元数据
- **高质量切图**: 智能裁剪边界，长图拼接
- **资料分析**: 特殊处理资料分析大题（题号 111-130 自动识别）
- **单次 OCR**: OCR 结果缓存，避免重复调用

### 交互体验
- **实时进度推送（SSE）**: 基于服务端推送的实时日志和步骤状态，支持断线重连与关键事件回放
- **手动分步模式**: 可单步执行、从某步运行到结束、失败后重试或重置
- **按步骤查询结果**: API 支持查询每个步骤的中间产物（UI 查看入口待完善）
- **现代化 Web 界面**: Vue 3 + TypeScript，响应式设计

### 性能优化
- **GPU 加速**: 3-10 倍速度提升
- **并发处理**: 页面级并发，2-3 倍额外加速
- **智能续跑**: 基于产物检测，跳过已完成步骤（同 PDF hash 复用工作目录时有效）

### 稳定性改进 (v2.3.1)
- **GPU 线程稳定性**: 修复异步环境下 Paddle/CUDA 线程亲和性导致的 hang 问题
  - 模型初始化和预热在同一线程完成，避免跨线程状态不一致
  - 可选的线程绑定推理模式（默认启用）
  - 自动检测 GPU 并发度，高并发时禁用线程绑定以保持性能
- **保守参数策略**: 重构硬件参数自动计算逻辑，优先稳定性而非吞吐量
  - 6GB 及以下显卡：极保守配置（workers=2, batch=1/8, prefetch=2, vram=0.6）
  - 所有显卡：workers 上限降至 4（原 8），显存占用降至 60%（原 80%）
  - 零配置即可稳定运行，无需手动调整环境变量
- **数据库一致性**: 修复数据库步骤命名与Pipeline不一致问题，确保状态同步和错误处理
- **资源管理**: 改进 ThreadPoolExecutor 生命周期管理，防止线程泄漏
- **GPU 锁超时保护**: 120 秒超时机制防止无限等待（`EXAMPAPER_GPU_LOCK_TIMEOUT_S`）

### AI 智能功能
- **AI 聊天答疑**: 集成LLM进行题目解析和教学指导，支持SSE流式回复
- **错题本管理**: 完整的错题收集、AI分析和复习系统，支持知识点标签
- **智能图片分析**: 基于 Vision AI 自动识别上传的题目图片并生成解析
- **多模型支持**: 兼容 OpenAI、DeepSeek、Gemini 等多种模型，支持原生 Thinking 模式
- **流式交互**: 所有 AI 交互采用 Server-Sent Events (SSE) 实现实时响应

---

## 项目结构

```
newvl/
├── backend/                     # Python 后端
│   └── src/
│       ├── web/                 # FastAPI Web 层
│       │   ├── main.py          # 应用入口（含静态资源、API v1 重定向）
│       │   ├── config.py        # 配置管理
│       │   ├── schemas.py       # 数据模型
│       │   ├── routers/         # API 路由
│       │   │   ├── tasks.py     # 任务管理 + SSE 实时流
│       │   │   ├── files.py     # 文件下载
│       │   │   ├── health.py    # 健康检查
│       │   │   ├── exams.py     # 试卷管理、答案导入
│       │   │   ├── users.py     # 用户错题标记
│       │   │   ├── chat.py      # AI 聊天（SSE 流式）
│       │   │   └── wrong_notebook.py  # 错题本管理
│       │   └── services/        # Web 服务
│       │       ├── event_bus.py      # 内存事件总线
│       │       ├── event_infra.py    # 事件基础设施（持久化 + 发布）
│       │       ├── task_service.py   # 任务状态管理
│       │       └── task_executor.py  # 任务执行器
│       ├── services/            # 业务逻辑
│       │   ├── pipeline/        # 处理流水线
│       │   │   ├── steps/       # 处理步骤实现
│       │   │   ├── impl/        # 核心算法
│       │   │   ├── runner.py    # 流水线执行器
│       │   │   ├── registry.py  # 步骤注册表
│       │   │   ├── ports.py     # 端口抽象
│       │   │   └── contracts.py # 接口定义
│       │   ├── events/          # 事件持久化
│       │   ├── artifacts/       # 工件存储（预留）
│       │   ├── queue/           # 任务队列（预留）
│       │   ├── models/          # 模型管理（GPU加速、PP-StructureV3）
│       │   ├── recovery/        # 任务恢复（预留）
│       │   ├── ai/              # AI 服务（聊天、分析、错题本）
│       │   │   ├── base.py        # AI提供商抽象接口
│       │   │   ├── openai_compatible.py  # OpenAI兼容API实现
│       │   │   ├── mock_provider.py      # 开发测试模拟提供者
│       │   │   ├── prompts.py            # 系统提示词构建
│       │   │   └── parser.py             # 响应解析工具
│       │   ├── answers/         # 答案导入与匹配
│       │   │   └── answer_pdf_importer.py  # PDF答案提取和试卷匹配
│       │   └── tasks/           # 任务服务
│       ├── db/                  # 数据库层
│       │   ├── base.py          # 抽象基类
│       │   ├── connection.py    # 连接管理
│       │   ├── schema.py        # 表结构
│       │   └── crud.py          # CRUD 操作
│       └── common/              # 公共工具
│           ├── types.py         # 类型定义
│           ├── paths.py         # 路径工具
│           ├── io.py            # 文件 IO
│           ├── image.py         # 图片处理
│           ├── ocr_models.py    # OCR 模型
│           └── utils.py         # 工具函数
│
├── frontend/                    # Vue 3 前端
│   ├── src/
│   │   ├── views/               # 页面视图
│   │   │   ├── DashboardView.vue    # 主页（PDF处理）
│   │   │   ├── ChatView.vue         # AI 聊天页
│   │   │   ├── ReviewView.vue       # 试卷复习页
│   │   │   └── WrongNotebook.vue    # 错题本页
│   │   ├── components/          # Vue 组件
│   │   │   ├── upload/          # 上传区域
│   │   │   ├── pipeline/        # 流水线视图
│   │   │   ├── logs/            # 日志终端
│   │   │   ├── results/         # 结果画廊
│   │   │   ├── exams/           # 试卷列表、答案导入
│   │   │   ├── chat/            # 聊天组件（会话列表、Markdown渲染、思考块等）
│   │   │   └── common/          # 通用组件（错误边界、图片查看器等）
│   │   ├── stores/              # Pinia 状态管理
│   │   │   ├── useTaskStore.ts       # 任务状态
│   │   │   ├── useConnectionStore.ts # SSE 连接
│   │   │   ├── useLogsStore.ts       # 日志管理
│   │   │   ├── useResultsStore.ts    # 结果展示
│   │   │   ├── useExamStore.ts       # 试卷状态
│   │   │   ├── useChatStore.ts       # 聊天状态
│   │   │   ├── useUserStore.ts       # 用户状态
│   │   │   ├── useWrongStore.ts      # 错题标记
│   │   │   └── useWrongNotebookStore.ts  # 错题本状态
│   │   ├── router/              # Vue Router 路由
│   │   ├── services/            # API 服务
│   │   └── composables/         # 组合式函数
│   ├── dist/                    # 构建输出（由后端提供静态服务）
│   └── package.json
│
├── scripts/                     # 脚本工具
│   └── diagnostics/             # 诊断工具
│
├── config/                      # 配置文件
├── data/                        # 运行时数据
│   └── tasks.db                 # SQLite 数据库
├── pdf_images/                  # 处理输出
├── tests/                       # 测试用例
├── docs/                        # 文档
│
├── manage.py                    # 生产环境启动入口（硬件探测、默认配置）
├── dev.py                       # 开发环境启动入口（前后端同时启动）
├── requirements.txt             # Python 依赖
└── web_requirements.txt         # Web 依赖
```

---

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装 Python 依赖
pip install -r requirements.txt
pip install -r web_requirements.txt

# （可选）构建前端产物
# 如果使用已有的 frontend/dist/，可跳过此步
cd frontend
npm install
npm run build
```

### 2. 启动服务

**生产环境（推荐）**:
```bash
# 使用 manage.py 启动（会根据硬件自动配置）
python manage.py

# 自定义端口和并发数
python manage.py web --port 9000 --workers 8

# 禁用 GPU（CPU 模式）
python manage.py web --no-gpu

# 服务启动后访问 http://localhost:8000
```

**开发环境**:
```bash
# 使用 dev.py 同时启动前后端（热重载）
python dev.py

# 仅启动后端
python dev.py --backend

# 仅启动前端
python dev.py --frontend

# 开发环境访问：
#   后端 API: http://localhost:8000
#   前端页面: http://localhost:5173
```

> **注意**: 如果 `frontend/dist/` 不存在，后端会提示先构建前端。前端构建后由后端的 `/` 和 `/assets` 路由提供静态资源服务。

### 3. 使用流程

#### 自动模式（一键处理）
1. 打开浏览器访问 `http://localhost:8000`
2. 拖拽或点击上传 PDF 试卷文件
3. 选择 **自动模式**
4. 实时查看处理进度和日志
5. 处理完成后预览或下载题目图片

#### 手动模式（分步执行）
1. 上传 PDF 后选择 **手动模式**
2. 单击"执行下一步"逐步处理
3. 或点击"运行到结束"从当前步骤运行到完成
4. 每步完成后可查看该步骤的中间结果
5. 如果某步失败，可以"重试"或"重置"从该步重新开始

#### AI 聊天答疑功能
1. 访问 `http://localhost:8000` 并切换到 **AI 答疑** 页面
2. **选择试卷**：从已处理的试卷列表中选择要分析的试卷
3. **浏览题目**：使用题目导航器查看所有已处理题目
4. **创建会话**：点击题目开启AI答疑会话
5. **提问互动**：在聊天框中输入问题，AI会提供解析和教学指导
6. **特殊功能**：
   - **提示模式**：激活提示模式，AI将引导式教学而非直接给答案
   - **图片增强**：AI结合题目图片进行Vision分析
   - **流式回复**：实时看到AI思考过程

#### 错题本管理
1. **收集错题**：
   - 方式一：在试卷复习页面标记做错的题目
   - 方式二：上传错题图片，AI自动分析识别
2. **AI分析**：系统自动分析错题的考点和知识点
3. **标签管理**：为错题添加知识标签，建立体系化分类
4. **复习训练**：
   - 生成相似题目练习
   - 重新作答获取AI解析
   - 按知识点维度复习错题

---

## 配置

多数配置参数由 `manage.py` 根据硬件自动设置合理默认值，也可通过环境变量覆盖。

### 核心配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXAMPAPER_USE_GPU` | `1` | 是否启用 GPU 加速 |
| `FLAGS_fraction_of_gpu_memory_to_use` | `0.6` | GPU 显存占用比例（0.0-1.0） |
| `EXAMPAPER_PPSTRUCTURE_WARMUP` | `1` | 是否在启动时预热模型 |
| `EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC` | `0` | 是否异步预热（服务先启动，模型后台加载） |

### 并发与性能

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXAMPAPER_MAX_WORKERS` | `4` | 并行工作线程数 |
| `EXAMPAPER_PARALLEL_EXTRACTION` | `1` | 是否启用页面级并行提取 |
| `EXAMPAPER_DET_BATCH_SIZE` | 自动探测 | 检测 batch size |
| `EXAMPAPER_REC_BATCH_SIZE` | 自动探测 | 识别 batch size |
| `EXAMPAPER_PREFETCH_SIZE` | 自动探测 | CPU 预取队列大小 |

### 高级选项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXAMPAPER_STEP1_INPROC` | `1` | 第一阶段是否进程内执行 |
| `EXAMPAPER_STEP2_INPROC` | `1` | 第二阶段是否进程内执行 |
| `EXAMPAPER_STEP1_FALLBACK_SUBPROCESS` | `1` | 进程内失败时是否回退到子进程 |
| `EXAMPAPER_STEP2_FALLBACK_SUBPROCESS` | `1` | 同上 |
| `EXAMPAPER_LIGHT_TABLE` | `0` | 是否启用轻量表格识别模式 |

### AI 服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AI_PROVIDER` | `mock` | AI提供商类型：`openai_compatible`、`mock` |
| `AI_BASE_URL` | `https://api.openai.com/v1` | OpenAI兼容API的基础URL |
| `AI_API_KEY` | `your_key_here` | API密钥（不含空格） |
| `AI_MODEL` | `gpt-3.5-turbo` | 默认AI模型名称 |
| `AI_TIMEOUT` | `60` | API调用超时时间（秒） |
| `AI_MAX_TOKENS` | `2000` | 生成的最大token数 |
| `AI_TEMPERATURE` | `0.7` | 温度参数（0.0-2.0） |
| `AI_TOP_P` | `0.95` | Top-p采样参数（0.0-1.0） |
| `EXAMPAPER_CHAT_VISION_MAX_BYTES` | `1500000` | 聊天中图片的最大字节数（默认1.5MB） |

### 推荐配置

**生产环境（GPU）**:
```bash
EXAMPAPER_USE_GPU=1
EXAMPAPER_PARALLEL_EXTRACTION=1
EXAMPAPER_MAX_WORKERS=4
EXAMPAPER_PPSTRUCTURE_WARMUP=1
FLAGS_fraction_of_gpu_memory_to_use=0.6
```

**开发/调试环境**:
```bash
EXAMPAPER_MAX_WORKERS=2                # 降低资源占用
```

**CPU 环境**:
```bash
EXAMPAPER_USE_GPU=0
EXAMPAPER_PARALLEL_EXTRACTION=0
EXAMPAPER_MAX_WORKERS=2
EXAMPAPER_PPSTRUCTURE_WARMUP=0
```

---

## 处理流程

### 流水线步骤

系统将 PDF 处理分为 5 个步骤（同一工作目录下可跳过已完成产物）：

| 步骤 | 用户友好名称 | 代码步骤名 | 说明 |
|------|-------------|-----------|------|
| 0 | PDF → 图片 | `pdf_to_images` | PyMuPDF 高分辨率转换，支持并行渲染 |
| 1 | 题目提取 + OCR | `extract_questions` | PP-StructureV3版面分析 + OCR识别 + 题目边界检测，结果缓存到 `ocr/page_*.json` |
| 2 | 文档结构分析 | `analyze_data` | 分析题目边界关系，检测资料分析区域（标题检测 + 题号111-130兜底），输出 `structure.json` |
| 3 | 裁剪拼接 | `compose_long_image` | 普通题跨页拼接(`q1.png~q110.png`)，资料分析大题合并(`data_analysis_*.png`)，不生成q111-q130 |
| 4 | 结果汇总 | `collect_results` | 验证输出完整性，生成最终汇总文件 `summary.json` |

```
PDF 上传
    ↓
步骤 0: PDF → 图片 (高分辨率转换)
    ↓
步骤 1: 题目提取 + OCR
    - PP-StructureV3 版面结构分析
    - 题目切分与识别
    - 结果缓存到 ocr/page_*.json
    ↓
步骤 2: 资料分析处理
    - 检测资料分析区域（标题 + 题号 111-130 兜底）
    - 分析题目边界关系
    - 输出 structure.json
    ↓
步骤 3: 裁剪拼接
    - 普通题 → q1.png ~ q110.png（跨页拼接）
    - 资料分析 → data_analysis_1.png ~ data_analysis_4.png
    - 不生成 q111-q130（已合并到资料分析大题）
    ↓
步骤 4: 结果汇总
    - 验证输出完整性
    - 生成 summary.json
    ↓
下载 / 预览
```

### 输出目录结构

```
pdf_images/{文件名stem}__{sha256前8位}/
├── page_*.png              # 原始页面图片
├── ocr/
│   └── page_*.json         # OCR 缓存（避免重复调用）
├── structure.json          # 结构分析结果
├── questions_page_*/       # 中间产物（按页切分）
└── all_questions/          # 最终输出 ⭐
    ├── q1.png ~ q110.png   # 普通题目（已拼接跨页内容）
    ├── data_analysis_1.png # 资料分析大题（含材料）
    ├── data_analysis_2.png
    ├── data_analysis_3.png
    ├── data_analysis_4.png
    └── summary.json        # 汇总信息（题目列表、元数据）
```

> **注意**: `summary.json` 等 JSON 文件仅可通过 ZIP 下载或直接访问文件系统获取，`/api/image/*` 端点仅允许下载 PNG 图片。

---

## API 参考

后端 API 使用 `/api` 前缀，同时提供 `/api/v1/* → /api/*` 的兼容重定向。

### 任务与流水线

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/upload` | 上传 PDF（`multipart/form-data`：`file` + `mode=auto\|manual`） |
| `POST` | `/api/process` | 启动自动模式流水线（JSON：`{ "task_id": "..." }`）<br>**注意**: 仅对 `mode=auto` 有效；手动模式需使用下方的 steps API |
| `GET` | `/api/status/{task_id}` | 查询任务状态与增量日志（Query: `since`） |
| `GET` | `/api/results/{task_id}` | 获取最终结果图片列表 |
| `GET` | `/api/stream/{task_id}` | **SSE 实时事件流**（支持断线回放，见下文） |
| `POST` | `/api/tasks/{task_id}/steps/{step_index}/start` | 手动模式：启动指定步骤（Query: `run_to_end=true\|false`） |
| `GET` | `/api/tasks/{task_id}/steps/{step_index}/results` | 获取指定步骤的结果/产物<br>**注意**: 返回的 artifacts 列表最多 10 个（截断） |
| `POST` | `/api/tasks/{task_id}/restart/{from_step}` | 从指定步骤重置并重新执行 |

### 文件与下载

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/image/{task_id}/{filename}` | 获取单张结果图片（PNG，含路径穿越防护） |
| `GET` | `/api/download/{task_id}` | 下载结果压缩包（ZIP） |

### 健康检查

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/health/live` | 存活探针 |
| `GET` | `/api/health/ready` | 就绪探针（包含 GPU 信息） |
| `GET` | `/api/health/models/ppstructure` | PP-StructureV3 模型状态与 GPU 信息 |

### AI 聊天功能

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/chat/sessions` | 创建聊天会话（JSON: `{"user_id": "...", "exam_id": ..., "question_no": ...}`） |
| `GET` | `/api/chat/sessions` | 获取用户的聊天会话列表（Query: `user_id`, 可选 `exam_id`） |
| `GET` | `/api/chat/sessions/{session_id}/messages` | 获取会话的所有消息 |
| `POST` | `/api/chat/sessions/{session_id}/messages:stream` | **SSE 流式聊天**（发送消息并流式接收AI回复）<br>Content-Type: `application/json`, Body: `{"content": "...", "model": "..."}` |

### 试卷管理

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/exams` | 获取所有试卷列表 |
| `GET` | `/api/exams/{exam_id}` | 获取试卷详情（含题目列表） |
| `GET` | `/api/exams/{exam_id}/questions/{question_no}/image` | 获取题目图片（基于数据库，支持重启后访问） |
| `POST` | `/api/exams/{exam_id}/answers:import` | 批量导入标准答案（支持JSON/CSV/PDF格式） |
| `GET` | `/api/exams/{exam_id}/answers` | 获取试卷的所有答案（返回 `{"question_no": "answer"}` 映射） |
| `POST` | `/api/exams/answers:import-pdfs` | 批量导入服务器端answer目录中的PDF答案（自动匹配试卷） |

### 用户错题管理

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/users/{user_id}/exams/{exam_id}/wrongs` | 标记错题（JSON: `{"answers": {"1": "A", "2": "B"}}`） |
| `GET` | `/api/users/{user_id}/exams/{exam_id}/wrongs` | 获取用户的错题列表 |
| `DELETE` | `/api/users/{user_id}/exams/{exam_id}/wrongs/{question_no}` | 删除错题标记 |

### 错题本管理

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/wrong-notebook/analyze` | AI分析上传的错题图片（返回题目信息和知识点） |
| `POST` | `/api/wrong-notebook/items` | 创建错题本条目（JSON: 参考`WrongItemCreate`模型） |
| `GET` | `/api/wrong-notebook/items` | 获取用户的错题本条目（Query: `user_id`, 可选过滤条件） |
| `GET` | `/api/wrong-notebook/items/{item_id}` | 获取错题本条目详情 |
| `POST` | `/api/wrong-notebook/items/{item_id}/practice` | 生成相似题目练习（SSE流式） |
| `POST` | `/api/wrong-notebook/items/{item_id}/reanswer` | 重新作答（获取AI解析指导） |
| `GET` | `/api/wrong-notebook/tags` | 获取知识标签树（按科目分类的层级结构） |
| `POST` | `/api/wrong-notebook/tags` | 创建知识标签（管理员功能） |

### SSE 事件流说明

**端点**: `GET /api/stream/{task_id}`

**断线回放**:
- 通过 Query 参数 `last_event_id` 或 HTTP Header `Last-Event-ID` 指定断点（二选一）
- 服务端从 SQLite 中回放该任务的历史事件（仅带 `id` 的关键事件）

**事件类型**:
- `step`: 步骤状态快照（包含每步状态、进度、错误、产物数量等）
- `log`: 日志条目
- `done`: 任务结束（`data` 为 `"completed"` 或 `"error"`）

**注意**:
- 进度更新（progress）为 live-only，不会持久化；仅关键状态变化会写入 DB
- DB 写入失败时会降级为 live-only 模式

**示例**:
```bash
# 初次连接
curl -N http://localhost:8000/api/stream/task123

# 断线重连（使用 Query 参数）
curl -N http://localhost:8000/api/stream/task123?last_event_id=42

# 断线重连（使用 Header）
curl -N -H "Last-Event-ID: 42" http://localhost:8000/api/stream/task123
```

---

## 开发

### 运行测试

```bash
cd tests
python test_db_basic.py
python test_web_integration.py
```

### 前端开发

```bash
cd frontend
npm install
npm run dev      # 开发服务器（Vite）
npm run build    # 构建生产版本
```

### 架构扩展点

**已接入主流程**:
- **步骤注册表** (`pipeline/registry.py`): 动态注册和管理处理步骤
- **端口抽象** (`pipeline/ports.py`): 定义了可替换的接口（如存储、队列）
- **事件基础设施** (`services/events/`): SSE 事件持久化与回放

**预留扩展点（未完全接入）**:
- **工件存储** (`services/artifacts/`): 本地文件存储抽象，可扩展为对象存储（S3、OSS 等）
- **任务队列** (`services/queue/`): 内存队列抽象，可扩展为 Redis/RabbitMQ
- **任务恢复** (`services/recovery/`): 进程重启后的任务恢复（预留）

> **说明**: 当前 Web 层的任务对象主要在内存中管理（服务重启后 task_id 失效）；SSE 事件会持久化到 SQLite 用于断线回放，但暂未提供任务历史列表类 API。产物的"续跑"能力基于工作目录检测，而非任务记录恢复。

## 更新日志

### v2.3.0 (2025-12-14)

**新增功能**:
- **实时进度推送（SSE）**:
  - 通过 `/api/stream/{task_id}` 实时推送步骤状态、日志和处理进度
  - 支持断线重连与 `last_event_id` 关键事件回放
  - 事件持久化到 SQLite（关键状态变化）
- **手动分步模式**:
  - 上传时可选择 `mode=manual`，逐步执行处理流程
  - 支持单步执行、从某步运行到结束、失败后重试或重置
- **按步骤查询结果**:
  - 新增 `GET /api/tasks/{task_id}/steps/{step_index}/results` 端点
  - 可查询每个步骤的产物和错误信息（UI 查看入口待完善）
- **增强的健康检查**:
  - `GET /api/health/models/ppstructure` 返回模型状态和 GPU 信息
  - 便于部署和运维监控

**架构优化**:
- 引入事件驱动架构（Event Bus + Event Store）
- 新增步骤注册表（Step Registry），支持动态注册处理步骤
- 前端组件模块化重构（Upload/Pipeline/Logs/Results）
- 新增多个 Pinia stores 管理状态（Connection/Logs/Results/Task）

**API 变更**:
- 移除文档中不存在的 `/api/history` 端点
- 新增 API v1 兼容重定向 (`/api/v1/* → /api/*`)
- 增强文件下载安全性（路径穿越防护）

**文档更新**:
- 修正 FastAPI 版本号徽章（0.115+ → 0.104.1）
- 更新项目结构图，反映新的模块组织
- 补充 SSE 事件流使用说明和示例
- 新增架构扩展点说明

### v2.3.1 (2025-12-16)

**稳定性改进**:
- **GPU 线程稳定性**: 修复异步环境下 Paddle/CUDA 线程亲和性导致的 hang 问题
  - 模型初始化和预热在同一线程完成，避免跨线程状态不一致
  - 可选的线程绑定推理模式（默认启用）
  - 自动检测 GPU 并发度，高并发时禁用线程绑定以保持性能
- **保守参数策略**: 重构硬件参数自动计算逻辑，优先稳定性而非吞吐量
  - 6GB 及以下显卡：极保守配置（workers=2, batch=1/8, prefetch=2, vram=0.6）
  - 所有显卡：workers 上限降至 4（原 8），显存占用降至 60%（原 80%）
  - 零配置即可稳定运行，无需手动调整环境变量
- **数据库一致性**: 修复数据库步骤命名与Pipeline不一致问题，确保状态同步和错误处理
- **资源管理**: 改进 ThreadPoolExecutor 生命周期管理，防止线程泄漏
- **GPU 锁超时保护**: 120 秒超时机制防止无限等待（`EXAMPAPER_GPU_LOCK_TIMEOUT_S`）

### v2.2.0 (2025-12-13)

**流程重构**:
- OCR 结果缓存：PP-StructureV3 只执行一次，结果保存到 `ocr/page_*.json`
- 结构检测分离：从 OCR 缓存读取，不再重复调用 OCR
- 题号兜底：即使未检测到"资料分析"标题，111-130 题号自动归入资料分析
- 材料区域捕获：`data_analysis_*.png` 包含完整的图表/文字材料

**性能提升**:
- 消除了重复 OCR 调用（原来 Step 2 会再次调用 OCR）
- 断点续接：每步骤检测完成状态，中断后可从断点继续

**新增文件**:
- `impl/ocr_cache.py` - OCR 结果缓存
- `impl/structure_detection.py` - 结构检测 + 题号兜底
- `impl/crop_and_stitch.py` - 裁剪拼接

### v2.1.0 (2025-12-13)

**重构**:
- 前后端完全分离：`frontend/` + `backend/`
- 拆分 `app.py` 为模块化结构
- 整理脚本到 `scripts/` 目录

**目录变更**:
- `web_interface/` → `frontend/` + `backend/src/web/`
- `src/` → `backend/src/`

### v2.0.2 (2025-12-13)

- 页面级并发处理
- 两阶段处理架构
- 性能提升 2-3 倍

### v2.0.1 (2025-12-12)

- SQLite 持久化
- 断点续跑
- 模型预热机制

---

## 许可证

MIT License

---

## 贡献

欢迎提交 Issue 和 Pull Request！
