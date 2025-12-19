<script setup lang="ts">
import { computed } from 'vue'
import type { SessionSummary } from '@/stores/useChatStore'

const props = defineProps<{
  sessions: SessionSummary[]
  currentSessionId: string | null
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'select', session: SessionSummary): void
  (e: 'createNew'): void
  (e: 'delete', session: SessionSummary): void
  (e: 'deleteAll'): void
}>()

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '未开始'
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) return '刚刚'
  if (diffMins < 60) return `${diffMins}分钟前`
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}小时前`
  if (diffMins < 10080) return `${Math.floor(diffMins / 1440)}天前`

  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

function toMessageTs(dateStr: string | null): number {
  if (!dateStr) return 0
  const t = Date.parse(dateStr)
  return Number.isFinite(t) ? t : 0
}

const sortedSessions = computed(() => {
  return [...props.sessions].sort((a, b) => {
    const ta = toMessageTs(a.last_message_at)
    const tb = toMessageTs(b.last_message_at)
    if (ta !== tb) return tb - ta
    return (b.message_count || 0) - (a.message_count || 0)
  })
})

const getSessionTitle = (session: SessionSummary) => {
  const t = (session.title || '').trim()
  if (t && t !== '对话' && t !== '新对话') return t
  if (session.message_count > 0) return `第${session.question_no}题 · ${formatDate(session.last_message_at)}`
  return '新对话'
}
</script>

<template>
  <div class="flex flex-col h-full bg-white/80 backdrop-blur-md border-r border-slate-200/60">
    <div class="p-4 border-b border-slate-100 flex justify-between items-center">
      <h2 class="text-lg font-semibold text-slate-700">对话历史</h2>
      <div class="flex items-center gap-2">
        <button
          @click="emit('deleteAll')"
          class="p-2 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="删除全部对话"
          :disabled="sortedSessions.length === 0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6h18" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 6V4h8v2" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 6l-1 14H6L5 6" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 11v6" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 11v6" />
          </svg>
        </button>
        <button
          @click="emit('createNew')"
          class="p-2 rounded-lg bg-indigo-500 hover:bg-indigo-600 text-white transition-colors"
          title="新建对话"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex-1 p-4 space-y-3">
      <div v-for="i in 3" :key="i" class="animate-pulse">
        <div class="h-4 bg-slate-200 rounded w-3/4 mb-2"></div>
        <div class="h-3 bg-slate-200 rounded w-1/2"></div>
      </div>
    </div>

    <div v-else class="flex-1 overflow-y-auto">
      <div v-if="sortedSessions.length === 0" class="p-8 text-center text-slate-400">
        暂无对话记录
      </div>

      <ul v-else class="divide-y divide-slate-100/60">
        <li
          v-for="session in sortedSessions"
          :key="session.session_id"
          @click="emit('select', session)"
          class="cursor-pointer hover:bg-white/60 transition-colors px-4 py-3 relative group"
          :class="{
            'bg-white/80 border-l-4 border-indigo-500': currentSessionId === session.session_id,
            'border-l-4 border-transparent': currentSessionId !== session.session_id
          }"
        >
          <div class="flex justify-between items-start mb-1">
            <span class="font-medium text-slate-700 truncate pr-2">
              {{ getSessionTitle(session) }}
            </span>
            <div class="flex items-center gap-2 flex-shrink-0">
              <span
                v-if="session.message_count > 0"
                class="px-2 py-0.5 text-xs rounded-full bg-indigo-100 text-indigo-600 font-medium"
              >
                {{ session.message_count }}
              </span>
              <button
                class="p-1 rounded-md text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                title="删除对话"
                @click.stop="emit('delete', session)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6h18" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 6V4h8v2" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 6l-1 14H6L5 6" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 11v6" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 11v6" />
                </svg>
              </button>
            </div>
          </div>
          <div class="text-xs text-slate-400 flex items-center justify-between gap-2">
            <span>{{ formatDate(session.last_message_at) }}</span>
            <span class="text-[11px] text-slate-400 flex-none">第 {{ session.question_no }} 题</span>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
div::-webkit-scrollbar {
  width: 4px;
}
div::-webkit-scrollbar-track {
  background: transparent;
}
div::-webkit-scrollbar-thumb {
  background-color: #cbd5e1;
  border-radius: 20px;
}
</style>
