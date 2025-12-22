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
  <div class="flex flex-col h-full bg-transparent">
    <!-- 标签切换 -->
    <div class="flex p-3 bg-transparent shrink-0">
      <div class="flex w-full bg-slate-100/50 p-1 rounded-xl">
        <button
          @click="setTab('questions')"
          class="flex-1 py-2 text-sm font-medium transition-all rounded-lg flex items-center justify-center gap-2"
          :class="activeTab === 'questions'
            ? 'bg-white text-indigo-600 shadow-sm ring-1 ring-black/5'
            : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
          </svg>
          题目列表
        </button>

        <button
          @click="setTab('sessions')"
          class="flex-1 py-2 text-sm font-medium transition-all rounded-lg flex items-center justify-center gap-2"
          :class="activeTab === 'sessions'
            ? 'bg-white text-indigo-600 shadow-sm ring-1 ring-black/5'
            : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          会话历史
        </button>
      </div>
    </div>

    <!-- 标签内容 -->
    <div class="flex-1 overflow-hidden relative">
      <Transition
        enter-active-class="transition duration-300 ease-out absolute inset-0"
        enter-from-class="opacity-0 translate-y-2"
        enter-to-class="opacity-100 translate-y-0"
        leave-active-class="transition duration-200 ease-in absolute inset-0"
        leave-from-class="opacity-100 translate-y-0"
        leave-to-class="opacity-0 -translate-y-2"
      >
        <div v-if="activeTab === 'questions'" class="h-full w-full absolute inset-0">
          <QuestionNavigator
            :exam-id="examId"
            :current-question-no="currentQuestionNo"
            :total-questions="totalQuestions"
          />
        </div>
      
        <div v-else class="h-full w-full absolute inset-0">
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
      </Transition>
    </div>
  </div>
</template>

<style scoped>
button:focus {
  outline: none;
}
</style>
