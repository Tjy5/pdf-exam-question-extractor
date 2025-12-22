import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useUserStore } from './useUserStore'
import { readSseJson } from '@/services/sse'

export interface WrongItem {
  id: number
  user_id: string
  source_type: 'exam' | 'upload'
  exam_id?: number
  question_no?: number
  original_image?: string
  ai_question_text?: string
  ai_answer_text?: string
  ai_analysis?: string
  subject?: string
  source_name?: string
  error_type?: string
  user_notes?: string
  mastery_level: number
  marked_at: string
  updated_at: string
  tags: Array<{ id: string; name: string; subject: string }>
}

export interface Tag {
  id: string
  name: string
  subject: string
  parent_id?: string
  is_system: number
  children: Tag[]
}

export interface AnalyzeResult {
  question_text?: string
  answer_text?: string
  analysis?: string
  thinking?: string
  subject?: string
  knowledge_points: string[]
  error_type?: string
}

export interface Filters {
  sourceType?: string
  subject?: string
  masteryLevel?: number
  tagId?: string
  search?: string
}

export const useWrongNotebookStore = defineStore('wrongNotebook', () => {
  const userStore = useUserStore()

  // State
  const items = ref<WrongItem[]>([])
  const tags = ref<Tag[]>([])
  const loading = ref(false)
  const analyzing = ref(false)
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const filters = ref<Filters>({})

  // Analysis state
  const analyzeText = ref('')
  const analyzeThinking = ref('')
  const analyzeResult = ref<AnalyzeResult | null>(null)
  const analyzeError = ref<string | null>(null)

  // Actions
  async function loadItems() {
    if (!userStore.userId) return

    loading.value = true
    try {
      const params = new URLSearchParams({
        page: String(page.value),
        page_size: String(pageSize.value)
      })

      if (filters.value.sourceType) params.set('source_type', filters.value.sourceType)
      if (filters.value.subject) params.set('subject', filters.value.subject)
      if (filters.value.masteryLevel !== undefined) params.set('mastery_level', String(filters.value.masteryLevel))
      if (filters.value.tagId) params.set('tag_id', filters.value.tagId)
      if (filters.value.search) params.set('search', filters.value.search)

      const res = await fetch(`/api/wrong-notebook/items?${params}`, {
        headers: { 'X-User-Id': userStore.userId }
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const data = await res.json()
      items.value = data.items
      total.value = data.total
    } catch (err) {
      console.error('Load wrong items error:', err)
    } finally {
      loading.value = false
    }
  }

  async function createItem(item: {
    sourceType: string
    originalImage?: string
    aiQuestionText?: string
    aiAnswerText?: string
    aiAnalysis?: string
    subject?: string
    sourceName?: string
    errorType?: string
    tagIds?: string[]
  }) {
    if (!userStore.userId) throw new Error('User not initialized')

    const res = await fetch('/api/wrong-notebook/items', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': userStore.userId
      },
      body: JSON.stringify({
        source_type: item.sourceType,
        original_image: item.originalImage,
        ai_question_text: item.aiQuestionText,
        ai_answer_text: item.aiAnswerText,
        ai_analysis: item.aiAnalysis,
        subject: item.subject,
        source_name: item.sourceName,
        error_type: item.errorType,
        tag_ids: item.tagIds || []
      })
    })

    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  }

  async function updateItem(itemId: number, updates: {
    masteryLevel?: number
    userNotes?: string
    tagIds?: string[]
    aiQuestionText?: string
    aiAnswerText?: string
    aiAnalysis?: string
  }) {
    const res = await fetch(`/api/wrong-notebook/items/${itemId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': userStore.userId
      },
      body: JSON.stringify({
        mastery_level: updates.masteryLevel,
        user_notes: updates.userNotes,
        tag_ids: updates.tagIds,
        ai_question_text: updates.aiQuestionText,
        ai_answer_text: updates.aiAnswerText,
        ai_analysis: updates.aiAnalysis
      })
    })

    if (!res.ok) throw new Error(`HTTP ${res.status}`)

    // Update local state
    const idx = items.value.findIndex(i => i.id === itemId)
    if (idx >= 0) {
      if (updates.masteryLevel !== undefined) items.value[idx].mastery_level = updates.masteryLevel
      if (updates.userNotes !== undefined) items.value[idx].user_notes = updates.userNotes
    }
  }

  async function deleteItem(itemId: number) {
    const res = await fetch(`/api/wrong-notebook/items/${itemId}`, {
      method: 'DELETE',
      headers: { 'X-User-Id': userStore.userId }
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    items.value = items.value.filter(i => i.id !== itemId)
  }

  async function loadTags(subject?: string) {
    const params = new URLSearchParams()
    if (subject) params.set('subject', subject)
    params.set('include_system', 'true')

    const res = await fetch(`/api/wrong-notebook/tags?${params}`, {
      headers: { 'X-User-Id': userStore.userId }
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    tags.value = await res.json()
  }

  async function createTag(tag: { name: string; subject: string; parentId?: string }) {
    if (!userStore.userId) throw new Error('User not initialized')

    const res = await fetch('/api/wrong-notebook/tags', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': userStore.userId
      },
      body: JSON.stringify({
        name: tag.name,
        subject: tag.subject,
        parent_id: tag.parentId
      })
    })

    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return await res.json()
  }

  async function analyzeImage(
    imageBase64: string,
    mimeType: string = 'image/jpeg',
    subject?: string
  ): Promise<AnalyzeResult> {
    analyzing.value = true
    analyzeText.value = ''
    analyzeThinking.value = ''
    analyzeResult.value = null
    analyzeError.value = null

    return new Promise((resolve, reject) => {
      fetch('/api/wrong-notebook/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: imageBase64,
          mime_type: mimeType,
          subject: subject
        })
      }).then(async response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)

        if (!response.body) throw new Error('No response body')
        let streamEnded = false

        try {
          for await (const data of readSseJson<any>(response.body)) {
            if (data.type === 'token') {
              const content = data.content || ''
              const kind = data.kind || 'content'

              if (kind === 'reasoning') {
                analyzeThinking.value += content
              } else {
                analyzeText.value += content
              }
            } else if (data.type === 'content') {
              // Backward compatibility: legacy format
              analyzeText.value += data.text
            } else if (data.type === 'done') {
              analyzeResult.value = data.result
              analyzing.value = false
              streamEnded = true
              resolve(data.result)
              return
            } else if (data.type === 'error') {
              analyzeError.value = data.message
              analyzing.value = false
              streamEnded = true
              reject(new Error(data.message))
              return
            }
          }

          // Stream ended without done/error event
          if (!streamEnded) {
            const errMsg = 'Stream ended unexpectedly'
            analyzeError.value = errMsg
            analyzing.value = false
            reject(new Error(errMsg))
          }
        }
      }).catch(err => {
        analyzeError.value = err.message
        analyzing.value = false
        reject(err)
      })
    })
  }

  function setFilters(newFilters: Filters) {
    filters.value = { ...filters.value, ...newFilters }
    page.value = 1
    loadItems()
  }

  function clearFilters() {
    filters.value = {}
    page.value = 1
    loadItems()
  }

  function setPage(newPage: number) {
    page.value = newPage
    loadItems()
  }

  // Computed
  const hasMore = computed(() => items.value.length < total.value)
  const isEmpty = computed(() => items.value.length === 0 && !loading.value)

  return {
    // State
    items,
    tags,
    loading,
    analyzing,
    total,
    page,
    pageSize,
    filters,
    analyzeText,
    analyzeThinking,
    analyzeResult,
    analyzeError,
    // Actions
    loadItems,
    createItem,
    updateItem,
    deleteItem,
    loadTags,
    createTag,
    analyzeImage,
    setFilters,
    clearFilters,
    setPage,
    // Computed
    hasMore,
    isEmpty
  }
})
