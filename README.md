# PDF试卷自动切题与结构化工具 v2.2.0

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)
![Vue](https://img.shields.io/badge/Vue-3.x-brightgreen.svg)
![PaddleOCR](https://img.shields.io/badge/PaddleOCR-3.x-orange.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

基于 **PaddleOCR + PP-StructureV3** 的智能试卷处理平台，自动将 PDF 试卷切分成单个题目图片，支持 GPU 加速、页面级并发处理、断点续跑。

---

## 特性

- **智能识别**: 自动识别题号、大题标题、跨页续接
- **结构化输出**: JSON 格式题目元数据
- **高质量切图**: 智能裁剪边界，长图拼接
- **资料分析**: 特殊处理资料分析大题（题号 111-130 自动识别）
- **单次 OCR**: OCR 结果缓存，避免重复调用
- **Web 界面**: Vue 3 + TypeScript 现代化前端
- **断点续跑**: 每步骤检测完成状态，中断可续接
- **GPU 加速**: 3-10 倍速度提升
- **并发处理**: 页面级并发，2-3 倍额外加速

---

## 项目结构

```
newvl/
├── backend/                     # Python 后端
│   └── src/
│       ├── web/                 # FastAPI Web 层
│       │   ├── main.py          # 应用入口
│       │   ├── config.py        # 配置管理
│       │   ├── schemas.py       # 数据模型
│       │   ├── routers/         # API 路由
│       │   │   ├── tasks.py     # 任务管理
│       │   │   ├── files.py     # 文件下载
│       │   │   └── health.py    # 健康检查
│       │   └── services/        # 业务服务
│       │       └── task_service.py
│       ├── common/              # 公共工具
│       │   ├── types.py         # 类型定义
│       │   ├── paths.py         # 路径工具
│       │   ├── io.py            # 文件 IO
│       │   ├── image.py         # 图片处理
│       │   ├── ocr_models.py    # OCR 模型
│       │   └── utils.py         # 工具函数
│       ├── db/                  # 数据库层
│       │   ├── connection.py    # 连接管理
│       │   ├── schema.py        # 表结构
│       │   └── crud.py          # CRUD 操作
│       └── services/            # 业务逻辑
│           ├── pipeline/        # 处理流水线
│           │   ├── steps/       # 5 个处理步骤
│           │   ├── impl/        # 核心实现
│           │   │   ├── ocr_cache.py          # OCR 缓存
│           │   │   ├── structure_detection.py # 结构检测
│           │   │   └── crop_and_stitch.py    # 裁剪拼接
│           │   ├── runner.py    # 流水线执行器
│           │   └── contracts.py # 接口定义
│           ├── models/          # 模型管理
│           ├── recovery/        # 恢复服务
│           └── parallel_extraction.py
│
├── frontend/                    # Vue 3 前端
│   ├── src/
│   │   ├── components/          # Vue 组件
│   │   │   └── dashboard/       # 仪表盘组件
│   │   ├── composables/         # 组合式函数
│   │   ├── services/            # API 服务
│   │   └── stores/              # 状态管理
│   ├── dist/                    # 构建输出
│   └── package.json
│
├── scripts/                     # 脚本工具
│   ├── diagnostics/             # 诊断工具
│   │   ├── check_db.py
│   │   ├── check_extraction_integrity.py
│   │   └── check_images.py
│   └── archived/                # 归档脚本
│
├── config/                      # 配置文件
├── data/                        # 运行时数据
│   └── tasks.db                 # SQLite 数据库
├── pdf_images/                  # 处理输出
├── tests/                       # 测试用例
├── docs/                        # 文档
│
├── manage.py                    # 项目入口
├── requirements.txt             # Python 依赖
├── web_requirements.txt         # Web 依赖
└── README.md
```

---

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
pip install -r web_requirements.txt

# 安装前端依赖（可选，已有构建产物）
cd frontend && npm install && npm run build
```

### 2. 启动服务

```bash
# 默认启动（GPU 加速 + 并发处理）
python manage.py

# 指定端口和 worker 数
python manage.py web --port 9000 --workers 8

# 禁用 GPU
python manage.py web --no-gpu

# 访问 http://localhost:8000
```

### 3. 使用流程

1. 打开浏览器访问 `http://localhost:8000`
2. 上传 PDF 试卷文件
3. 选择处理模式（自动/手动）
4. 等待处理完成
5. 预览或下载题目图片

---

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXAMPAPER_USE_GPU` | `1` | GPU 加速 |
| `EXAMPAPER_MAX_WORKERS` | `4` | 并发数 |
| `EXAMPAPER_PARALLEL_EXTRACTION` | `1` | 并发提取 |
| `EXAMPAPER_PPSTRUCTURE_WARMUP` | `1` | 模型预热 |
| `FLAGS_fraction_of_gpu_memory_to_use` | `0.8` | 显存占用 |

### 推荐配置

**生产环境（GPU）**:
```bash
EXAMPAPER_USE_GPU=1
EXAMPAPER_PARALLEL_EXTRACTION=1
EXAMPAPER_MAX_WORKERS=4
EXAMPAPER_PPSTRUCTURE_WARMUP=1
```

**开发环境**:
```bash
EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC=1
EXAMPAPER_ALLOW_MODEL_RELOAD=1
```

---

## API 参考

### 核心端点

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/upload` | 上传 PDF |
| `POST` | `/api/process` | 开始处理 |
| `GET` | `/api/status/{id}` | 任务状态 |
| `GET` | `/api/results/{id}` | 处理结果 |
| `GET` | `/api/download/{id}` | 下载 ZIP |
| `GET` | `/api/history` | 历史记录 |

### 健康检查

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/health/live` | 存活检查 |
| `GET` | `/api/health/ready` | 就绪检查 |

---

## 处理流程

```
PDF 上传
    ↓
Step 0: PDF → 图片 (300 DPI)
    ↓
Step 1: OCR + 缓存
    - PP-StructureV3 只执行一次
    - 结果保存到 ocr/page_*.json
    ↓
Step 2: 结构检测
    - 读取 OCR 缓存（不再调用 OCR）
    - 检测资料分析区域（标题 + 题号 111-130 兜底）
    - 输出 structure.json
    ↓
Step 3: 裁剪拼接
    - 普通题 → q1.png ~ q110.png（跨页拼接）
    - 资料分析 → data_analysis_1.png ~ data_analysis_4.png
    - 不生成 q111-q130（已合并到大题）
    ↓
Step 4: 结果汇总
    - 验证输出完整性
    - 生成 summary.json
    ↓
下载 / 预览
```

### 输出目录结构

```
pdf_images/{exam_name}/
├── page_*.png              # 原始页面图片
├── ocr/
│   └── page_*.json         # OCR 缓存
├── structure.json          # 结构文档
├── questions_page_*/       # 中间结果（可忽略）
└── all_questions/          # 最终输出
    ├── q1.png ~ q110.png   # 普通题目
    ├── data_analysis_1.png # 资料分析大题
    ├── data_analysis_2.png
    ├── data_analysis_3.png
    ├── data_analysis_4.png
    └── summary.json        # 汇总信息
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
npm run dev      # 开发服务器
npm run build    # 构建生产版本
```

## 更新日志

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
