# PaddleOCR 完整使用指南（更新至 2025-12-06）

面向 PaddleOCR 3.x 系列的实战笔记，重点围绕四条主力产线：

- **PP-OCRv5**：通用 OCR 识别（检测 + 识别）。
- **PP-StructureV3**：文档结构化（版面、表格、公式、图表）。
- **PP-ChatOCRv4**：基于大模型的关键信息抽取。
- **PaddleOCR-VL**：视觉语言模型，多模态文档解析。

---

## 1. 版本与依赖概览

- 推荐组合：**PaddleOCR 3.x + 对应版本的 PaddlePaddle（具体版本以官网 update 页面为准）**。  
- Python 版本：3.8–3.12。  
- 硬件：
  - CPU 可跑全套产线，但速度较慢。
  - GPU 推荐 CUDA 11.8/12.x + 8GB 以上显存；VL 建议 16GB+。
- 主要组件对应的安装 extra：
  - 基础 OCR：`paddleocr`
  - 文档解析 / 结构化：`paddleocr[doc-parser]`
  - 信息抽取（ChatOCR）：`paddleocr[ie]`

---

## 2. 安装与环境准备

### 2.1 安装 PaddlePaddle

以国内源为例（请按自己平台和官方文档选择对应轮子，以下仅为示意）：

```bash
# CPU
python -m pip install "paddlepaddle" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

# GPU（CUDA 示例，具体 CUDA 版本以官网说明为准）
python -m pip install "paddlepaddle-gpu" -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
```

安装后可以用 `python -c "import paddle; print(paddle.__version__)"` 验证版本。

### 2.2 安装 PaddleOCR

根据需求选择不同 extra：

```bash
# 只做通用 OCR
python -m pip install -U "paddleocr"

# 含文档结构化 / VL / 翻译等全部能力
python -m pip install -U "paddleocr[all]"

# 只做文档解析（PP-StructureV3 / PaddleOCR-VL）
python -m pip install -U "paddleocr[doc-parser]"

# 只做文档信息抽取（PP-ChatOCRv4）
python -m pip install -U "paddleocr[ie]"
```

---

## 3. 四条主力产线概览

### 3.1 PP-OCRv5（通用 OCR）

**定位**：一条从图片到文本的通用产线，包含文本检测、文本行方向分类（可选）、文本识别。  
**特点**：
- 提供 `server` 与 `mobile` 两套模型，`server` 精度更高，`mobile` 更轻量。
- 单模型支持简体中文、繁体中文、英文、日文等多种文字类型，覆盖票据、表格、文档、截图等常见场景。
- 默认命令行产线使用 **PP-OCRv5_server**。

**典型命令行**：

```bash
# 默认（PP-OCRv5_server）整条 OCR 产线
paddleocr ocr -i ./demo.png --ocr_version PP-OCRv5

# 使用轻量模型
paddleocr ocr -i ./demo.png --ocr_version PP-OCRv5 --use_mobile_model True
```

适合：试卷题目、普通文档、截图、票据等“以文字为主”的场景。

### 3.2 PP-StructureV3（文档结构化）

**定位**：从整页文档图像中恢复“结构 + 文本”，支持：

- 版面区域检测：段落、标题、表格、图片、公式、页眉页脚等。
- 表格结构识别：单元格网格 + 文本，支持复杂合并单元格。
- 公式识别、图表解析（配合子产线）。
- 输出 Markdown / JSON / HTML，便于后处理。

**典型命令行**：

```bash
# 结构化解析整页文档
paddleocr pp_structurev3 -i ./doc.png \
  --use_doc_orientation_classify False \
  --use_doc_unwarping False
```

适合：试卷、报告、研报、古籍等版面复杂、需要保留“段落 + 表格 + 公式”结构的场景。

### 3.3 PP-ChatOCRv4（文档信息抽取）

**定位**：在 OCR 和结构化的基础上，结合大语言模型（LLM/MLLM）做“问答 + 信息抽取”，例如：

- 从合同中抽取甲乙方信息、金额、时间等字段。
- 从复杂表格 / 多页 PDF 中抓取指标并生成结论性文字。

**特点**：
- 上游仍然调用 PP-Structure / PP-OCR 系列模型做视觉解析。
- 下游通过大模型将结构化结果转成自然语言摘要或结构化字段。

**示意命令行（以文档模式为例）**：

```bash
# 需正确配置大模型后端（文档有详细说明）
paddleocr pp_chatocrv4_doc -i ./doc.png --ie_version PP-ChatOCRv4
```

**Python 使用思路**（简化示意）：

```python
from paddleocr import PPChatOCRv4Doc

pipeline = PPChatOCRv4Doc()  # 实际使用时需提供大模型配置
result = pipeline.predict("./doc.png", prompt="请列出文中的考试时间和分值")
print(result)
```

本仓库当前主要用到的是 **PP-StructureV3 + PP-OCRv5**，PP-ChatOCRv4 可在后续需要做“自动摘要 / 自动填表 / 抽取关键信息”时接入。

### 3.4 PaddleOCR-VL（视觉语言模型）

**定位**：页级文档解析 + 元素级理解的多模态模型。  
**特点**：

- 核心模型：**PaddleOCR-VL-0.9B**，将视觉编码器（NaViT 风格）与轻量语言模型结合。
- 支持 100+ 语言，擅长同时识别**文本、表格、公式、图表**。
- 对资源要求相对适中，可通过 Docker 离线部署或结合 vLLM/SGLang/FastDeploy 加速。

**典型命令行**：

```bash
# 使用 VL 做文档解析
paddleocr doc_parser -i ./report.png --use_layout_detection True
```

**Python 示例**：

```python
from paddleocr import PaddleOCRVL

vl = PaddleOCRVL(use_layout_detection=True)
result = vl.predict("report.png")
for page in result:
  page.save_to_markdown("output")  # 也可保存 JSON / 可视化图片
```

适合：多语种、复杂结构（大量表格/图表/公式）的高精度场景，例如研报、年报、复杂答题卡等。

---

## 4. 命令行快速对照

| 场景 | 推荐命令 |
|------|----------|
| 普通图片文字识别 | `paddleocr ocr -i img.png --ocr_version PP-OCRv5` |
| 只检测不识别 | `paddleocr text_detection -i img.png` |
| 只识别已裁好的文本行 | `paddleocr text_recognition -i img_crop.png` |
| 文档结构化（表格/段落/标题） | `paddleocr pp_structurev3 -i doc.png` |
| 文档信息抽取（需要大模型） | `paddleocr pp_chatocrv4_doc -i doc.png` |
| 多模态 VL 文档解析 | `paddleocr doc_parser -i doc.png --use_layout_detection True` |

---

## 5. Python API 速查

### 5.1 PP-OCRv5：整条 OCR 产线

```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(
    lang="ch",             # 语言：ch / en / ... 
    ocr_version="PP-OCRv5",
    use_gpu=True,
)
result = ocr.ocr("demo.png")
for page in result:
    for line in page:
        bbox, (text, score) = line
        print(text, score)
```

### 5.2 PP-StructureV3：文档结构化

```python
from paddleocr import PPStructureV3

pp = PPStructureV3(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
)
layout = pp.predict("doc.png")
for page in layout:
    page.save_to_markdown("output")  # 也可 save_to_json / save_to_img
```

### 5.3 PP-ChatOCRv4：信息抽取（示意）

```python
from paddleocr import PPChatOCRv4Doc

pipeline = PPChatOCRv4Doc(
    # llm_client_config=...   # 这里配置大模型服务
)
resp = pipeline.predict(
    input="doc.png",
    prompt="请给出文中出现的所有年份和对应的指标值",
)
print(resp)
```

在本项目中，我们不直接在代码里硬编码大模型地址，而是将其放在配置文件 `chatocr_config.json` 中，由 `run_chatocr_on_big_questions.py` 读取并传给 PP-ChatOCRv4。

### 5.4 PaddleOCR-VL：多模态解析

```python
from paddleocr import PaddleOCRVL

vl = PaddleOCRVL(use_layout_detection=True)
pages = vl.predict("report.png")
for p in pages:
    p.save_to_markdown("output")
```

---

## 6. 模型选择与常用参数

- **模型大小：server vs mobile**
  - `*_server_*`：精度高、速度略慢，适合服务器端批量处理。
  - `*_mobile_*`：轻量、适合本地/边缘设备。
- **设备选择**
  - `use_gpu=True` 或 `device="gpu:0"`：优先使用 GPU。
  - CPU 环境下可关闭高性能选项，如 `use_tensorrt=False`。
- **高性能推理**
  - `enable_hpi=True`：开启高性能推理（HPI）。
  - `use_tensorrt=True` + `precision="fp16"`：GPU 上进一步加速（需安装匹配的 TensorRT）。
- **自定义模型路径**
  - `text_detection_model_dir`、`text_recognition_model_dir` 等参数直接填本地模型目录。
  - 或通过 `export_paddlex_config_to_yaml` 导出配置，手动改 `model_dir` 后再加载。

---

## 7. 部署与测试建议

- **快速本地测试**
  - 先用命令行 `paddleocr ocr` / `pp_structurev3` 在几张典型图片上跑一遍；
  - 查看输出图片和 JSON，确认版面块合理，再集成到脚本。
- **离线部署**
  - 对 VL 或大规模服务可优先考虑官方离线 Docker 镜像；
  - 生产环境建议结合 vLLM / SGLang / FastDeploy 等推理框架提升吞吐。
- **与当前项目的三层流程对应关系**
  - 第 1 层（按题号切单题）：`extract_questions_ppstruct.py`  
    - 核心依赖：**PP-StructureV3 + PP-OCRv5**，输出每题截图和 `questions_page_X/meta.json`。
  - 第 2 层（资料分析大题聚合）：`make_data_analysis_big.py`  
    - 继续使用 **PP-StructureV3**，根据「（一）（二）（三）（四）」等标题和自动识别到的资料分析页面范围生成大题截图，并写入 `big_questions`。
  - 第 3 层（大题级语义理解）：`run_chatocr_on_big_questions.py` / `run_vl_on_big_questions.py`  
    - 前者调用 **PP-ChatOCRv4Doc**，基于大模型对大题截图做摘要 / 信息抽取；  
    - 后者调用 **PaddleOCR-VL**，对大题截图做多模态结构化解析，输出 JSON；  
    - 两者都在原有 `meta.json` 基础上追加信息，而不改动现有字段。
- **PP-ChatOCRv4 在本项目中的配置方式**
  - 配置文件路径：项目根目录下的 `chatocr_config.json`，内容形如：
    ```json
    {
      "chat_bot_config": {
        "api_type": "openai",
        "base_url": "https://你的LLM服务地址/v1",
        "api_key": "YOUR_API_KEY",
        "model_name": "你的模型名",
        "module_name": "chat_bot",
        "temperature": 0.2,
        "max_tokens": 1024,
        "top_p": 0.9
      }
    }
    ```
  - 只要你使用的是 **OpenAI 接口风格** 的第三方大模型（如兼容 `/v1/chat/completions`），就可以通过该文件完成接入。

---

## 8. 进一步学习资料

- 官方主页与中文文档：`https://www.paddleocr.ai`
- GitHub 仓库：`https://github.com/PaddlePaddle/PaddleOCR`
- 推荐阅读顺序：
  1. 快速开始 & 安装说明  
  2. 通用 OCR 产线（PP-OCRv5）  
  3. PP-StructureV3 文档结构化教程  
  4. PP-ChatOCRv4 信息抽取示例  
  5. PaddleOCR-VL 使用与部署说明

结合本指南和官方教程，你就可以根据不同任务场景（纯 OCR / 结构化 / 信息抽取 / 多模态理解）选择合适的产线，并在当前“自动切题”项目里逐步引入更强的能力。
