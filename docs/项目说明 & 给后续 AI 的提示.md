# 项目说明 & 给后续 AI 的提示 (v2.0)

> **⚠️ 重要更新**: 本项目已于 2025-12-11 完成 v2.0 架构重构。如果你是之前参与过v1.x的AI，请优先阅读本文档的"架构变更说明"部分。

---

## 🎯 项目概述

这是一个**把 PDF 试卷页面自动切分成单题图片，并保留题目文字/表格结构**的智能工具。使用 **PaddleOCR 3.x + PP-StructureV3** 进行版面解析和文字识别。

### 核心功能

- 🎯 自动识别页面布局和文字
- 📝 按题号将页面划分成单题
- 📊 输出每道题的截图 + 文字和表格结构
- 🔗 支持跨页题目自动拼接
- 📈 特殊处理资料分析大题
- 🌐 提供CLI和Web两种交互方式

---

## ⚡ 快速开始（v2.0）

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 启动程序

```bash
# 推荐：使用统一入口
python manage.py          # CLI交互式菜单
python manage.py web      # Web界面

# Windows 快捷启动（Web界面）
start_web.bat             # 双击启动
```

---

## 🆕 v2.0 架构变更说明（重要！）

### 关键变更

| 方面 | v1.x | v2.0 |
|------|------|------|
| **入口** | 多个独立脚本 | 统一 `manage.py` |
| **公共模块** | 单文件 `common.py` (692行) | 模块化 `src/common/` |
| **配置** | 硬编码在脚本中 | YAML配置系统 `config/` |
| **数据目录** | `pdf_images/` (混在根目录) | `data/output/` (独立管理) |
| **文档** | 单一README | 分类文档 `docs/` |
| **Git** | 追踪所有数据 | 只追踪代码 |

### 新目录结构

```
newvl/                            # v2.0
├── src/                          # ⭐ 核心代码（新增）
│   ├── common/                   # 公共模块（已模块化）
│   │   ├── types.py              # 常量和类型
│   │   ├── paths.py              # 路径工具
│   │   ├── io.py                 # JSON读写
│   │   ├── image.py              # 图片处理
│   │   ├── ocr_models.py         # OCR模型管理
│   │   └── utils.py              # 工具函数
│   ├── core/                     # 核心算法
│   ├── ocr/                      # OCR封装
│   ├── postprocess/              # 后处理
│   ├── compose/                  # 长图拼接
│   ├── analysis/                 # 数据分析
│   └── services/                 # 服务层
├── config/                       # ⭐ 配置文件（新增）
│   ├── global_settings.yaml
│   ├── exam_gd_2025.yaml
│   └── exam_sihai_2025.yaml
├── data/                         # ⭐ 数据目录（新增，不入Git）
│   ├── input/                    # 输入PDF
│   ├── interim/                  # 中间文件
│   ├── output/                   # 处理结果
│   │   ├── gd_2025/
│   │   └── sihai_2025_h2_1/
│   └── cache/                    # 缓存
├── scripts/                      # ⭐ 辅助脚本（新增）
│   ├── archived/                 # 实验代码归档
│   └── migrate_data_v1_to_v2.py  # 数据迁移工具
├── docs/                         # ⭐ 文档（新增）
│   ├── README.md                 # v1.x详细文档
│   ├── PaddleOCR完整使用指南.md
│   └── 项目说明 & 给后续 AI 的提示.md (本文档)
├── web_interface/                # Web界面
│   ├── app.py                    # FastAPI应用
│   └── templates/                # 前端模板
├── manage.py                     # ⭐ 统一入口（新增）
├── start_web.bat                 # Windows Web启动脚本
├── common.py                     # ⚠️ 向后兼容层（将弃用）
├── extract_questions_ppstruct.py # 主处理脚本
├── make_data_analysis_big.py     # 资料分析处理
├── compose_question_long_image.py # 长图拼接
└── requirements.txt
```

### 向后兼容性

✅ **现有脚本无需修改**，v1.x的调用方式仍然有效：
- `common.py` 作为兼容层重新导出 `src.common` 的函数
- 所有 `from common import xxx` 仍然有效
- Web界面使用 `start_web.bat` 快捷启动

⚠️ **推荐新代码使用新导入方式**：
```python
# v1.x（仍然支持，但不推荐）
from common import get_ppstructure, load_meta

# v2.0（推荐）
from src.common import get_ppstructure, load_meta
from src.common.ocr_models import get_ppstructure
from src.common.io import load_meta
```

---

## 📁 核心模块说明

### 1. `src/common/` - 公共模块（已模块化）

**v2.0 将原 `common.py` (692行) 拆分为6个专门模块**：

#### `types.py` - 常量和类型定义
- 题号识别正则：`QUESTION_HEAD_PATTERN`
- 大题关键字：`SECTION_HEAD_KEYWORDS`
- 噪声关键字：`NOISE_TEXT_KEYWORDS`
- 路径常量：`DEFAULT_DATA_DIR`, `LEGACY_PDF_IMAGES_DIR`

#### `paths.py` - 路径工具
- `page_index()` - 页码排序
- `resolve_image_path()` - 路径解析（✨ 支持目录重命名后的路径修复）
- `get_meta_path()` - 获取meta.json路径
- `iter_meta_paths()` - 遍历meta文件
- `auto_latest_exam_dir()` - 自动选择最近试卷目录
- `get_data_dir()` - 获取数据目录
- `resolve_exam_dir_by_hash()` - 基于PDF hash的目录管理

#### `io.py` - 文件IO操作
- `load_meta()` / `save_meta()` - meta.json读写
- `load_json()` / `save_json()` - 通用JSON操作

#### `image.py` - 图片处理
- `union_boxes()` - 计算bbox并集
- `crop_and_save()` - 裁剪并保存图片
- `crop_page_and_save()` - 按页面裁剪
- `compose_vertical()` - 垂直拼接长图
- `compute_smart_crop_box()` - 智能裁剪边界计算
- `find_footer_top_from_meta()` - 页脚位置检测

#### `ocr_models.py` - OCR模型管理
- `get_ppstructure()` - PP-StructureV3单例
- `layout_blocks_from_doc()` - 版面块标准化
- `get_offline_model_path()` - 离线模型路径

#### `utils.py` - 版面分析工具
- `is_section_boundary_block()` - 判断分区标题
- `detect_section_boundaries()` - 检测所有分区边界
- `detect_continuation_blocks()` - 跨页续接检测（带置信度）

### 2. `config/` - 配置管理系统

#### 配置文件层级
```
global_settings.yaml (全局默认)
    ↓ 覆盖
exam_*.yaml (试卷特定配置)
    ↓ 覆盖
命令行参数
```

#### 配置文件结构示例
```yaml
# config/global_settings.yaml
ocr:
  engine: paddle
  gpu_enable: false

extraction:
  question_pattern: '(?:^|\n|。)\s*(\d{1,3})[\.．、]\s*'
  margin_ratio: 0.008

paths:
  input_dir: data/input
  output_dir: data/output
```

### 3. 主要处理脚本

#### `extract_questions_ppstruct.py` - 题目提取
- 使用 PP-StructureV3 进行版面分析
- 自动识别题号、大题标题
- 处理跨页续接
- 输出结构化JSON

**使用方式**：
```bash
# v1.x方式（仍然支持）
python extract_questions_ppstruct.py
python extract_questions_ppstruct.py --dir pdf_images/试卷名 6 7

# v2.0方式（推荐，待实现）
python manage.py process --config config/exam_gd_2025.yaml
```

#### `make_data_analysis_big.py` - 资料分析处理
- 自动识别资料分析页面
- 生成大题级截图
- 输出 `big_questions` 结构

#### `compose_question_long_image.py` - 长图拼接
- 拼接跨页题目
- 生成长图
- 更新meta信息

---

## 🔧 开发指南（给AI）

### 1. 代码修改建议

#### ✅ 推荐做法

```python
# 导入新模块
from src.common.ocr_models import get_ppstructure
from src.common.io import load_meta, save_meta
from src.common.image import crop_and_save
from src.common.paths import auto_latest_exam_dir

# 使用配置系统
import yaml
with open('config/exam_gd_2025.yaml') as f:
    config = yaml.safe_load(f)
```

#### ❌ 避免做法

```python
# 不要在src/模块中使用根目录的common.py
from common import xxx  # 旧方式

# 不要硬编码路径
img_dir = Path("pdf_images/试卷名")  # 应该使用配置
```

### 2. 添加新功能

1. **确定模块位置**：
   - 图片处理 → `src/common/image.py`
   - OCR相关 → `src/common/ocr_models.py`
   - 路径工具 → `src/common/paths.py`
   - 新的核心算法 → `src/core/`

2. **添加配置项**：
   - 在 `config/global_settings.yaml` 添加默认值
   - 在试卷配置中可覆盖

3. **更新文档**：
   - 更新本文档的相关章节
   - 更新根目录 README.md

### 3. 数据管理

#### v2.0数据结构

```
data/output/{exam_id}/
├── pages/              # 整页图片
│   └── page_*.png
├── questions/          # 切好的题目
│   ├── questions_page_*/
│   │   ├── q*.png
│   │   └── meta.json
│   └── all_questions/  # 汇总
├── metadata.json       # 试卷元数据
└── exam_questions.json # 题目汇总
```

#### 迁移v1.x数据

```bash
# 先模拟运行
python scripts/migrate_data_v1_to_v2.py --dry-run

# 确认后执行
python scripts/migrate_data_v1_to_v2.py

# 验证
python manage.py cli
```

---

## 📋 核心逻辑说明

### 题目提取流程

```
1. 加载PP-StructureV3（单例）
   ↓
2. 版面块抽取（layout_blocks_from_doc）
   ↓
3. 检测section boundaries（detect_section_boundaries）
   ↓
4. 按题号分段
   - 识别题号正则
   - 确定每题范围
   ↓
5. 处理跨页续接（detect_continuation_blocks）
   - 识别续接内容
   - 评估置信度
   ↓
6. 计算裁剪框（compute_smart_crop_box）
   - 动态margin计算
   - 排除页眉页脚
   ↓
7. 裁剪并保存
   - 生成题目图片
   - 保存meta.json
```

### 智能裁剪算法

```python
# src/common/image.py
def compute_smart_crop_box(
    blocks: list[dict],
    page_size: tuple[int, int],
    footer_top: Optional[int] = None,
    use_full_width: bool = True,
    margin_ratio: float = 0.008,  # 相对页面尺寸
    min_margin: int = 3,
    max_margin: int = 15,
) -> tuple[int, int, int, int]:
    """
    改进点：
    1. margin基于页面尺寸动态计算
    2. 自动排除header/footer/number块
    3. 考虑footer位置避免截入页脚
    """
```

### 跨页检测算法

```python
# src/common/utils.py
def detect_continuation_blocks(
    blocks: list[dict],
    section_boundaries: Optional[set[int]] = None,
    prev_question_context: Optional[dict] = None,
) -> tuple[list[dict], float]:
    """
    返回：(续接块列表, 置信度0.0-1.0)

    置信度评估：
    - 0.9: 候选块<=2, 位置靠近顶部
    - 0.7: 候选块<=5
    - 0.5: 候选块>5
    - 0.0: 无续接或遇到section boundary
    """
```

---

## ⚠️ 重要约定（必读！）

### 1. 不要修改的内容

- ❌ **`pdf_images/questions_page6`** (无下划线)
  - 人工精调的"黄金标准"
  - 任何脚本和AI都不要改动

### 2. 配置优先级

```
硬编码 < 全局配置 < 试卷配置 < 命令行参数
```

始终优先使用配置文件，避免硬编码。

### 3. 路径规范

- ✅ 使用 `Path` 对象
- ✅ 使用配置系统获取路径
- ✅ 使用 `src.common.paths` 工具函数
- ❌ 避免硬编码路径字符串

### 4. 模型缓存

- 离线模型路径：`~/.paddlex/official_models`
- 自动fallback机制已实现
- 不要多次初始化模型（使用单例）

---

## 🔍 故障排除（给AI）

### 导入错误

```python
# 错误：ModuleNotFoundError: No module named 'src'
# 解决：确保在项目根目录运行，或使用相对导入

# 正确方式1：从根目录运行
python manage.py

# 正确方式2：使用向后兼容层
from common import get_ppstructure  # 仍然有效
```

### 配置文件不存在

```python
# 错误：FileNotFoundError: config/exam_xxx.yaml
# 解决：复制模板创建新配置

cp config/exam_gd_2025.yaml config/exam_new.yaml
# 然后修改exam_info部分
```

### 数据路径问题

```python
# v1.x路径（旧）
img_dir = Path("pdf_images/试卷名")

# v2.0路径（新）
from src.common.paths import get_data_dir
img_dir = get_data_dir("output") / "exam_id"
```

---

## 📚 相关文档

- [README.md](../README.md) - 用户使用指南
- [PaddleOCR完整使用指南.md](PaddleOCR完整使用指南.md) - OCR技术文档
- [config/README.md](../config/README.md) - 配置系统说明
- [scripts/archived/README.md](../scripts/archived/README.md) - 归档代码说明

---

## 🤖 给AI的提示

### 如果你要修改代码

1. **优先查看**：
   - 本文档的"核心模块说明"
   - 相关模块的docstring
   - `config/global_settings.yaml`

2. **修改前确认**：
   - 是否影响向后兼容性？
   - 是否需要更新配置文件？
   - 是否需要数据迁移？

3. **测试方法**：
   ```bash
   # 基本功能测试
   python manage.py cli

   # 单独测试模块
   python -c "from src.common import get_ppstructure; print('OK')"
   ```

### 如果遇到问题

1. 检查 `.gitignore` 是否正确排除数据
2. 检查 `common.py` 向后兼容层是否正常
3. 检查配置文件路径是否正确
4. 查看 `docs/README.md` 了解v1.x的详细逻辑

---

## 🐛 已知问题修复记录

### v2.0.1 (2025-12-12)

1. **路径解析增强** (`src/common/paths.py:28-80`)
   - **问题**: meta.json 中存储的路径包含旧目录名（如 `_v2` 后缀），但实际目录已重命名
   - **修复**: `resolve_image_path` 现在支持：
     - 跨平台路径分隔符规范化
     - 提取 `questions_page_X/filename` 部分进行智能匹配
     - 文件名兜底搜索机制
   - **影响**: 修复 Web 界面步骤4（结果汇总）无法复制题目图片的问题

2. **资料分析大题拼接优化** (`make_data_analysis_big.py:189`)
   - **问题**: 材料图片和题目图片之间间隙过小（50px），导致大模型识别困难
   - **修复**: 增加垂直间隙至 200px，提升可读性
   - **影响**: 改善 all_questions 目录中 `data_analysis_*.png` 的视觉质量

3. **CLI 工具简化**
   - **变更**: 移除独立的 `cli_menu.py`，统一使用 `manage.py` 和 Web 界面
   - **推荐**: Windows 用户使用 `start_web.bat` 快捷启动

---

**版本**: v2.0.1
**最后更新**: 2025-12-12
**重构完成**: ✅ 核心架构已重构完成，向后兼容
