<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useExamStore, type Question } from '@/stores/useExamStore'
import { useWrongStore, type QuestionStatus } from '@/stores/useWrongStore'
import { useUserStore } from '@/stores/useUserStore'

const route = useRoute()
const router = useRouter()
const examStore = useExamStore()
const wrongStore = useWrongStore()
const userStore = useUserStore()

const examId = computed(() => Number(route.params.examId))
const currentIdx = ref(0)
const showSidebar = ref(false)
const initError = ref<string | null>(null)

const questions = computed(() => examStore.currentExam?.questions || [])
const currentQuestion = computed<Question | undefined>(() => questions.value[currentIdx.value])

const currentAnswer = computed({
  get: () => wrongStore.answersByNo[currentQuestion.value?.question_no || 0] || '',
  set: (val: string) => {
    if (currentQuestion.value) {
      wrongStore.setAnswer(examId.value, currentQuestion.value.question_no, val)
    }
  }
})

function getStatusClass(q: Question, idx: number): string {
  const status = wrongStore.statusByNo[q.question_no] || 'unanswered'
  const isActive = currentIdx.value === idx
  const base = 'cursor-pointer flex items-center justify-center h-10 w-10 rounded-lg transition-all font-medium text-sm '

  const statusColors: Record<QuestionStatus, string> = {
    correct: 'bg-emerald-100 text-emerald-600 border border-emerald-200',
    wrong: 'bg-rose-100 text-rose-600 border border-rose-200',
    unanswered: 'bg-slate-100 text-slate-400 hover:bg-slate-200',
    pending: 'bg-indigo-100 text-indigo-600 animate-pulse',
    noStandard: 'bg-yellow-100 text-yellow-600 border border-yellow-200'
  }

  const colorClass = statusColors[status] || statusColors.unanswered

  if (isActive) return base + 'ring-2 ring-indigo-500 ring-offset-2 ' + colorClass
  return base + colorClass
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowRight') next()
  if (e.key === 'ArrowLeft') prev()
  if (e.key === 'a' || e.key === 'A') currentAnswer.value = 'A'
  if (e.key === 'b' || e.key === 'B') currentAnswer.value = 'B'
  if (e.key === 'c' || e.key === 'C') currentAnswer.value = 'C'
  if (e.key === 'd' || e.key === 'D') currentAnswer.value = 'D'
}

function next() {
  if (currentIdx.value < questions.value.length - 1) currentIdx.value++
}

function prev() {
  if (currentIdx.value > 0) currentIdx.value--
}

function jumpTo(index: number) {
  currentIdx.value = index
  showSidebar.value = false
}

function goToChat() {
  if (!currentQuestion.value) return
  router.push({
    path: `/exam/${examId.value}/chat`,
    query: { q: currentQuestion.value.question_no }
  })
}

function goToDashboard() {
  router.push('/dashboard')
}

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown)

  if (!examId.value || examId.value === 0) {
    initError.value = '缺少试卷ID，请从试卷列表进入复习页面'
    return
  }

  try {
    await wrongStore.initReview(examId.value)
  } catch (err: unknown) {
    initError.value = err instanceof Error ? err.message : '初始化复习失败'
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  wrongStore.clearReview()
})
</script>

<template>
  <div class="min-h-screen flex flex-col md:flex-row gap-6 p-4 md:p-6 bg-slate-50/50">
    <!-- 移动端侧边栏切换按钮 -->
    <button
      class="md:hidden fixed bottom-6 right-6 z-50 bg-indigo-600 text-white p-4 rounded-full shadow-xl hover:bg-indigo-700 transition-colors"
      @click="showSidebar = !showSidebar"
    >
      <span class="text-xl">{{ showSidebar ? '✕' : '☰' }}</span>
    </button>

    <!-- 初始化错误提示 -->
    <div v-if="initError" class="flex-1 flex flex-col items-center justify-center text-center p-8">
      <div class="w-20 h-20 bg-gradient-to-tr from-red-100 to-orange-100 rounded-full flex items-center justify-center mb-6 shadow-sm">
        <span class="text-4xl">⚠️</span>
      </div>
      <h2 class="text-xl font-semibold text-slate-700 mb-2">无法初始化复习</h2>
      <p class="text-slate-500 max-w-md mx-auto mb-6">{{ initError }}</p>
      <button
        @click="goToDashboard"
        class="px-6 py-3 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 transition-colors"
      >
        返回试卷列表
      </button>
    </div>

    <!-- 正常界面 -->
    <template v-else>
      <!-- 左侧题目网格 -->
      <aside
        :class="[
          'glass-panel flex flex-col w-80 h-[calc(100vh-2rem)] rounded-2xl transition-transform duration-300 ease-in-out',
          'md:sticky md:top-4',
          'fixed left-0 top-0 bottom-0 z-40',
          showSidebar ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        ]"
      >
        <div class="p-6 border-b border-slate-100/50">
          <h2 class="text-lg font-bold text-slate-800 mb-4">题目列表</h2>

          <!-- 进度统计 -->
          <div class="mb-4 p-3 bg-indigo-50 rounded-xl">
            <div class="flex justify-between items-center text-sm mb-2">
              <span class="text-slate-600">完成进度</span>
              <span class="font-bold text-indigo-600">{{ wrongStore.progress.percentage }}%</span>
            </div>
            <div class="w-full bg-slate-200 rounded-full h-2 overflow-hidden">
              <div
                class="bg-gradient-to-r from-indigo-500 to-violet-500 h-full transition-all duration-300"
                :style="{ width: `${wrongStore.progress.percentage}%` }"
              ></div>
            </div>
            <div class="flex justify-between mt-2 text-xs text-slate-500">
              <span>✓ 正确: {{ wrongStore.progress.correct }}</span>
              <span>✗ 错误: {{ wrongStore.progress.wrong }}</span>
            </div>
          </div>

          <!-- 状态图例 -->
          <div class="flex flex-wrap gap-2 text-xs text-slate-500">
            <div class="flex items-center gap-1">
              <span class="w-2 h-2 rounded-full bg-emerald-500"></span>正确
            </div>
            <div class="flex items-center gap-1">
              <span class="w-2 h-2 rounded-full bg-rose-500"></span>错误
            </div>
            <div class="flex items-center gap-1">
              <span class="w-2 h-2 rounded-full bg-slate-300"></span>未答
            </div>
            <div class="flex items-center gap-1">
              <span class="w-2 h-2 rounded-full bg-yellow-500"></span>无答案
            </div>
          </div>
        </div>

        <!-- 题目网格 -->
        <div class="flex-1 overflow-y-auto p-6">
          <div v-if="wrongStore.loading" class="flex justify-center py-12">
            <div class="animate-spin rounded-full h-8 w-8 border-4 border-indigo-500 border-t-transparent"></div>
          </div>
          <div v-else class="grid grid-cols-5 gap-3">
            <button
              v-for="(q, idx) in questions"
              :key="q.question_no"
              :class="getStatusClass(q, idx)"
              @click="jumpTo(idx)"
              :title="`题目 ${q.question_no}`"
              :aria-label="`题目 ${q.question_no}`"
            >
              {{ q.question_no }}
            </button>
          </div>
        </div>
      </aside>

      <!-- 右侧题目详情 -->
      <main class="flex-1 flex flex-col min-w-0">
        <div v-if="!currentQuestion" class="glass-panel rounded-2xl p-12 flex items-center justify-center text-slate-400">
          <div class="text-center">
            <span class="text-6xl mb-4 block">📝</span>
            <p>请从左侧选择题目开始复习</p>
          </div>
        </div>

        <div v-else class="glass-panel rounded-2xl flex flex-col overflow-hidden">
          <!-- 头部 -->
          <header class="flex items-center justify-between p-6 border-b border-slate-100/50 bg-white/40">
            <div>
              <h1 class="text-xl font-bold text-slate-800">
                第 {{ currentQuestion.question_no }} 题
              </h1>
              <div class="flex items-center gap-2 mt-1 text-sm">
                <span
                  :class="[
                    'px-2 py-0.5 rounded-full text-xs font-medium',
                    wrongStore.statusByNo[currentQuestion.question_no] === 'correct' ? 'bg-emerald-100 text-emerald-700' :
                    wrongStore.statusByNo[currentQuestion.question_no] === 'wrong' ? 'bg-rose-100 text-rose-700' :
                    wrongStore.statusByNo[currentQuestion.question_no] === 'pending' ? 'bg-indigo-100 text-indigo-700' :
                    'bg-slate-100 text-slate-600'
                  ]"
                >
                  {{
                    wrongStore.statusByNo[currentQuestion.question_no] === 'correct' ? '✓ 正确' :
                    wrongStore.statusByNo[currentQuestion.question_no] === 'wrong' ? '✗ 错误' :
                    wrongStore.statusByNo[currentQuestion.question_no] === 'pending' ? '⏳ 提交中' :
                    '未作答'
                  }}
                </span>
              </div>
            </div>
            <button
              @click="goToChat"
              class="flex items-center gap-2 px-4 py-2 bg-indigo-50 text-indigo-600 rounded-xl hover:bg-indigo-100 transition-colors font-medium"
            >
              <span>✨</span> AI 答疑
            </button>
          </header>

          <!-- 题目内容区 -->
          <div class="flex-1 overflow-y-auto p-6 md:p-8 space-y-8">
            <!-- 提交错误提示 -->
            <div
              v-if="wrongStore.error"
              class="bg-rose-50 border border-rose-200 rounded-xl p-4 flex items-center gap-3"
            >
              <span class="text-rose-600 text-xl">⚠️</span>
              <div class="flex-1">
                <p class="text-sm font-medium text-rose-700">提交失败</p>
                <p class="text-sm text-rose-600">{{ wrongStore.error }}</p>
              </div>
              <button
                @click="wrongStore.error = null"
                class="text-rose-400 hover:text-rose-600"
              >
                ✕
              </button>
            </div>

            <!-- 题目图片 -->
            <div class="rounded-2xl overflow-hidden border border-slate-200 bg-slate-50 shadow-sm">
              <img
                v-if="currentQuestion.image_url"
                :src="currentQuestion.image_url"
                class="w-full object-contain max-h-[500px]"
                alt="题目图片"
              />
              <div v-else class="h-48 flex items-center justify-center text-slate-400">
                暂无题目图片
              </div>
            </div>

            <!-- 答案输入区 -->
            <div class="max-w-2xl mx-auto w-full">
              <div class="text-sm font-medium text-slate-500 mb-4 uppercase tracking-wider">
                您的答案
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                <button
                  v-for="opt in ['A', 'B', 'C', 'D']"
                  :key="opt"
                  @click="currentAnswer = opt"
                  :class="[
                    'h-14 rounded-xl font-bold text-lg transition-all border-2',
                    currentAnswer === opt
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-700 shadow-md scale-105'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-indigo-200 hover:bg-slate-50'
                  ]"
                  :disabled="wrongStore.submitting"
                >
                  {{ opt }}
                </button>
              </div>

              <!-- 错题时显示正确答案 -->
              <div
                v-if="wrongStore.statusByNo[currentQuestion.question_no] === 'wrong' && wrongStore.correctAnswersByNo[currentQuestion.question_no]"
                class="mt-4 p-4 bg-emerald-50 border border-emerald-200 rounded-xl"
              >
                <div class="flex items-center gap-2 text-sm text-emerald-700">
                  <span class="font-bold">正确答案:</span>
                  <span class="text-lg font-bold">{{ wrongStore.correctAnswersByNo[currentQuestion.question_no] }}</span>
                </div>
              </div>

              <!-- 提交状态提示 -->
              <div v-if="wrongStore.submitting" class="mt-4 flex items-center justify-center gap-2 text-sm text-indigo-600">
                <div class="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin"></div>
                <span>正在提交...</span>
              </div>
            </div>
          </div>

          <!-- 底部导航 -->
          <footer class="p-6 border-t border-slate-100/50 bg-white/40 flex justify-between items-center">
            <button
              @click="prev"
              :disabled="currentIdx === 0"
              class="px-6 py-3 rounded-xl font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-100 text-slate-700"
            >
              上一题
            </button>

            <div class="text-slate-400 font-medium">
              {{ currentIdx + 1 }} / {{ questions.length }}
            </div>

            <button
              @click="next"
              :disabled="currentIdx === questions.length - 1"
              class="px-6 py-3 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-indigo-200"
            >
              {{ currentIdx === questions.length - 1 ? '完成' : '下一题' }}
            </button>
          </footer>
        </div>
      </main>
    </template>
  </div>
</template>
