# AI 聊天解析功能 - 核心规格

**版本**: 2.0 | **日期**: 2025-12-17 | **状态**: 全部完成

---

## 一、功能概述

### 已完成功能

| 模块 | 功能 | 说明 |
|------|------|------|
| 试卷管理 | 试卷选择器 | 顶部下拉菜单，支持搜索和切换 |
| 题目导航 | 题目网格 | 左侧5列网格，颜色状态指示，一键跳转 |
| 会话管理 | 会话历史 | 按题目分组，折叠/展开，自动保存 |
| AI答疑 | SSE流式聊天 | Markdown渲染，代码高亮，快捷提问 |
| 错题复习 | 答案录入 | 自动标记正误，进度统计，AI串联 |
| 高级功能 | 搜索/筛选 | 按题号搜索，全部/已聊/收藏/未访问筛选 |
| 高级功能 | 键盘快捷键 | J/K/←/→ 导航题目 |
| 高级功能 | 草稿保存 | 自动保存到localStorage，500ms防抖 |
| 高级功能 | 提示模式 | AI仅提供提示，不给完整答案 |
| 高级功能 | 题目收藏 | 星标标记，跨会话持久化 |

---

## 二、快速开始

### 启动服务

```powershell
# 后端
python -m venv venv && .\venv\Scripts\activate
pip install -r requirements.txt -r web_requirements.txt
python manage.py

# 前端（开发）
cd frontend && npm install && npm run dev

# 前端（生产）
cd frontend && npm run build
```

### AI配置

```bash
AI_PROVIDER=openai_compatible  # 或 mock
AI_BASE_URL=http://localhost:11434/v1
AI_API_KEY=your_key
AI_MODEL=llama3
```

---

## 三、核心API

### 试卷与答案

```bash
GET  /api/exams                              # 试卷列表
GET  /api/exams/{id}                         # 试卷详情（含题目列表）
GET  /api/exams/{id}/questions/{no}/image    # 题目图片
POST /api/exams/{id}/answers:import          # 导入答案（JSON/CSV）
GET  /api/exams/{id}/answers                 # 获取答案
```

### 聊天

```bash
POST /api/chat/sessions                      # 创建会话
GET  /api/chat/sessions?user_id=&exam_id=    # 会话列表
GET  /api/chat/sessions/{id}/messages        # 消息历史
POST /api/chat/sessions/{id}/messages:stream # 发送消息（SSE流式）
```

### 错题

```bash
POST /api/users/{uid}/exams/{eid}/wrong-questions  # 批量标记
GET  /api/users/{uid}/exams/{eid}/wrong-questions  # 错题列表
```

---

## 四、数据库表

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| exams | 试卷 | exam_dir_name, display_name, question_count, has_answers |
| exam_questions | 题目 | exam_id, question_no, image_filename, ocr_text |
| exam_answers | 标准答案 | exam_id, question_no, answer |
| users | 用户 | user_id (前端生成) |
| user_wrong_questions | 错题 | user_id, exam_id, question_no, user_answer, status |
| chat_sessions | 会话 | session_id (UUID), user_id, exam_id, question_no |
| chat_messages | 消息 | session_id, role, content |

---

## 五、前端架构

### 路由

```typescript
/dashboard                    // 试卷列表入口
/exam/:examId/chat?q=N       // AI答疑（三栏布局）
/exam/:examId/review          // 错题复习
```

### 核心组件

```
views/
├── ChatView.vue              # AI答疑主视图（540行）
├── ReviewView.vue            # 错题复习（342行）
└── DashboardView.vue         # 首页

components/chat/
├── ExamSelector.vue          # 试卷选择器（220行）
├── QuestionNavigator.vue     # 题目导航网格（240行）
├── LeftSidebar.vue           # 双标签侧边栏（101行）
├── SessionList.vue           # 会话历史分组（217行）
├── ContextPanel.vue          # 题目上下文（156行）
└── MarkdownRenderer.vue      # Markdown渲染

components/common/
└── ImageViewer.vue           # 图片查看器（140行）
```

### Store

```typescript
// useChatStore - 核心方法
createSession(examId, questionNo)     // 创建会话
sendMessage(content, hintMode)        // 发送消息（SSE）
loadSessions({ examId })              // 加载会话列表
loadQuestionContext(examId, no)       // 加载题目上下文
toggleBookmark(key)                   // 收藏切换
saveDraft(key, content)               // 保存草稿
getQuestionStatus(examId, no)         // 获取题目状态

// useWrongStore - 错题复习
initReview(examId)                    // 初始化复习
setAnswer(examId, no, answer)         // 设置答案（防抖提交）
submitAnswers(examId)                 // 批量提交
```

---

## 六、关键技术方案

### 竞态条件防护

```typescript
let requestId = 0
async function asyncOperation() {
  const myId = ++requestId
  await someAsync()
  if (myId !== requestId) return  // 忽略过期请求
  updateState()
}
```

### 用户数据隔离

```typescript
// localStorage键格式
`chat_bookmarks:${userId}`  // 收藏
`chat_drafts:${userId}`     // 草稿
```

### 提示模式

- 前端传递 `hint_mode: true`
- 后端注入临时系统提示，不污染数据库
- 自动清理历史消息中的旧污染

### SSE错误处理

```typescript
// HTTP错误：response.ok 检查后才设置 requestAccepted
// SSE错误：抛出异常触发catch恢复输入
if (data.type === 'error') throw new Error(data.message)
```

---

## 七、响应式设计

| 断点 | 布局 |
|------|------|
| < md | 单栏，侧边栏抽屉 |
| md | 左侧固定，右侧抽屉 |
| lg | 三栏全显示 |

---

## 八、测试检查清单

**核心功能**
- [ ] 试卷切换更新URL和内容
- [ ] 题目跳转加载上下文和会话
- [ ] 上一题/下一题边界禁用
- [ ] 会话历史分组显示

**高级功能**
- [ ] 键盘J/K/←/→导航，Shift组合不触发
- [ ] 草稿刷新后恢复
- [ ] 发送失败输入框恢复
- [ ] 提示模式刷新后历史干净
- [ ] 多用户书签隔离

---

## 九、文件清单

**后端**
- `backend/src/web/routers/chat.py` - 聊天API
- `backend/src/web/routers/exams.py` - 试卷API
- `backend/src/web/routers/users.py` - 用户/错题API
- `backend/src/services/ai/` - AI Provider抽象

**前端**
- `frontend/src/stores/useChatStore.ts` - 聊天状态（382行）
- `frontend/src/stores/useWrongStore.ts` - 错题状态（203行）
- `frontend/src/views/ChatView.vue` - AI答疑视图（540行）
- `frontend/src/views/ReviewView.vue` - 错题复习（342行）

---

**合并自**: IMPLEMENTATION_SUMMARY.md, AI答疑界面优化方案.md, AI答疑界面测试报告.md, AI_CHAT_FEATURE_SPEC.md, AI 聊天解析功能综合实施指南.md
