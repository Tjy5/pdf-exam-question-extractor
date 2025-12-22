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
  <div class="flex flex-1 overflow-hidden min-h-0">
    <!-- 左侧边栏：题目导航 + 会话历史（桌面显示） -->
    <aside class="w-80 flex-none hidden md:flex flex-col border-r border-slate-200/60 bg-white/70 backdrop-blur-xl z-20 shadow-[1px_0_20px_rgba(0,0,0,0.02)]">
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
      enter-from-class="-translate-x-full opacity-50"
      enter-to-class="translate-x-0 opacity-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="translate-x-0 opacity-100"
      leave-to-class="-translate-x-full opacity-50"
    >
      <aside
        v-if="isHistoryOpen"
        class="fixed inset-y-0 left-0 z-50 w-80 md:hidden bg-white shadow-2xl"
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
      enter-from-class="opacity-0 backdrop-blur-none"
      enter-to-class="opacity-100 backdrop-blur-sm"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="opacity-100 backdrop-blur-sm"
      leave-to-class="opacity-0 backdrop-blur-none"
    >
      <div
        v-if="isHistoryOpen || isContextOpen"
        class="fixed inset-0 bg-slate-900/20 z-60 md:hidden"
        @click="isHistoryOpen = false; isContextOpen = false"
      ></div>
    </Transition>

    <!-- 中间：聊天区域 -->
    <main class="flex-1 flex flex-col min-w-0 relative bg-slate-50/50">
      <!-- 动态背景装饰 -->
      <div class="absolute inset-0 overflow-hidden pointer-events-none">
        <div class="absolute -top-[20%] -left-[10%] w-[50%] h-[50%] rounded-full bg-indigo-100/40 blur-3xl opacity-60 mix-blend-multiply animate-blob"></div>
        <div class="absolute top-[10%] -right-[10%] w-[40%] h-[40%] rounded-full bg-violet-100/40 blur-3xl opacity-60 mix-blend-multiply animate-blob animation-delay-200"></div>
        <div class="absolute -bottom-[20%] left-[20%] w-[60%] h-[60%] rounded-full bg-slate-100/60 blur-3xl opacity-60 mix-blend-multiply animate-blob animation-delay-400"></div>
      </div>

      <!-- 头部 -->
      <header class="flex-none px-4 md:px-6 py-3 bg-white/60 backdrop-blur-md border-b border-white/40 z-30 shadow-sm sticky top-0">
        <div class="flex items-center gap-3">
          <button
            @click="isHistoryOpen = !isHistoryOpen"
            class="md:hidden p-2 -ml-2 text-slate-500 hover:text-indigo-600 transition-colors rounded-lg hover:bg-white/50"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          <div class="flex-1 min-w-0 flex flex-col justify-center">
            <!-- 面包屑导航 -->
            <div class="flex items-center gap-1.5 text-xs text-slate-500 mb-0.5">
              <button
                @click="goToDashboard"
                class="hover:text-indigo-600 transition-colors hover:underline"
              >
                试卷列表
              </button>
              <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
              <ExamSelector
                :current-exam-id="examId"
                :current-question-no="questionNo"
                :has-unsaved-input="hasUnsavedInput"
              />
            </div>

            <!-- 题号指示器 -->
            <div class="flex items-center gap-3">
              <h1 class="text-base md:text-lg font-bold text-slate-800 flex items-center gap-2">
                <span class="text-2xl drop-shadow-sm">🤖</span>
                <span class="tracking-tight">AI 答疑助手</span>
                
                <div class="flex items-center gap-1 ml-2">
                   <!-- 提示模式切换 -->
                  <button
                    @click="store.hintMode = !store.hintMode"
                    class="p-1 rounded-full transition-all border"
                    :class="store.hintMode ? 'bg-amber-100 border-amber-200 text-amber-600 shadow-inner' : 'bg-transparent border-transparent text-slate-400 hover:text-slate-600 hover:bg-slate-100'"
                    title="提示模式"
                  >
                    <span v-if="store.hintMode" class="text-sm px-1.5 font-bold">提示模式 ON</span>
                    <span v-else class="grayscale opacity-50">💡</span>
                  </button>

                  <!-- 收藏按钮 -->
                  <button
                    @click="toggleBookmark"
                    class="p-1 rounded-full transition-all focus:outline-none hover:scale-110 active:scale-95"
                    :class="isBookmarked ? 'text-yellow-400 drop-shadow-sm' : 'text-slate-300 hover:text-slate-400'"
                    title="收藏题目"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" :fill="isBookmarked ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                    </svg>
                  </button>
                </div>
              </h1>
              <span v-if="totalQuestions > 0" class="hidden sm:inline-block px-2 py-0.5 rounded-md bg-slate-100 text-xs font-semibold text-slate-500 border border-slate-200">
                第 {{ questionNo }} / {{ totalQuestions }} 题
              </span>
            </div>
          </div>

          <button
            @click="isContextOpen = !isContextOpen"
            class="lg:hidden p-2 -mr-2 text-slate-500 hover:text-indigo-600 transition-colors rounded-lg hover:bg-white/50"
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
        class="flex-1 overflow-y-auto px-4 md:px-8 py-6 space-y-8 scroll-smooth"
      >
        <!-- 初始化错误 -->
        <div v-if="initError" class="flex flex-col items-center justify-center h-full text-center p-8 animate-fade-in-up">
          <div class="w-24 h-24 bg-gradient-to-tr from-rose-100 to-orange-100 rounded-3xl flex items-center justify-center mb-6 shadow-lg shadow-rose-100/50">
            <span class="text-5xl">⚠️</span>
          </div>
          <h2 class="text-2xl font-bold text-slate-800 mb-3">无法初始化会话</h2>
          <p class="text-slate-500 max-w-md mx-auto mb-8 font-medium leading-relaxed">{{ initError }}</p>
          <button
            @click="goToDashboard"
            class="px-8 py-3.5 bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white rounded-xl font-bold shadow-lg shadow-indigo-200 hover:shadow-indigo-300 hover:-translate-y-0.5 transition-all"
          >
            返回试卷列表
          </button>
        </div>

        <!-- 空状态 -->
        <div v-else-if="store.messages.length === 0" class="flex flex-col items-center justify-center h-full text-center p-8 animate-fade-in-up">
          <div class="relative w-24 h-24 mb-8">
             <div class="absolute inset-0 bg-indigo-200 rounded-full blur-xl opacity-50 animate-pulse"></div>
            <div class="relative w-full h-full bg-gradient-to-tr from-violet-100 to-indigo-100 rounded-3xl flex items-center justify-center shadow-xl shadow-indigo-100/50 transform rotate-3 transition-transform hover:rotate-0 duration-500">
              <span class="text-5xl drop-shadow-sm">💭</span>
            </div>
          </div>
          
          <h2 class="text-2xl font-extrabold text-slate-800 mb-3 tracking-tight">
            第 {{ questionNo }} 题 AI 答疑助手
          </h2>
          <p class="text-slate-500 max-w-md mx-auto mb-10 text-lg leading-relaxed">
            我可以帮你快速理解题意、梳理解题思路，并补齐相关知识点。
          </p>

          <div class="w-full max-w-md bg-white/60 backdrop-blur-sm border border-white/60 rounded-2xl p-6 shadow-sm ring-1 ring-slate-900/5">
            <div class="text-sm font-bold text-slate-700 mb-4 uppercase tracking-wider flex items-center gap-2">
              <div class="w-1.5 h-1.5 rounded-full bg-indigo-500"></div>
               我可以做些什么
            </div>
            <ul class="space-y-3">
              <li class="flex items-start gap-3 p-2 rounded-lg hover:bg-indigo-50/50 transition-colors cursor-default group">
                <span class="mt-0.5 flex-none w-6 h-6 rounded-full bg-indigo-100 text-indigo-600 flex items-center justify-center text-xs font-bold group-hover:bg-indigo-600 group-hover:text-white transition-colors">1</span>
                <span class="text-slate-600 group-hover:text-slate-800 transition-colors">解析题目思路与解题逻辑</span>
              </li>
              <li class="flex items-start gap-3 p-2 rounded-lg hover:bg-indigo-50/50 transition-colors cursor-default group">
                <span class="mt-0.5 flex-none w-6 h-6 rounded-full bg-violet-100 text-violet-600 flex items-center justify-center text-xs font-bold group-hover:bg-violet-600 group-hover:text-white transition-colors">2</span>
                <span class="text-slate-600 group-hover:text-slate-800 transition-colors">讲解相关知识点与考点</span>
              </li>
              <li class="flex items-start gap-3 p-2 rounded-lg hover:bg-indigo-50/50 transition-colors cursor-default group">
                 <span class="mt-0.5 flex-none w-6 h-6 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center text-xs font-bold group-hover:bg-teal-600 group-hover:text-white transition-colors">3</span>
                <span class="text-slate-600 group-hover:text-slate-800 transition-colors">提供解题技巧与避坑指南</span>
              </li>
            </ul>
          </div>
        </div>

        <!-- 消息列表 -->
        <div
          v-else
          v-for="msg in store.messages"
          :key="msg.id"
          class="flex gap-4 md:gap-6 max-w-5xl mx-auto w-full group"
          :class="msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'"
        >
          <!-- 头像 -->
          <div
            class="flex-none w-10 h-10 md:w-12 md:h-12 rounded-full flex items-center justify-center shadow-md text-xl md:text-2xl ring-2 ring-white"
            :class="msg.role === 'user' ? 'bg-indigo-600 text-white' : 'bg-white text-slate-700'"
          >
            {{ msg.role === 'user' ? '👤' : '🤖' }}
          </div>

          <!-- 消息体 -->
          <div
            class="flex flex-col max-w-[85%] lg:max-w-[75%]"
            :class="msg.role === 'user' ? 'items-end' : 'items-start'"
          >
            <div
              class="px-5 py-4 md:px-6 md:py-5 shadow-sm text-base leading-relaxed break-words relative overflow-hidden"
              :class="[
                msg.role === 'user'
                  ? 'bg-gradient-to-br from-indigo-500 to-indigo-600 text-white rounded-2xl rounded-tr-sm shadow-indigo-200'
                  : 'bg-white/80 backdrop-blur-sm border border-white/60 text-slate-800 rounded-2xl rounded-tl-sm shadow-slate-200/50'
              ]"
            >
              <!-- 用户消息 -->
              <div v-if="msg.role === 'user'" class="whitespace-pre-wrap font-medium tracking-wide">{{ msg.content }}</div>
              
              <!-- AI 消息 -->
              <div v-else class="markdown-body">
               <!-- 思考过程块 -->
                <!-- 等待原生思考内容：先显示“AI 正在响应中...” -->
                <div
                  v-if="msg.role === 'assistant' && msg.thinkingEnabled && msg.isStreaming && (!msg.thinking || msg.thinking.trim().length === 0) && (!msg.content || msg.content.trim().length === 0)"
                  class="flex items-center gap-1.5 mb-3 text-slate-400 text-sm"
                >
                  <span class="w-2 h-2 bg-indigo-400 rounded-full animate-bounce"></span>
                  <span class="w-2 h-2 bg-indigo-400 rounded-full animate-bounce delay-100"></span>
                  <span class="w-2 h-2 bg-indigo-400 rounded-full animate-bounce delay-200"></span>
                  <span class="ml-1">AI 正在响应中...</span>
                </div>

                <ThinkingBlock
                  v-if="msg.role === 'assistant' && msg.thinkingEnabled && msg.thinking && msg.thinking.trim().length > 0"
                  :thinking="msg.thinking || ''"
                  :is-streaming="msg.isStreaming"
                  :default-expanded="msg.thinkingDefaultExpanded"
                  :collapse-at="msg.thinkingCollapseAt"
                  :duration-ms="msg.thinkingDurationMs"
                />

                <!-- AI 回复内容 -->
                <MarkdownRenderer :content="msg.content" />

                <!-- 加载指示器 -->
                <div
                  v-if="msg.isStreaming && !(msg.thinkingEnabled && (!msg.thinking || msg.thinking.trim().length === 0) && (!msg.content || msg.content.trim().length === 0))"
                  class="flex items-center gap-1.5 mt-4 text-slate-400"
                >
                  <span class="w-2 h-2 bg-indigo-400 rounded-full animate-bounce"></span>
                  <span class="w-2 h-2 bg-indigo-400 rounded-full animate-bounce delay-100"></span>
                  <span class="w-2 h-2 bg-indigo-400 rounded-full animate-bounce delay-200"></span>
                </div>
              </div>
            </div>
            
            <!-- 消息时间/状态 (可扩展) -->
            <!-- <span class="text-xs text-slate-300 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {{ msg.role === 'user' ? 'You' : 'AI' }}
            </span> -->
          </div>
        </div>
      </div>

      <!-- 错误提示 -->
      <Transition enter-active-class="transition duration-300 cubic-bezier(0.16, 1, 0.3, 1)" enter-from-class="opacity-0 translate-y-[-20px]" enter-to-class="opacity-100 translate-y-0">
        <div v-if="store.error" class="fixed top-24 left-1/2 -translate-x-1/2 bg-white/90 backdrop-blur-md border border-rose-100 text-rose-600 px-6 py-4 rounded-2xl shadow-xl shadow-rose-100/40 flex items-center gap-3 z-50 max-w-md text-sm md:text-base cursor-pointer hover:bg-rose-50 transition-colors" @click="store.error = null">
          <div class="bg-rose-100 p-1.5 rounded-full">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
            </svg>
          </div>
          <span class="font-medium">{{ store.error }}</span>
        </div>
      </Transition>

      <!-- 输入区域 -->
      <div v-if="!initError" class="flex-none p-4 pb-6 z-20">
        <div class="max-w-4xl mx-auto space-y-4">
          <!-- 快捷提问 -->
          <Transition
            enter-active-class="transition duration-300 ease-out"
            enter-from-class="opacity-0 transform translate-y-4"
            enter-to-class="opacity-100 transform translate-y-0"
          >
            <div v-if="store.messages.length > 0 || !inputText" class="flex gap-2 overflow-x-auto pb-1 -mx-4 px-4 md:mx-0 md:px-0 scrollbar-hide">
              <button
                v-for="q in [
                  { label: '💡 为什么选这个？', text: '这道题为什么选这个答案？' },
                  { label: '📝 详细解析', text: '请详细解析一下解题思路' },
                  { label: '🎯 解题技巧', text: '有什么解题技巧吗？' },
                  { label: '⚠️ 常见错误', text: '常见错误有哪些？' }
                ]"
                :key="q.label"
                @click="setQuickQuestion(q.text)"
                class="whitespace-nowrap px-4 py-2 bg-white/70 hover:bg-white border border-slate-200/60 hover:border-indigo-200 text-slate-600 hover:text-indigo-600 rounded-full text-sm font-medium shadow-sm hover:shadow-md transition-all active:scale-95 backdrop-blur-sm"
                :disabled="store.isStreaming"
              >
                {{ q.label }}
              </button>
            </div>
          </Transition>

          <!-- 输入框容器 -->
          <div class="relative bg-white rounded-2xl shadow-xl shadow-indigo-100/50 ring-1 ring-slate-900/5 group transition-shadow focus-within:shadow-2xl focus-within:shadow-indigo-200/50 focus-within:ring-indigo-500/30">
            <input
              v-model="inputText"
              type="text"
              placeholder="输入你的问题，Enter 发送..."
              class="w-full pl-6 pr-24 py-4 bg-transparent border-none focus:ring-0 text-slate-800 placeholder:text-slate-400 text-base"
              :disabled="store.isStreaming"
              @keyup.enter="handleSend"
            />
            <button
              class="absolute right-2 top-2 bottom-2 px-6 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-100 disabled:text-slate-300 text-white rounded-xl font-bold transition-all flex items-center justify-center min-w-[5rem]"
              :disabled="store.isStreaming || !inputText.trim()"
              @click="handleSend"
            >
              <span v-if="!store.isStreaming">发送</span>
              <span v-else class="flex gap-1.5">
                <span class="w-1.5 h-1.5 bg-current rounded-full animate-bounce"></span>
                <span class="w-1.5 h-1.5 bg-current rounded-full animate-bounce delay-100"></span>
                <span class="w-1.5 h-1.5 bg-current rounded-full animate-bounce delay-200"></span>
              </span>
            </button>
          </div>
          <div class="text-center text-xs text-slate-300">
             AI 内容仅供参考，请以标准教材为准
          </div>
        </div>
      </div>
    </main>

    <!-- 右侧边栏：题目上下文（桌面显示） -->
    <aside class="w-96 flex-none hidden lg:flex flex-col border-l border-slate-200/60 bg-white/70 backdrop-blur-xl z-20 shadow-[-1px_0_20px_rgba(0,0,0,0.02)]">
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
      enter-from-class="translate-x-full opacity-50"
      enter-to-class="translate-x-0 opacity-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="translate-x-0 opacity-100"
      leave-to-class="translate-x-full opacity-50"
    >
      <aside
        v-if="isContextOpen"
        class="fixed inset-y-0 right-0 z-50 w-80 md:w-96 lg:hidden bg-white shadow-2xl"
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
.scrollbar-hide::-webkit-scrollbar {
    display: none;
}
.scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
}
</style>
