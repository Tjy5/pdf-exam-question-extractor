<script setup lang="ts">
import { ref } from 'vue'
import QuestionNavigator from './QuestionNavigator.vue'
import SessionList from './SessionList.vue'
import type { SessionSummary } from '@/stores/useChatStore'

const props = defineProps<{
  examId: number
  currentQuestionNo: number
  totalQuestions?: number
  sessions: SessionSummary[]
  currentSessionId: string | null
  sessionsLoading: boolean
}>()

const emit = defineEmits<{
  (e: 'selectSession', session: SessionSummary): void
  (e: 'createNewSession'): void
  (e: 'deleteSession', session: SessionSummary): void
  (e: 'deleteAllSessions'): void
}>()

type TabType = 'questions' | 'sessions'
const activeTab = ref<TabType>('questions')

function setTab(tab: TabType) {
  activeTab.value = tab
}
</script>

<template>
  <div class="flex flex-col h-full bg-white/80 backdrop-blur-md border-r border-slate-200/60">
    <!-- 标签切换 -->
    <div class="flex border-b border-slate-100 bg-slate-50/50">
      <button
        @click="setTab('questions')"
        class="flex-1 px-4 py-3 text-sm font-medium transition-colors relative"
        :class="activeTab === 'questions'
          ? 'text-indigo-600 bg-white'
          : 'text-slate-600 hover:text-slate-800 hover:bg-white/50'"
      >
        <span class="flex items-center justify-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
          </svg>
          题目
        </span>
        <div
          v-if="activeTab === 'questions'"
          class="absolute bottom-0 left-0 right-0 h-0.5 bg-indigo-600"
        ></div>
      </button>

      <button
        @click="setTab('sessions')"
        class="flex-1 px-4 py-3 text-sm font-medium transition-colors relative"
        :class="activeTab === 'sessions'
          ? 'text-indigo-600 bg-white'
          : 'text-slate-600 hover:text-slate-800 hover:bg-white/50'"
      >
        <span class="flex items-center justify-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          会话
        </span>
        <div
          v-if="activeTab === 'sessions'"
          class="absolute bottom-0 left-0 right-0 h-0.5 bg-indigo-600"
        ></div>
      </button>
    </div>

    <!-- 标签内容 -->
    <div class="flex-1 overflow-hidden">
      <!-- Tab 1: 题目导航 -->
      <div v-show="activeTab === 'questions'" class="h-full">
        <QuestionNavigator
          :exam-id="examId"
          :current-question-no="currentQuestionNo"
          :total-questions="totalQuestions"
        />
      </div>

      <!-- Tab 2: 会话历史 -->
      <div v-show="activeTab === 'sessions'" class="h-full">
        <SessionList
          :sessions="sessions"
          :current-session-id="currentSessionId"
          :loading="sessionsLoading"
          @select="(session) => emit('selectSession', session)"
          @create-new="emit('createNewSession')"
          @delete="(session) => emit('deleteSession', session)"
          @delete-all="emit('deleteAllSessions')"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
button:focus {
  outline: none;
}
</style>
