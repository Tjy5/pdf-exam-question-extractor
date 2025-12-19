<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore, type SessionSummary } from '@/stores/useChatStore'
import { useExamStore } from '@/stores/useExamStore'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import ThinkingBlock from '@/components/chat/ThinkingBlock.vue'
import ExamSelector from '@/components/chat/ExamSelector.vue'
import LeftSidebar from '@/components/chat/LeftSidebar.vue'
import ContextPanel from '@/components/chat/ContextPanel.vue'
import ImageViewer from '@/components/common/ImageViewer.vue'

const props = defineProps<{ examId?: string }>()
const route = useRoute()
const router = useRouter()
const store = useChatStore()
const examStore = useExamStore()

const inputText = ref('')
const messagesContainer = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const initError = ref<string | null>(null)
let initSessionRequestId = 0

// 侧边栏状态（移动端）
const isHistoryOpen = ref(false)
const isContextOpen = ref(false)

// 题目上下文加载降级：允许跳过题目继续聊天
const skipQuestionContext = ref(false)
const questionContextErrorForView = computed(() => skipQuestionContext.value ? null : store.questionContextError)

// ImageViewer状态
const imageViewerOpen = ref(false)
const imageViewerSrc = ref('')

const examId = computed(() => props.examId ? Number(props.examId) : 0)
const questionNo = computed(() => Number(route.query.q) || 1)
const sessionIdFromRoute = computed(() => {
  // 优先使用sid，兼容旧的sessionId参数，并验证类型为string
  const sid = route.query.sid
  const legacySessionId = route.query.sessionId
  const value = sid ?? legacySessionId
  return typeof value === 'string' ? value : undefined
})
const hasValidParams = computed(() => examId.value > 0 && questionNo.value > 0)
const hasUnsavedInput = computed(() => inputText.value.trim().length > 0)
const isBookmarked = computed(() => store.isBookmarked(examId.value, questionNo.value))

// 获取当前试卷信息
const currentExam = computed(() => examStore.exams.find(e => e.id === examId.value))
const totalQuestions = computed(() => currentExam.value?.question_count || 0)

// 初始化时加载试卷列表
onMounted(() => {
  if (examStore.exams.length === 0) {
    examStore.fetchExams()
  }
  initSession()
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})

// 初始化会话
async function initSession() {
  const requestId = ++initSessionRequestId
  initError.value = null

  if (!hasValidParams.value) {
    if (requestId === initSessionRequestId) {
      initError.value = '缺少必要参数，请从试卷列表选择题目进行答疑'
    }
    return
  }

  const initExamId = examId.value
  const initQuestionNo = questionNo.value
  const initSid = sessionIdFromRoute.value

  // 恢复草稿
  const draft = store.getDraft(initExamId, initQuestionNo)
  inputText.value = draft

  try {
    // 1) 优先：URL带sid则直接切换到该会话（同sid则跳过重复加载）
    if (initSid) {
      if (initSid !== store.sessionId) {
        await store.switchSession(initSid)
      }
    } else {
      // 2) URL不带sid：进入“草稿会话”，不在切题时自动创建/复用会话
      store.clearActiveSession()
    }
    if (requestId !== initSessionRequestId) return

    // 确保加载试卷详情(包含题目列表)
    if (!examStore.currentExam || examStore.currentExam.exam.id !== initExamId) {
      const detail = await examStore.fetchExamDetail(initExamId)
      if (requestId !== initSessionRequestId) return
      if (!detail) {
        initError.value = examStore.error?.includes('404')
          ? `试卷不存在或已被删除（ID=${initExamId}），请从试卷列表重新选择`
          : (examStore.error || '获取试卷详情失败')
        return
      }
    }
    if (requestId !== initSessionRequestId) return

    // 加载会话列表
    await store.loadSessions({ examId: initExamId })
    if (requestId !== initSessionRequestId) return

    // 加载题目上下文
    await store.loadQuestionContext(initExamId, initQuestionNo)
  } catch (err: unknown) {
    if (requestId !== initSessionRequestId) return
    initError.value = err instanceof Error ? err.message : '初始化失败'
  }
}

watch([examId, questionNo, sessionIdFromRoute], () => {
  skipQuestionContext.value = false
  if (hasValidParams.value) {
    void initSession()
  }
})

function goToDashboard() {
  router.push('/dashboard')
}

watch(() => store.messages, () => {
  if (autoScroll.value) {
    nextTick(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTo({
          top: messagesContainer.value.scrollHeight,
          behavior: 'smooth'
        })
      }
    })
  }
}, { deep: true })

// 草稿自动保存
watch(inputText, (newVal) => {
  if (hasValidParams.value) {
    store.saveDraft(examId.value, questionNo.value, newVal)
  }
})

function handleScroll() {
  if (!messagesContainer.value) return
  const { scrollTop, scrollHeight, clientHeight } = messagesContainer.value
  autoScroll.value = scrollHeight - scrollTop - clientHeight < 100
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || store.isStreaming) return
  const sendExamId = examId.value
  const sendQuestionNo = questionNo.value
  inputText.value = ''
  store.saveDraft(sendExamId, sendQuestionNo, '')
  try {
    // 草稿会话：首次发送时才创建会话，并写回URL的sid
    if (!store.sessionId) {
      const newSessionId = await store.createSession(sendExamId, sendQuestionNo)
      if (!newSessionId) throw new Error('创建会话失败')

      const cleanQuery = { ...(route.query as any) }
      delete cleanQuery.sid
      delete cleanQuery.sessionId
      await router.replace({
        path: `/exam/${sendExamId}/chat`,
        query: { ...cleanQuery, q: sendQuestionNo, sid: newSessionId }
      })
    }

    await store.sendMessage(text, { questionNo: sendQuestionNo })
    await store.loadSessions({ examId: sendExamId })
  } catch {
    // 发送失败：恢复草稿（并仅在仍停留在同一题时恢复输入框）
    store.saveDraft(sendExamId, sendQuestionNo, text)
    if (examId.value === sendExamId && questionNo.value === sendQuestionNo) {
      inputText.value = text
    }
  }
}

function setQuickQuestion(question: string) {
  inputText.value = question
}

function handleSelectSession(session: SessionSummary) {
  router.push({
    path: `/exam/${session.exam_id}/chat`,
    query: { q: session.question_no, sid: session.session_id }
  })
  isHistoryOpen.value = false
}

async function handleCreateNewSession() {
  if (!hasValidParams.value) return

  try {
    // 进入草稿会话：不立刻创建会话，首次发送消息才创建
    store.clearActiveSession()
    inputText.value = ''
    store.saveDraft(examId.value, questionNo.value, '')

    const cleanQuery = { ...(route.query as any) }
    delete cleanQuery.sid
    delete cleanQuery.sessionId
    await router.push({
      path: `/exam/${examId.value}/chat`,
      query: { ...cleanQuery, q: questionNo.value }
    })
  } finally {
    isHistoryOpen.value = false
  }
}

async function handleDeleteSession(session: SessionSummary) {
  const title = (session.title || '').trim() || (session.message_count > 0 ? `第${session.question_no}题对话` : '新对话')
  const ok = window.confirm(`确定删除「${title}」吗？删除后无法恢复。`)
  if (!ok) return

  try {
    await store.deleteSession(session.session_id)
    await store.loadSessions({ examId: examId.value })

    if (sessionIdFromRoute.value === session.session_id) {
      const cleanQuery = { ...(route.query as any) }
      delete cleanQuery.sid
      delete cleanQuery.sessionId
      await router.replace({
        path: `/exam/${examId.value}/chat`,
        query: { ...cleanQuery, q: questionNo.value }
      })
    }
  } finally {
    isHistoryOpen.value = false
  }
}

async function handleDeleteAllSessions() {
  if (store.sessions.length === 0) return
  const ok = window.confirm('确定删除本试卷的全部对话吗？删除后无法恢复。')
  if (!ok) return

  try {
    await store.deleteAllSessions({ examId: examId.value })
    await store.loadSessions({ examId: examId.value })

    const cleanQuery = { ...(route.query as any) }
    delete cleanQuery.sid
    delete cleanQuery.sessionId
    await router.replace({
      path: `/exam/${examId.value}/chat`,
      query: { ...cleanQuery, q: questionNo.value }
    })
  } finally {
    isHistoryOpen.value = false
  }
}

function handleOpenImage(src: string) {
  imageViewerSrc.value = src
  imageViewerOpen.value = true
}

function handleRetryQuestionContext() {
  skipQuestionContext.value = false
  if (!hasValidParams.value) return
  store.loadQuestionContext(examId.value, questionNo.value)
}

function handleContinueWithoutContext() {
  skipQuestionContext.value = true
  isContextOpen.value = false
}

// 处理题目导航
function handleNavigate(direction: 'prev' | 'next') {
  const targetQ = direction === 'prev'
    ? questionNo.value - 1
    : questionNo.value + 1

  if (targetQ < 1 || targetQ > totalQuestions.value) return

  router.push({
    path: `/exam/${examId.value}/chat`,
    query: { q: targetQ }
  })
}

// 键盘快捷键
function handleKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement
  if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return
  if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return

  if (e.key === 'ArrowRight' || e.key.toLowerCase() === 'j') {
    handleNavigate('next')
  } else if (e.key === 'ArrowLeft' || e.key.toLowerCase() === 'k') {
    handleNavigate('prev')
  }
}

// 收藏功能
function toggleBookmark() {
  store.toggleBookmark(examId.value, questionNo.value)
}
</script>

<template>
  <div class="flex h-screen w-full bg-slate-50 overflow-hidden text-slate-800">
    <!-- 左侧边栏：题目导航 + 会话历史（桌面显示） -->
    <aside class="w-80 flex-none hidden md:flex flex-col">
      <LeftSidebar
        :exam-id="examId"
        :current-question-no="questionNo"
        :total-questions="totalQuestions"
        :sessions="store.sessions"
        :current-session-id="store.currentSessionId"
        :sessions-loading="store.sessionsLoading"
        @select-session="handleSelectSession"
        @create-new-session="handleCreateNewSession"
        @delete-session="handleDeleteSession"
        @delete-all-sessions="handleDeleteAllSessions"
      />
    </aside>

    <!-- 左侧边栏：题目导航 + 会话历史（移动端抽屉） -->
    <Transition
      enter-active-class="transition duration-300 ease-out"
      enter-from-class="-translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="-translate-x-full"
    >
      <aside
        v-if="isHistoryOpen"
        class="fixed inset-y-0 left-0 z-40 w-80 md:hidden"
      >
        <LeftSidebar
          :exam-id="examId"
          :current-question-no="questionNo"
          :total-questions="totalQuestions"
          :sessions="store.sessions"
          :current-session-id="store.currentSessionId"
          :sessions-loading="store.sessionsLoading"
          @select-session="handleSelectSession"
          @create-new-session="handleCreateNewSession"
          @delete-session="handleDeleteSession"
          @delete-all-sessions="handleDeleteAllSessions"
        />
      </aside>
    </Transition>

    <!-- 遮罩层（移动端） -->
    <Transition
      enter-active-class="transition duration-300 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="isHistoryOpen || isContextOpen"
        class="fixed inset-0 bg-black/30 z-30 md:hidden"
        @click="isHistoryOpen = false; isContextOpen = false"
      ></div>
    </Transition>

    <!-- 中间：聊天区域 -->
    <main class="flex-1 flex flex-col min-w-0 relative">
      <!-- 背景装饰 -->
      <div class="absolute top-0 left-0 w-full h-96 bg-gradient-to-b from-blue-50 to-transparent pointer-events-none"></div>

      <!-- 头部 -->
      <header class="flex-none px-4 md:px-6 py-3 bg-white/80 backdrop-blur-md border-b border-slate-100 z-10">
        <div class="flex items-center gap-3 mb-2">
          <button
            @click="isHistoryOpen = !isHistoryOpen"
            class="md:hidden p-2 -ml-2 text-slate-500 hover:text-indigo-600 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          <div class="flex-1 min-w-0">
            <!-- 面包屑导航 -->
            <div class="flex items-center gap-2 text-sm text-slate-600 mb-1">
              <button
                @click="goToDashboard"
                class="hover:text-indigo-600 transition-colors"
              >
                试卷列表
              </button>
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
              <ExamSelector
                :current-exam-id="examId"
                :current-question-no="questionNo"
                :has-unsaved-input="hasUnsavedInput"
              />
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
              <span class="text-slate-700 font-medium">AI答疑</span>
            </div>

            <!-- 题号指示器 -->
            <div class="flex items-center gap-2">
              <h1 class="text-lg md:text-xl font-bold text-slate-800 flex items-center gap-2">
                <!-- 提示模式切换 -->
                <button
                  @click="store.hintMode = !store.hintMode"
                  class="p-1 rounded-full transition-colors border"
                  :class="store.hintMode ? 'bg-indigo-100 border-indigo-300 text-indigo-700' : 'bg-slate-50 border-slate-200 text-slate-400 hover:text-slate-600'"
                  title="提示模式"
                >
                  <span v-if="store.hintMode">💡</span>
                  <span v-else class="grayscale opacity-50">💡</span>
                </button>

                <!-- 收藏按钮 -->
                <button
                  @click="toggleBookmark"
                  class="p-1 rounded-full transition-colors focus:outline-none"
                  :class="isBookmarked ? 'text-yellow-400 hover:text-yellow-500' : 'text-slate-300 hover:text-slate-400'"
                  title="收藏题目"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" :fill="isBookmarked ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                  </svg>
                </button>

                <span class="text-2xl">🤖</span>
                <span class="hidden sm:inline">AI 答疑助手</span>
                <span v-if="store.hintMode" class="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full border border-indigo-200">
                  提示模式
                </span>
              </h1>
              <span v-if="totalQuestions > 0" class="text-sm text-slate-500 font-medium">
                第 {{ questionNo }} 题 / 共 {{ totalQuestions }} 题
              </span>
            </div>
          </div>

          <button
            @click="isContextOpen = !isContextOpen"
            class="lg:hidden p-2 -mr-2 text-slate-500 hover:text-indigo-600 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
        </div>
      </header>

      <!-- 消息区域 -->
      <div
        ref="messagesContainer"
        @scroll="handleScroll"
        class="flex-1 overflow-y-auto px-4 py-6 space-y-6"
      >
        <!-- 初始化错误 -->
        <div v-if="initError" class="flex flex-col items-center justify-center h-full text-center p-8">
          <div class="w-20 h-20 bg-gradient-to-tr from-red-100 to-orange-100 rounded-full flex items-center justify-center mb-6 shadow-sm">
            <span class="text-4xl">⚠️</span>
          </div>
          <h2 class="text-xl font-semibold text-slate-700 mb-2">无法初始化会话</h2>
          <p class="text-slate-500 max-w-md mx-auto mb-6">{{ initError }}</p>
          <button
            @click="goToDashboard"
            class="px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-medium shadow-sm transition-all"
          >
            返回试卷列表
          </button>
        </div>

        <!-- 空状态 -->
        <div v-else-if="store.messages.length === 0" class="flex flex-col items-center justify-center h-full text-center p-8">
          <div class="w-20 h-20 bg-gradient-to-tr from-blue-100 to-indigo-100 rounded-full flex items-center justify-center mb-6 shadow-sm">
            <span class="text-4xl">💭</span>
          </div>
          <h2 class="text-xl font-semibold text-slate-700 mb-2">
            这是「第 {{ questionNo }} 题」的 AI 答疑
          </h2>
          <p class="text-slate-400 max-w-sm mx-auto">
            我可以帮你快速理解题意、梳理解题思路，并补齐相关知识点。
          </p>

          <div class="mt-5 w-full max-w-sm text-left bg-white/70 border border-slate-100 rounded-2xl p-4">
            <div class="text-sm font-medium text-slate-600 mb-3">我可以帮你：</div>
            <ul class="space-y-2 text-sm text-slate-500">
              <li class="flex items-start gap-2">
                <span class="mt-0.5 text-indigo-500">•</span>
                <span>解析题目思路（为什么这么做）</span>
              </li>
              <li class="flex items-start gap-2">
                <span class="mt-0.5 text-indigo-500">•</span>
                <span>讲解相关知识点与考点</span>
              </li>
              <li class="flex items-start gap-2">
                <span class="mt-0.5 text-indigo-500">•</span>
                <span>提供解题技巧与常见坑点</span>
              </li>
            </ul>
          </div>

          <p class="text-slate-400 mt-5">点击下方快捷提问开始</p>
        </div>

        <!-- 消息列表 -->
        <div
          v-else
          v-for="msg in store.messages"
          :key="msg.id"
          class="flex gap-4 max-w-4xl mx-auto w-full"
          :class="msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'"
        >
          <div
            class="flex-none w-10 h-10 rounded-full flex items-center justify-center shadow-sm text-lg"
            :class="msg.role === 'user' ? 'bg-indigo-600 text-white' : 'bg-white border border-slate-100 text-slate-700'"
          >
            {{ msg.role === 'user' ? '👤' : '🤖' }}
          </div>

          <div
            class="flex flex-col max-w-[85%] lg:max-w-[75%]"
            :class="msg.role === 'user' ? 'items-end' : 'items-start'"
          >
            <div
              class="px-5 py-3.5 shadow-sm text-base leading-relaxed break-words"
              :class="[
                msg.role === 'user'
                  ? 'bg-gradient-to-br from-indigo-500 to-indigo-600 text-white rounded-2xl rounded-tr-sm'
                  : 'bg-white border border-slate-100 text-slate-800 rounded-2xl rounded-tl-sm'
              ]"
            >
              <div v-if="msg.role === 'user'" class="whitespace-pre-wrap">{{ msg.content }}</div>
              <div v-else class="markdown-body">
                <!-- 思考过程块 -->
                <ThinkingBlock
                  v-if="msg.thinking"
                  :thinking="msg.thinking"
                  :is-streaming="msg.isStreaming"
                />

                <!-- AI 回复内容 -->
                <MarkdownRenderer :content="msg.content" />

                <!-- 加载指示器 -->
                <div v-if="msg.isStreaming" class="flex items-center gap-1.5 mt-3 text-slate-400">
                  <span class="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce"></span>
                  <span class="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce delay-100"></span>
                  <span class="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce delay-200"></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 错误提示 -->
      <Transition enter-active-class="transition duration-300" enter-from-class="opacity-0" enter-to-class="opacity-100">
        <div v-if="store.error" class="fixed top-20 left-1/2 -translate-x-1/2 bg-rose-50 border border-rose-200 text-rose-600 px-4 py-3 rounded-xl shadow-lg flex items-center gap-2 z-50">
          <span>❌</span>
          <span class="font-medium">{{ store.error }}</span>
        </div>
      </Transition>

      <!-- 输入区域 -->
      <div v-if="!initError" class="flex-none bg-white border-t border-slate-100 p-4 z-10">
        <div class="max-w-4xl mx-auto space-y-3">
          <!-- 快捷提问 -->
          <div class="flex gap-2 overflow-x-auto pb-2 -mx-2 px-2">
            <button
              v-for="q in [
                { label: '💡 为什么选这个？', text: '这道题为什么选这个答案？' },
                { label: '📝 详细解析', text: '请详细解析一下解题思路' },
                { label: '🎯 解题技巧', text: '有什么解题技巧吗？' },
                { label: '⚠️ 常见错误', text: '常见错误有哪些？' }
              ]"
              :key="q.label"
              @click="setQuickQuestion(q.text)"
              class="whitespace-nowrap px-3 py-1.5 bg-slate-50 hover:bg-indigo-50 border border-slate-200 hover:border-indigo-200 text-slate-600 hover:text-indigo-600 rounded-full text-sm transition-all"
              :disabled="store.isStreaming"
            >
              {{ q.label }}
            </button>
          </div>

          <!-- 输入框 -->
          <div class="relative">
            <input
              v-model="inputText"
              type="text"
              placeholder="输入你的问题..."
              class="w-full pl-4 pr-20 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:bg-white focus:ring-2 focus:ring-indigo-100 focus:border-indigo-400 transition-all"
              :disabled="store.isStreaming"
              @keyup.enter="handleSend"
            />
            <button
              class="absolute right-2 top-2 bottom-2 px-4 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white rounded-lg font-medium transition-all"
              :disabled="store.isStreaming || !inputText.trim()"
              @click="handleSend"
            >
              <span v-if="!store.isStreaming">发送</span>
              <span v-else class="flex gap-1">
                <span class="w-1 h-1 bg-white rounded-full animate-bounce"></span>
                <span class="w-1 h-1 bg-white rounded-full animate-bounce delay-100"></span>
                <span class="w-1 h-1 bg-white rounded-full animate-bounce delay-200"></span>
              </span>
            </button>
          </div>
        </div>
      </div>
    </main>

    <!-- 右侧边栏：题目上下文（桌面显示） -->
    <aside class="w-96 flex-none hidden lg:flex flex-col">
      <ContextPanel
        :context="store.questionContext"
        :loading="store.questionContextLoading"
        :error="questionContextErrorForView"
        :skipped="skipQuestionContext"
        :total-questions="totalQuestions"
        @open-image="handleOpenImage"
        @navigate="handleNavigate"
        @retry="handleRetryQuestionContext"
        @continue-without-context="handleContinueWithoutContext"
      />
    </aside>

    <!-- 右侧边栏：题目上下文（移动端抽屉） -->
    <Transition
      enter-active-class="transition duration-300 ease-out"
      enter-from-class="translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="translate-x-full"
    >
      <aside
        v-if="isContextOpen"
        class="fixed inset-y-0 right-0 z-40 w-80 md:w-96 lg:hidden"
      >
        <ContextPanel
          :context="store.questionContext"
          :loading="store.questionContextLoading"
          :error="questionContextErrorForView"
          :skipped="skipQuestionContext"
          :total-questions="totalQuestions"
          @open-image="handleOpenImage"
          @navigate="handleNavigate"
          @retry="handleRetryQuestionContext"
          @continue-without-context="handleContinueWithoutContext"
        />
      </aside>
    </Transition>

    <!-- 图片查看器 -->
    <ImageViewer
      :open="imageViewerOpen"
      :src="imageViewerSrc"
      @close="imageViewerOpen = false"
    />
  </div>
</template>

<style scoped>
.delay-100 {
  animation-delay: 0.1s;
}
.delay-200 {
  animation-delay: 0.2s;
}
</style>
