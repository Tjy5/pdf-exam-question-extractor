# 项目说明 & 给后续 AI 的提示

这个目录里存放的是：**把 PDF 试卷页面自动切分成单题图片，并保留题目文字 / 表格结构** 的脚本和示例数据。目前主要针对 `pdf_images/page_*.png` 里的行测试卷截图。

下面说明当前状态、文件结构，以及后续人类或新的 AI 需要注意的约定。

---

## 目标与现状

### 总体目标

- 对一张试卷页面（PNG）：
  - 自动识别页面布局和文字；
  - 按题号将页面划分成一题一块；
  - 输出：每道题的截图 + 对应的文字和表格结构（方便出题、批改或下游 NLP）。
- 需要支持 **很多页、不止一套卷子**，而不仅仅是当前的第 6 页。

### 当前已经完成的内容

1. 使用 **PaddleOCR 3.x + PP-StructureV3** 做版面解析和文字识别。
2. 实现了一个脚本 `extract_questions_ppstruct.py`：
   - 自动扫描 `pdf_images/page_*.png`；
   - 调用 `PPStructureV3` 得到布局块（文字块 / 表格块等）；
   - 在文字块中用正则匹配题号（形如 `31.`、`32．`、`33、` 等）；
   - 把“某个题号块到下一个题号块之前”的所有布局块聚合成一道题；
   - 根据这些块的坐标计算裁剪范围，并裁出题目图片；
   - 保存每页的结构化信息到 JSON。
3. 对 `pdf_images/page_6.png` 的 **31～39 题** 做了人工精调裁剪，放在单独的目录里，作为“黄金标准”。

> **重要约定：`pdf_images/questions_page6` 目录下的 31～39 题图片已经人工确认“完美”，后续任何脚本和 AI 都不要再改动这个目录里的内容。**

---

## 目录结构约定

当前仓库关键结构（只列出和本任务相关的部分）：

- `PaddleOCR完整使用指南.md`
  - 最新的 **PaddleOCR 3.x 使用指南**（更新到 2025-12-05），涵盖安装、`PaddleOCR` / `PPStructureV3` / `PaddleOCR-VL` 的命令行与 Python 用法、离线部署提示等。
- `extract_questions_ppstruct.py`
  - 主脚本：使用 PP-StructureV3 对 `pdf_images/page_*.png` 自动按题号切题，并输出结构化 JSON。
  - 调用方式：
    - 不带参数：处理所有 `page_*.png`
      ```bash
      python extract_questions_ppstruct.py
      ```
    - 带参数：只处理指定页面（推荐）
      ```bash
      python extract_questions_ppstruct.py 6 7      # 只处理 page_6.png 和 page_7.png
      python extract_questions_ppstruct.py page_6.png page_13.png
      ```
- `make_data_analysis_big.py`
  - 辅助脚本：针对**资料分析**大题，生成“大题级截图”和结构化分组信息。
  - 不再写死题号范围（如 71～75、76～80），而是基于：
    - 资料分析所在页面范围：默认**自动识别**（扫描所有 `page_*.png`，找到包含“资料分析”标题的页面作为起点，一直到试卷末尾）；如需强制指定，可在脚本顶部设置 `DATA_ANALYSIS_PAGES`；
    - PP-StructureV3 识别到的「（一）（二）（三）（四）」等大题标题；
    - 小题顺序（每道大题默认 5 个小题，可通过 `DATA_ANALYSIS_GROUP_SIZE` 调整）。
  - 对当前试卷会自动得到 4 道资料分析大题：
    - `data_analysis_1`：只在 `page_13`，输出 `questions_page_13/big_1.png`；
    - `data_analysis_2`：跨 `page_13` & `page_14`，输出 `big_2_part1.png`、`big_2_part2.png`；
    - `data_analysis_3`：跨 `page_14` & `page_15`，输出 `big_3_part1.png`、`big_3_part2.png`；
    - `data_analysis_4`：跨 `page_15`、`page_16`，如有需要还可延伸到 `page_17`（例如材料继续出现在下一页），输出 `big_4_part1.png`、`big_4_part2.png`、`big_4_part3.png` 等。
  - 对应的大题结构分别写在每道大题**首个出现页面**的 `meta.json` 的 `big_questions` 字段中，例如：
    - 第 1、2 道大题记录在 `questions_page_13/meta.json`；
    - 第 3 道大题记录在 `questions_page_14/meta.json`；
    - 第 4 道大题记录在 `questions_page_15/meta.json`。
  - 使用方式（推荐先对整套或至少后几页跑一遍结构化脚本）：
    ```bash
    python extract_questions_ppstruct.py           # 先生成 questions_page_X/meta.json
    python make_data_analysis_big.py               # 自动识别资料分析页并生成 big_*.png
    ```
- `run_chatocr_on_big_questions.py` / `run_vl_on_big_questions.py`
  - 第三层：在大题截图的基础上，接入 **PP-ChatOCRv4** 和 **PaddleOCR-VL** 做语义理解 / 信息抽取。
  - 典型用法：
    - 配置好 `chatocr_config.json` 后，运行 ChatOCR：
      ```bash
      python run_chatocr_on_big_questions.py
      ```
      会对每个 `big_questions[*].segments[*].image` 生成摘要信息，写回对应 `meta.json` 的 `chatocr_chat_res` 字段。
      - 配置文件位置：项目根目录下的 `chatocr_config.json`，结构大致为：
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
        只要是 **OpenAI 接口格式** 的第三方大模型（如兼容 `/v1/chat/completions`），都可以在这里配置。
    - 安装好 `paddleocr[doc-parser]` 后，运行 VL：
      ```bash
      python run_vl_on_big_questions.py
      ```
      会对每个大题截图调用 `PaddleOCRVL`，把结果保存为 JSON 文件，并在 `meta.json` 中记录 `vl_json_path`。
- `pdf_images/`
  - `page_6.png` 等：从 PDF 导出的整页图片。
  - `questions_page6/`
    - **手工裁好的第 6 页题目图**，目前只关心 31～39 题。
    - 这是人工标注的“金标准”，请不要覆盖或重裁这里的图片。
  - `questions_page_6/`、`questions_page_7/` 等（下划线版）
    - 由 `extract_questions_ppstruct.py` 自动生成的 **按页划分的题目图片 + 元数据**。
    - 示例：`pdf_images/questions_page_6/q35.png`、`meta.json`。
  - `exam_questions.json`
    - 脚本汇总所有页面 `meta.json` 生成的一个总览文件（如果存在的话）。

> 注意：`questions_page6`（无下划线）是人工结果；`questions_page_6`（有下划线）是脚本输出，两者不要混淆。

---

## `extract_questions_ppstruct.py` 的核心逻辑

这是未来扩展的核心脚本。主要由以下步骤组成（仅说明思路，具体实现逻辑请看脚本内函数）：

1. **加载 PP-StructureV3**

```python
from paddleocr import PPStructureV3

pipeline = PPStructureV3(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
)
```

2. **版面块抽取**

```python
doc = pipeline.predict("pdf_images/page_6.png")[0]
parsing_res_list = doc["parsing_res_list"]  # List[LayoutBlock]

blocks = [
    {
        "index": blk.index,
        "label": blk.label,              # "text" / "table" / "footer" ...
        "bbox": blk.bbox,                # [x1, y1, x2, y2]
        "content": blk.content,          # str 或 HTML
        "region_label": blk.region_label # 细分类型，可选
    }
    for blk in parsing_res_list
]
```

3. **按题号分段**

- 用正则 `^\s*(\d{1,3})[\.．、]\s*` 在 `label == "text"` 的块中匹配题号；
- 把这些题号块在列表中的索引记为 `head[i].start`，题号值为 `head[i].qno`；
- 每道题的块范围为：`start = head[i].start`，`end = head[i+1].start`（最后一道题的 `end = len(blocks)`）。

4. **为每道题计算裁剪框**

- 对属于本题的所有块，收集其 `bbox` 的 x/y 坐标；
- 在垂直方向上取这些块的最小 y / 最大 y，再加一个安全 `margin`；
- 横向裁剪通常使用页面全宽 `[0, top, page_width, bottom]`，避免漏字；
- 同时记录一个紧凑版的 `crop_box_blocks = [min_x, min_y, max_x, max_y]` 以备后续使用。

5. **输出结果**

对每一页：

- 创建 `pdf_images/questions_page_X/` 目录；
- 保存本页每一道题：
  - `q{题号}.png`：按裁剪框截出的题目图；
  - `meta.json`：包括
    - `qno`、`image` 路径、两种 crop box；
    - 所有 `text_blocks`（bbox + 文本内容）；
    - 所有 `table_blocks`（bbox + HTML 表格）。
- 整体上，`exam_questions.json` 是所有页面 `meta.json` 的汇总。

此外，当运行 `make_data_analysis_big.py` 时，会在相关页的 `meta.json` 中增加一个可选的：

- `big_questions`: `List[BigQuestion]`
  - 目前用于“资料分析”这种**一份材料 + 多个小问**的大题。
  - 结构大致如下（以第 2 道资料分析大题为例）：
    ```json
    "big_questions": [
      {
        "id": "data_analysis_2",
        "type": "data_analysis",
        "pages": ["page_13", "page_14"],
        "qnos": [76, 77, 78, 79, 80],
        "segments": [
          {
            "page": "page_13",
            "image": "pdf_images/questions_page_13/big_2_part1.png",
            "box": [0, 598, 595, 791]
          },
          {
            "page": "page_14",
            "image": "pdf_images/questions_page_14/big_2_part2.png",
            "box": [0, 85, 595, 597]
          }
        ]
      }
    ]
    ```
  - 未来如果要生成“一整张超长大图”，可以直接使用 `segments` 中的 `image` + `box` 信息进行拼接。

---

## 重要约定（给未来人类和 AI）

1. **不要再改动 `pdf_images/questions_page6` 下的文件**
   - 这里的 31～39 题是当前用户人工检查、微调后的“完美版本”。
   - 任何新脚本、新 AI 如需改进算法，请在新的目录（如 `questions_page_6`）里输出结果进行对比，不要覆盖。

2. **如需调整裁剪策略，请优先修改脚本逻辑而不是直接覆盖图片**
   - 例如：
     - 调整题号识别正则（有些试卷题号格式不同）；
     - 增大/减小裁剪 margin；
     - 对双栏排版或跨页题做特殊处理。
   - 做完调整后，可以重新跑 `extract_questions_ppstruct.py`，观察 `questions_page_X` 目录中的变化。

3. **PP-StructureV3 / PaddleOCR 版本**
   - 当前环境基于 PaddleOCR 3.x，接口使用的是新的 `predict` 风格 API；
   - 如果将来升级 PaddleOCR 或 PaddlePaddle，请优先参考 `PaddleOCR完整使用指南.md` 中的最新说明；
   - 版本变更时要注意：
     - `PPStructureV3` 的输出结构是否有字段变化；
     - `parsing_res_list` / `LayoutBlock` 的字段和 `to_dict()` 行为是否一致。

4. **后续可能的扩展方向**

- 在 `meta.json` 的基础上：
  - 把 `text_blocks` 自动拆成「题干 + 选项 A/B/C/D」；
  - 对表格题（如第 35 题）使用 `table_blocks.html` 重建成结构化表格；
  - 做题目去重、难度分析、知识点标注等。
- 对更复杂的文档（双栏、多种题型混排）：
  - 可以引入 PaddleOCR-VL 等视觉语言模型做更高层的语义划分；
  - 但仍建议保留“版面块 + 题号规则”这一层逻辑，以便可控和可解释。

---

## 资料分析大题的特殊说明

- 当前对 **第 13～16 页的资料分析部分** 做了“大题级别”的额外裁剪，逻辑都集中在 `make_data_analysis_big.py` 里：
  - 自动识别这些页面中的「（一）（二）（三）（四）」等大题标题；
  - 假定每道资料分析大题包含 5 个小题（可在脚本顶部 `DATA_ANALYSIS_GROUP_SIZE` 调整）；
  - 按标题 + 版面块顺序，将小题聚合成若干大题，并为每道大题生成 1～2 张跨页截图。
- 这些大题截图 **不会替代单题截图**：
  - 例如本卷中，`q71`～`q90` 仍然按普通题目方式单独裁剪并记录在各页的 `questions` 列表里；
  - 大题信息额外写在 `big_questions` 字段中，作为“材料 + 多个小问”的结构化描述。
- 对于跨页大题，目前的约定是：
  - 先分别保留每一页的片段（`segments` 列表）；
  - 将来如果要生成“一张超长大图”，可以另写脚本遍历 `big_questions[*].segments`，把这些片段拼接起来。
- 如果之后的试卷里还有新的资料分析大题（尤其是跨页的），一般只需要：
  - 把新试卷页面导出为 `pdf_images/page_*.png` 并跑一遍 `extract_questions_ppstruct.py`；
  - 根据新试卷的资料分析所在页，调整 `make_data_analysis_big.py` 顶部的 `DATA_ANALYSIS_PAGES`（一般不需要再写死题号范围）。

---

## 长图拼接（未来方案草案）

目前 **尚未实现代码**，这里只是预留一个设计思路，方便之后的人或 AI 来补全：

- 新脚本建议命名为：`compose_big_questions_long_image.py`（示例名，自由调整）。
- 基本流程：
  1. 遍历 `pdf_images/questions_page_*/meta.json`；
  2. 找到其中的 `big_questions` 列表；
  3. 对每个 big question 的 `segments`：
     - 读取 `segment["image"]` 指向的图片（通常已经是按页裁剪好的片段）；
     - 根据需要的拼接顺序（目前默认按 `segments` 列表顺序）将多张图 **竖直拼接** 成一张长图；
     - 将拼接后的结果存到一个约定路径，例如：
       - `pdf_images/questions_page_13/data_analysis_2_long.png`
  4. 在对应的 `big_questions` 条目中增加一个字段，例如：
     ```json
     {
       "id": "data_analysis_2",
       "type": "data_analysis",
       "pages": ["page_13", "page_14"],
       "qnos": [76, 77, 78, 79, 80],
       "segments": [ ... ],
       "combined_image": "pdf_images/questions_page_13/data_analysis_2_long.png"
     }
     ```
- 约定：
  - 不改动已有的 `segments` 内容，只是**新增** `combined_image` 字段；
  - 如无特殊需求，可以让“整图的逻辑归属”仍然挂在第一页（例如 `page_13`）对应的 `meta.json` 中；
  - 单题截图和原始 `big_*.png` 依旧保留，以便对照或做更细粒度处理。

实现这个脚本时，可以直接使用 Pillow (`PIL.Image`) 做简单的竖直拼接即可，无需重新跑 OCR 或结构化模型。

---

## 如何继续工作

给后续的人类或 AI 的简单 checklist：

1. **想跑一遍现有页面？**
   - 确认已经安装 PaddlePaddle + PaddleOCR（参考 `介绍.md`）。
   - 在仓库根目录执行：
     ```bash
     python extract_questions_ppstruct.py  # 或者 python extract_questions_ppstruct.py 6 7 13 14
     ```
   - 查看 `pdf_images/questions_page_X/` 及 `exam_questions.json`。

2. **要扩展到新试卷？**
   - 把新试卷的每一页导出为 `pdf_images/page_*.png`（命名尽量统一）。
   - 再跑一遍脚本即可得到新的 `questions_page_X` 和 JSON。

3. **要改进算法？**
   - 修改 `extract_questions_ppstruct.py` 中的：
     - 题号正则 `QUESTION_HEAD_PATTERN`；
     - 题目块分段逻辑 `find_question_spans`；
     - 裁剪策略和 margin。
   - 如果要调整资料分析大题（尤其是跨页大题）的截图方式，先看 `make_data_analysis_big.py` 里对 `big_questions` 的处理，再决定是改坐标、改命名，还是新增“整合长图”的生成步骤。
   - 注意保留对 `questions_page6` 的保护约定。

做到这些，新的开发者或 AI 就可以在现有基础上**无缝接力**，继续提高切题效果和结构化质量。  
