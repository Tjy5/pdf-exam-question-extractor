import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useUserStore } from './useUserStore'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
  thinking?: string  // 思考过程内容（从 <think> 标签中提取）
}

export interface SessionSummary {
  session_id: string
  exam_id: number
  question_no: number
  title: string | null
  last_message_at: string | null
  message_count: number
}

export interface QuestionContext {
  examId: number
  questionNo: number
  imageUrl: string
  ocrText?: string
  correctAnswer?: string
  userAnswer?: string
}

interface MessageOut {
  id: number
  role: string
  content: string
  created_at: string
}

function parseTimestamp(createdAt: string | null | undefined): number {
  if (!createdAt) return Date.now()
  const t = Date.parse(createdAt)
  return Number.isFinite(t) ? t : Date.now()
}

function normalizeRole(role: string): Message['role'] {
  if (role === 'user' || role === 'assistant' || role === 'system') return role
  return 'assistant'
}

type BookmarkMap = Record<string, true>

function toBookmarkMap(value: unknown): BookmarkMap {
  const map: BookmarkMap = {}
  if (Array.isArray(value)) {
    for (const item of value) {
      if (typeof item === 'string' && item.trim()) map[item] = true
    }
    return map
  }
  if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (v) map[k] = true
    }
  }
  return map
}

function toDraftMap(value: unknown): Record<string, string> {
  const map: Record<string, string> = {}
  if (!value || typeof value !== 'object' || Array.isArray(value)) return map
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    if (typeof v === 'string') map[k] = v
  }
  return map
}

async function readErrorDetail(res: Response): Promise<string | null> {
  try {
    const data = await res.json()
    const detail = (data && typeof data === 'object' && 'detail' in data) ? (data as any).detail : null
    return typeof detail === 'string' && detail.trim() ? detail : null
  } catch {
    return null
  }
}

// 解析思考内容：提取 <think> 标签中的内容
function parseThinkingContent(text: string, trimContent = true): { thinking: string; content: string } {
  if (!text) return { thinking: '', content: '' }

  const thinkingParts: string[] = []
  let mainContent = text

  // 支持多种思考标签格式
  const thinkingPatterns = [
    /<think>([\s\S]*?)<\/think>/gi,
    /<thinking>([\s\S]*?)<\/thinking>/gi,
    /<reason>([\s\S]*?)<\/reason>/gi,
    /<reasoning>([\s\S]*?)<\/reasoning>/gi,
  ]

  for (const pattern of thinkingPatterns) {
    let match: RegExpExecArray | null
    while ((match = pattern.exec(mainContent)) !== null) {
      const thinkContent = match[1].trim()
      if (thinkContent) {
        thinkingParts.push(thinkContent)
      }
      mainContent = mainContent.replace(match[0], '')
      pattern.lastIndex = 0
    }
  }

  return {
    thinking: thinkingParts.join('\n\n'),
    content: trimContent ? mainContent.trim() : mainContent
  }
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)
  const error = ref<string | null>(null)
  const sessionId = ref<string | null>(null)

  // P1: 会话历史
  const sessions = ref<SessionSummary[]>([])
  const sessionsLoading = ref(false)
  const sessionsError = ref<string | null>(null)
  const currentSessionId = ref<string | null>(null)
  const messagesCacheBySessionId = ref<Record<string, Message[]>>({})

  // P2: 题目上下文面板
  const questionContext = ref<QuestionContext | null>(null)
  const questionContextLoading = ref(false)
  const questionContextError = ref<string | null>(null)
  const answersCacheByExamId = ref<Record<number, Record<number, string>>>({})

  // P3: 高级功能
  const drafts = ref<Record<string, string>>({})
  const hintMode = ref(false)
  const bookmarks = ref<BookmarkMap>({})

  // 流取消支持
  const activeStreamAbortController = ref<AbortController | null>(null)

  // 竞态条件防护：请求token
  let loadSessionsRequestId = 0
  let createSessionRequestId = 0
  let switchSessionRequestId = 0
  let loadContextRequestId = 0

  const userStore = useUserStore()

  const titleGenInFlight: Record<string, true> = {}
  const titleGenAttempts: Record<string, number> = {}

  const LEGACY_BOOKMARKS_KEY = 'chat_bookmarks'
  function bookmarksStorageKey(userId: string) {
    return `chat_bookmarks:${userId}`
  }
  function draftsStorageKey(userId: string) {
    return `chat_drafts:${userId}`
  }

  function loadBookmarksFromStorage(userId: string): BookmarkMap {
    if (!userId) return {}
    const userKey = bookmarksStorageKey(userId)
    const rawNew = localStorage.getItem(userKey)

    // 仅读取当前用户的书签，不再回退到 legacy key 防止跨用户泄漏
    if (!rawNew) {
      // 首次登录时检查 legacy key 是否存在
      const rawLegacy = localStorage.getItem(LEGACY_BOOKMARKS_KEY)
      if (rawLegacy) {
        // 将 legacy 数据迁移到用户专属key后删除
        try {
          const parsed = JSON.parse(rawLegacy)
          const map = toBookmarkMap(parsed)
          if (Object.keys(map).length > 0) {
            localStorage.setItem(userKey, JSON.stringify(Object.keys(map)))
          }
          // 删除 legacy key 避免后续用户读取
          localStorage.removeItem(LEGACY_BOOKMARKS_KEY)
          return map
        } catch (e) {
          console.error('Failed to migrate legacy bookmarks', e)
        }
      }
      return {}
    }

    try {
      const parsed = JSON.parse(rawNew)
      return toBookmarkMap(parsed)
    } catch (e) {
      console.error('Failed to load bookmarks', e)
      return {}
    }
  }

  function persistBookmarksToStorage() {
    const userId = userStore.userId
    if (!userId) return
    try {
      localStorage.setItem(bookmarksStorageKey(userId), JSON.stringify(Object.keys(bookmarks.value)))
    } catch (e) {
      console.error('Failed to persist bookmarks', e)
    }
  }

  function loadDraftsFromStorage(userId: string): Record<string, string> {
    if (!userId) return {}
    try {
      const raw = localStorage.getItem(draftsStorageKey(userId))
      if (!raw) return {}
      return toDraftMap(JSON.parse(raw))
    } catch (e) {
      console.error('Failed to load drafts', e)
      return {}
    }
  }

  let draftsPersistTimer: ReturnType<typeof setTimeout> | null = null
  function schedulePersistDrafts() {
    const userId = userStore.userId
    if (!userId) return
    if (draftsPersistTimer) clearTimeout(draftsPersistTimer)
    draftsPersistTimer = setTimeout(() => {
      try {
        localStorage.setItem(draftsStorageKey(userId), JSON.stringify(drafts.value))
      } catch (e) {
        console.error('Failed to persist drafts', e)
      }
    }, 500)
  }

  // 初始化 per-user 本地状态
  bookmarks.value = loadBookmarksFromStorage(userStore.userId)
  drafts.value = loadDraftsFromStorage(userStore.userId)

  watch(() => userStore.userId, (newUserId) => {
    if (draftsPersistTimer) {
      clearTimeout(draftsPersistTimer)
      draftsPersistTimer = null
    }
    bookmarks.value = loadBookmarksFromStorage(newUserId)
    drafts.value = loadDraftsFromStorage(newUserId)
  })

  function abortActiveStream() {
    if (activeStreamAbortController.value) {
      try {
        activeStreamAbortController.value.abort()
      } catch {
        // ignore
      } finally {
        activeStreamAbortController.value = null
      }
    }
    isStreaming.value = false
  }

  async function loadSessions(opts: { examId?: number } = {}) {
    const requestId = ++loadSessionsRequestId
    sessionsLoading.value = true
    sessionsError.value = null

    try {
      const userId = userStore.userId
      if (!userId) {
        if (requestId === loadSessionsRequestId) {
          sessions.value = []
          sessionsError.value = 'No user'
        }
        return []
      }

      const params = new URLSearchParams({ user_id: userId })
      if (typeof opts.examId === 'number' && opts.examId > 0) {
        params.set('exam_id', String(opts.examId))
      }

      const res = await fetch(`/api/chat/sessions?${params.toString()}`)
      if (requestId !== loadSessionsRequestId) return []
      if (!res.ok) {
        const detail = await readErrorDetail(res)
        throw new Error(detail || `加载会话列表失败 (${res.status})`)
      }

      const data = (await res.json()) as SessionSummary[]
      if (requestId === loadSessionsRequestId) {
        const list = Array.isArray(data) ? data : []
        sessions.value = list
        void autoGenerateMissingSessionTitles()
        return sessions.value
      }
      return []
    } catch (err: unknown) {
      if (requestId === loadSessionsRequestId) {
        sessions.value = []
        sessionsError.value = err instanceof Error ? err.message : '加载会话列表失败'
      }
      return []
    } finally {
      if (requestId === loadSessionsRequestId) {
        sessionsLoading.value = false
      }
    }
  }

  function isGenericSessionTitle(title: string | null): boolean {
    const t = (title || '').trim()
    return !t || t === '对话' || t === '新对话'
  }

  async function generateSessionTitle(sessionId: string, opts: { questionNo?: number; force?: boolean } = {}) {
    const userId = userStore.userId
    if (!userId) throw new Error('No user')
    if (!sessionId) throw new Error('Invalid session')

    if (titleGenInFlight[sessionId]) return null
    titleGenInFlight[sessionId] = true

    try {
      const payload: Record<string, unknown> = { user_id: userId, force: Boolean(opts.force) }
      if (typeof opts.questionNo === 'number' && opts.questionNo > 0) {
        payload.question_no = opts.questionNo
      }

      const res = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/title:generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })

      if (!res.ok) {
        const detail = await readErrorDetail(res)
        throw new Error(detail || `生成标题失败 (${res.status})`)
      }

      const data = (await res.json()) as { title?: unknown }
      const title = typeof data?.title === 'string' ? data.title : ''
      if (title) {
        const idx = sessions.value.findIndex(s => s.session_id === sessionId)
        if (idx >= 0) {
          sessions.value[idx] = { ...sessions.value[idx], title }
        }
      }
      return title || null
    } finally {
      delete titleGenInFlight[sessionId]
    }
  }

  async function autoGenerateMissingSessionTitles(limit = 5) {
    const targets = sessions.value.filter(s => s.message_count > 0 && isGenericSessionTitle(s.title)).slice(0, limit)
    for (const s of targets) {
      const sid = s.session_id
      const attempts = titleGenAttempts[sid] ?? 0
      if (attempts >= 2) continue
      titleGenAttempts[sid] = attempts + 1

      try {
        await generateSessionTitle(sid, { questionNo: s.question_no })
      } catch {
        // Ignore title generation failures (noisy networks / missing AI key etc.)
      }
    }
  }

  async function deleteSession(targetSessionId: string) {
    const userId = userStore.userId
    if (!userId) throw new Error('No user')
    if (!targetSessionId) throw new Error('Invalid session')

    if (isStreaming.value && sessionId.value === targetSessionId) {
      abortActiveStream()
    }

    const params = new URLSearchParams({ user_id: userId })
    const res = await fetch(`/api/chat/sessions/${encodeURIComponent(targetSessionId)}?${params.toString()}`, {
      method: 'DELETE'
    })
    if (!res.ok) {
      const detail = await readErrorDetail(res)
      throw new Error(detail || `删除会话失败 (${res.status})`)
    }

    sessions.value = sessions.value.filter(s => s.session_id !== targetSessionId)
    delete messagesCacheBySessionId.value[targetSessionId]

    if (currentSessionId.value === targetSessionId || sessionId.value === targetSessionId) {
      clearActiveSession()
    }
  }

  async function deleteAllSessions(opts: { examId?: number } = {}) {
    const userId = userStore.userId
    if (!userId) throw new Error('No user')

    const params = new URLSearchParams({ user_id: userId })
    const hasExam = typeof opts.examId === 'number' && opts.examId > 0
    if (hasExam) params.set('exam_id', String(opts.examId))

    const res = await fetch(`/api/chat/sessions?${params.toString()}`, {
      method: 'DELETE'
    })
    if (!res.ok) {
      const detail = await readErrorDetail(res)
      throw new Error(detail || `删除会话失败 (${res.status})`)
    }

    const removed = hasExam
      ? sessions.value.filter(s => s.exam_id === opts.examId).map(s => s.session_id)
      : sessions.value.map(s => s.session_id)

    sessions.value = hasExam
      ? sessions.value.filter(s => s.exam_id !== opts.examId)
      : []

    for (const sid of removed) {
      delete messagesCacheBySessionId.value[sid]
    }

    if (sessionId.value && removed.includes(sessionId.value)) {
      clearActiveSession()
    }
  }

  async function switchSession(newSessionId: string) {
    if (!newSessionId) return

    if (isStreaming.value) abortActiveStream()

    // 竞态防护：生成新的请求ID
    const requestId = ++switchSessionRequestId

    const prevSessionId = sessionId.value
    const prevMessages = messages.value.slice()

    sessionId.value = newSessionId
    currentSessionId.value = newSessionId

    const cached = messagesCacheBySessionId.value[newSessionId]
    if (cached && cached.length > 0) {
      messages.value = cached
    } else {
      messages.value = []
    }

    error.value = null

    try {
      const res = await fetch(`/api/chat/sessions/${encodeURIComponent(newSessionId)}/messages`)

      // 检查是否是最新请求
      if (requestId !== switchSessionRequestId) {
        console.log('Stale switchSession response ignored')
        return
      }

      if (!res.ok) {
        const detail = await readErrorDetail(res)
        throw new Error(detail || `加载消息失败 (${res.status})`)
      }

      const data = (await res.json()) as MessageOut[]

      // 再次检查（JSON解析可能耗时）
      if (requestId !== switchSessionRequestId) {
        console.log('Stale switchSession response ignored')
        return
      }

      const mapped: Message[] = (Array.isArray(data) ? data : []).map((m) => ({
        id: `${newSessionId}:${m.id}`,
        role: normalizeRole(m.role),
        content: String(m.content ?? ''),
        timestamp: parseTimestamp(m.created_at)
      }))

      messages.value = mapped
      messagesCacheBySessionId.value[newSessionId] = mapped
    } catch (err: unknown) {
      // 只有当前请求失败才回滚
      if (requestId === switchSessionRequestId) {
        sessionId.value = prevSessionId
        currentSessionId.value = prevSessionId
        messages.value = prevMessages
        error.value = err instanceof Error ? err.message : '切换会话失败'
      }
    }
  }

  function clearActiveSession() {
    if (isStreaming.value) abortActiveStream()
    sessionId.value = null
    currentSessionId.value = null
    messages.value = []
    error.value = null
  }

  async function loadAnswersForExam(examId: number) {
    if (examId <= 0) return
    if (answersCacheByExamId.value[examId]) return

    const res = await fetch(`/api/exams/${examId}/answers`)
    if (!res.ok) {
      const detail = await readErrorDetail(res)
      throw new Error(detail || `加载答案失败 (${res.status})`)
    }

    const data = (await res.json()) as Record<string, string>
    const normalized: Record<number, string> = {}

    if (data && typeof data === 'object') {
      for (const [k, v] of Object.entries(data)) {
        const qNo = Number(k)
        if (!Number.isFinite(qNo) || qNo <= 0) continue
        normalized[qNo] = (typeof v === 'string' && v.trim()) ? v : '未知'
      }
    }

    answersCacheByExamId.value[examId] = normalized
  }

  async function loadQuestionContext(examId: number, questionNo: number) {
    questionContextLoading.value = true
    questionContextError.value = null

    // 竞态防护：生成新的请求ID
    const requestId = ++loadContextRequestId

    try {
      if (examId <= 0 || questionNo <= 0) {
        if (requestId !== loadContextRequestId) return null
        questionContext.value = null
        questionContextError.value = '无效的试卷ID或题号'
        return null
      }

      const imageUrl = `/api/exams/${examId}/questions/${questionNo}/image`

      // 尝试加载答案，但不因答案加载失败而阻止context显示
      let correctAnswer = '未知'
      try {
        await loadAnswersForExam(examId)
        if (requestId !== loadContextRequestId) return null
        correctAnswer = answersCacheByExamId.value[examId]?.[questionNo] || '未知'
      } catch (err: unknown) {
        console.warn('Failed to load answers:', err)
      }

      // 最终检查
      if (requestId !== loadContextRequestId) {
        console.log('Stale loadQuestionContext response ignored')
        return null
      }

      const ctx: QuestionContext = {
        examId,
        questionNo,
        imageUrl,
        correctAnswer
      }

      questionContext.value = ctx
      return ctx
    } catch (err: unknown) {
      if (requestId === loadContextRequestId) {
        questionContext.value = null
        questionContextError.value = err instanceof Error ? err.message : '加载题目上下文失败'
      }
      return null
    } finally {
      if (requestId === loadContextRequestId) {
        questionContextLoading.value = false
      }
    }
  }

  // 创建新会话
  async function createSession(examId: number, questionNo: number) {
    if (isStreaming.value) abortActiveStream()

    const requestId = ++createSessionRequestId
    const res = await fetch('/api/chat/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userStore.userId,
        exam_id: examId,
        question_no: questionNo
      })
    })

    if (requestId !== createSessionRequestId) return null
    if (!res.ok) {
      try {
        const errorData = await res.json()
        throw new Error(errorData.detail || `请求失败 (${res.status})`)
      } catch (parseErr) {
        throw new Error(`创建会话失败 (${res.status})`)
      }
    }

    const data = await res.json()
    if (requestId !== createSessionRequestId) return data?.session_id ?? null
    sessionId.value = data.session_id
    currentSessionId.value = data.session_id
    messages.value = []
    messagesCacheBySessionId.value[data.session_id] = []
    return data.session_id
  }

  // 发送消息并流式接收回复
  async function sendMessage(content: string, opts: { questionNo?: number } = {}) {
    if (!sessionId.value) throw new Error('No active session')
    if (isStreaming.value) throw new Error('Already streaming')

    // 添加用户消息
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
      timestamp: Date.now()
    }
    const startLen = messages.value.length
    messages.value.push(userMsg)

    // 创建 AI 消息占位符
    const aiMsg: Message = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true
    }
    messages.value.push(aiMsg)

    isStreaming.value = true
    error.value = null
    let requestAccepted = false
    let rawAssistantText = ''  // 缓冲完整文本，避免流式 trim 导致空格丢失

    try {
      const controller = new AbortController()
      activeStreamAbortController.value = controller

      const payload: Record<string, unknown> = { content, hint_mode: hintMode.value }
      if (typeof opts.questionNo === 'number' && opts.questionNo > 0) {
        payload.question_no = opts.questionNo
      }

      const response = await fetch(`/api/chat/sessions/${sessionId.value}/messages:stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal
      })

      if (!response.ok) {
        const detail = await readErrorDetail(response)
        throw new Error(detail || `请求失败 (${response.status})`)
      }
      requestAccepted = true
      if (!response.body) throw new Error('No response body')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      let buffer = ''
      let streamEnded = false

      // SSE spec: events are delimited by a blank line; each event may contain multiple "data:" lines.
      while (!streamEnded) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        // Normalize CRLF to LF for simpler parsing
        buffer = buffer.replace(/\r/g, '')

        while (true) {
          const boundaryIndex = buffer.indexOf('\n\n')
          if (boundaryIndex === -1) break

          const rawEvent = buffer.slice(0, boundaryIndex)
          buffer = buffer.slice(boundaryIndex + 2)

          const dataLines = rawEvent.split('\n').filter(l => l.startsWith('data:'))
          if (dataLines.length === 0) continue

          const dataStr = dataLines
            .map(l => l.slice(5).trimStart())
            .join('\n')
            .trim()
          if (!dataStr) continue

          let data: any
          try {
            data = JSON.parse(dataStr)
          } catch (e) {
            console.error('SSE JSON parse error:', e, { dataStr })
            continue
          }

          if (data?.type === 'token') {
            if (typeof data.content === 'string') {
              rawAssistantText += data.content
              // 实时解析思考内容（流式阶段不 trim，避免丢失单词间空格和"抖动"）
              const parsed = parseThinkingContent(rawAssistantText, false)
              aiMsg.thinking = parsed.thinking
              aiMsg.content = parsed.content
            }
            continue
          }
          if (data?.type === 'done') {
            // 流式完成后，最终 trim 一次
            const finalParsed = parseThinkingContent(rawAssistantText, true)
            aiMsg.thinking = finalParsed.thinking.trim()
            aiMsg.content = finalParsed.content.trim()
            aiMsg.isStreaming = false
            streamEnded = true
            break
          }
          if (data?.type === 'error') {
            const msg = (typeof data.message === 'string' && data.message) ? data.message : 'Stream error'
            error.value = msg
            if (!aiMsg.content.trim()) aiMsg.content = `（错误）${msg}`
            aiMsg.isStreaming = false
            streamEnded = true
            break
          }
        }
      }
    } catch (err: any) {
      if (err && (err.name === 'AbortError' || err.code === 20)) {
        // 切换会话中止了流，不显示为错误
      } else {
        if (!requestAccepted) {
          // 请求未被服务端接受：回滚本地追加的消息，避免"幽灵消息"
          messages.value.splice(startLen)
        }
        error.value = err?.message || 'Failed to send message'
        throw err
      }
    } finally {
      isStreaming.value = false
      aiMsg.isStreaming = false
      activeStreamAbortController.value = null

      if (sessionId.value) {
        messagesCacheBySessionId.value[sessionId.value] = messages.value.slice()
      }
    }
  }

  // 按题目分组会话（用于会话历史Tab）
  const sessionsByQuestion = computed(() => {
    const grouped: Record<number, SessionSummary[]> = {}
    for (const session of sessions.value) {
      const qNo = session.question_no
      if (!grouped[qNo]) grouped[qNo] = []
      grouped[qNo].push(session)
    }
    return grouped
  })

  // 获取题目状态的辅助方法
  function getQuestionStatus(examId: number, questionNo: number): 'current' | 'hasSession' | 'unvisited' {
    // 检查是否是当前题目
    if (questionContext.value?.examId === examId && questionContext.value?.questionNo === questionNo) {
      return 'current'
    }

    // 检查是否有会话记录（且有真实消息）
    const hasSession = sessions.value.some(s => s.exam_id === examId && s.question_no === questionNo && s.message_count > 0)
    if (hasSession) {
      return 'hasSession'
    }

    return 'unvisited'
  }

  // P3 高级功能方法
  function toggleBookmark(examId: number, questionNo: number) {
    const key = `${examId}-${questionNo}`
    if (bookmarks.value[key]) {
      delete bookmarks.value[key]
    } else {
      bookmarks.value[key] = true
    }
    persistBookmarksToStorage()
  }

  function isBookmarked(examId: number, questionNo: number): boolean {
    return Boolean(bookmarks.value[`${examId}-${questionNo}`])
  }

  function saveDraft(examId: number, questionNo: number, text: string) {
    const key = `${examId}-${questionNo}`
    if (!text) {
      delete drafts.value[key]
    } else {
      drafts.value[key] = text
    }
    schedulePersistDrafts()
  }

  function getDraft(examId: number, questionNo: number): string {
    return drafts.value[`${examId}-${questionNo}`] || ''
  }

  return {
    messages,
    isStreaming,
    error,
    sessionId,

    // P1: 会话历史
    sessions,
    sessionsLoading,
    sessionsError,
    currentSessionId,
    loadSessions,
    deleteSession,
    deleteAllSessions,
    switchSession,
    messagesCacheBySessionId,
    generateSessionTitle,

    // P2: 题目上下文
    questionContext,
    questionContextLoading,
    questionContextError,
    answersCacheByExamId,
    loadQuestionContext,

    // P3: 优化功能
    sessionsByQuestion,
    getQuestionStatus,

    // P3: 高级功能
    drafts,
    hintMode,
    bookmarks,
    toggleBookmark,
    isBookmarked,
    saveDraft,
    getDraft,

    createSession,
    sendMessage,
    clearActiveSession
  }
})
