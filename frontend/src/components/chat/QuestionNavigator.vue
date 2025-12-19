<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/useChatStore'
import { useExamStore, type Question } from '@/stores/useExamStore'

const props = defineProps<{
  examId: number
  currentQuestionNo: number
  totalQuestions?: number
}>()

const router = useRouter()
const chatStore = useChatStore()
const examStore = useExamStore()

const searchQuery = ref('')
const filterType = ref<'all' | 'chat' | 'bookmarked' | 'unvisited' | 'data_analysis'>('all')

// 从store获取题目列表
const questions = computed<Question[]>(() => {
  if (examStore.currentExam?.exam.id === props.examId) {
    return examStore.currentExam.questions
  }
  return []
})

// 普通题目（非资料分析）
const normalQuestions = computed(() => {
  return questions.value.filter(q => q.question_type !== 'data_analysis' && q.question_no < 1000)
})

// 资料分析大题
const dataAnalysisQuestions = computed(() => {
  return questions.value.filter(q => q.question_type === 'data_analysis' || q.question_no >= 1000)
})

// 过滤后的题目
const filteredQuestions = computed(() => {
  let list = questions.value
  
  // 按类型筛选
  if (filterType.value === 'data_analysis') {
    list = dataAnalysisQuestions.value
  } else if (filterType.value !== 'all') {
    list = normalQuestions.value
  }
  
  return list.filter(q => {
    // 搜索过滤
    if (searchQuery.value) {
      const label = q.display_label || q.question_no.toString()
      if (!label.includes(searchQuery.value) && !q.question_no.toString().includes(searchQuery.value)) {
        return false
      }
    }

    const status = getQuestionStatus(q.question_no)
    const bookmarked = chatStore.isBookmarked(props.examId, q.question_no)

    if (filterType.value === 'chat' && status !== 'hasSession' && status !== 'current') return false
    if (filterType.value === 'unvisited' && status !== 'unvisited') return false
    if (filterType.value === 'bookmarked' && !bookmarked) return false

    return true
  })
})

// 获取题目状态
function getQuestionStatus(qNo: number): 'current' | 'hasSession' | 'unvisited' {
  return chatStore.getQuestionStatus(props.examId, qNo)
}

// 获取题目按钮的样式类
function getQuestionButtonClass(q: Question) {
  const status = getQuestionStatus(q.question_no)
  const bookmarked = chatStore.isBookmarked(props.examId, q.question_no)
  const isDataAnalysis = q.question_type === 'data_analysis' || q.question_no >= 1000

  // 资料分析大题使用更宽的按钮
  const baseClasses = isDataAnalysis 
    ? 'col-span-5 py-2 px-3 rounded-lg font-medium text-sm transition-all relative text-left'
    : 'w-12 h-12 rounded-lg font-medium text-sm transition-all relative'

  if (status === 'current') {
    return `${baseClasses} bg-indigo-500 text-white shadow-md ${bookmarked ? 'ring-2 ring-yellow-300' : ''}`
  } else if (status === 'hasSession') {
    return `${baseClasses} bg-white text-slate-700 border-2 border-indigo-300 hover:bg-indigo-50 ${bookmarked ? 'ring-2 ring-yellow-300' : ''}`
  } else {
    const bgColor = isDataAnalysis ? 'bg-emerald-50 hover:bg-emerald-100' : 'bg-slate-100 hover:bg-slate-200'
    return `${baseClasses} ${bgColor} text-slate-600 ${bookmarked ? 'ring-2 ring-yellow-400' : ''}`
  }
}

// 获取显示标签
function getDisplayLabel(q: Question): string {
  if (q.display_label) return q.display_label
  if (q.question_type === 'data_analysis' || q.question_no >= 1000) {
    const order = q.question_no >= 1000 ? q.question_no - 1000 : q.question_no
    const nums = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
    return `资料分析第${nums[order - 1] || order}大题`
  }
  return String(q.question_no)
}

// 点击题号
function handleQuestionClick(qNo: number) {
  if (qNo === props.currentQuestionNo) return

  router.push({
    path: `/exam/${props.examId}/chat`,
    query: { q: qNo }
  })
}

// 上一题/下一题导航
const currentIndex = computed(() => {
  return questions.value.findIndex(q => q.question_no === props.currentQuestionNo)
})

function goToPrevQuestion() {
  if (currentIndex.value <= 0) return
  const prevQ = questions.value[currentIndex.value - 1]
  if (prevQ) handleQuestionClick(prevQ.question_no)
}

function goToNextQuestion() {
  if (currentIndex.value < 0 || currentIndex.value >= questions.value.length - 1) return
  const nextQ = questions.value[currentIndex.value + 1]
  if (nextQ) handleQuestionClick(nextQ.question_no)
}

const canGoPrev = computed(() => currentIndex.value > 0)
const canGoNext = computed(() => currentIndex.value >= 0 && currentIndex.value < questions.value.length - 1)
</script>

<template>
  <div class="flex flex-col h-full bg-white/80 backdrop-blur-md">
    <!-- 标题 -->
    <div class="p-4 border-b border-slate-100">
      <h3 class="font-semibold text-slate-700 flex items-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
        </svg>
        题目导航
        <span v-if="dataAnalysisQuestions.length" class="ml-2 text-xs text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">
          含{{ dataAnalysisQuestions.length }}个资料分析
        </span>
      </h3>
    </div>

    <!-- 搜索与筛选 -->
    <div class="px-4 py-2 border-b border-slate-100 space-y-2">
      <input
        v-model="searchQuery"
        type="text"
        placeholder="搜索题号..."
        class="w-full px-3 py-1.5 text-sm bg-slate-50 border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />
      <div class="flex gap-1 text-xs flex-wrap">
        <button
          v-for="f in [
            { k: 'all', l: '全部' },
            { k: 'chat', l: '已聊' },
            { k: 'bookmarked', l: '收藏' },
            { k: 'unvisited', l: '未访问' },
            { k: 'data_analysis', l: '资料分析' }
          ]"
          :key="f.k"
          @click="filterType = f.k as any"
          class="flex-1 py-1 rounded border transition-colors min-w-[50px]"
          :class="filterType === f.k ? 'bg-indigo-50 border-indigo-200 text-indigo-600' : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'"
        >
          {{ f.l }}
        </button>
      </div>
    </div>

    <!-- 题目网格 -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="filteredQuestions.length === 0" class="text-center text-slate-400 py-8">
        <p class="text-sm">暂无题目</p>
      </div>

      <div v-else class="grid grid-cols-5 gap-2">
        <button
          v-for="q in filteredQuestions"
          :key="q.question_no"
          :class="getQuestionButtonClass(q)"
          @click="handleQuestionClick(q.question_no)"
          :disabled="q.question_no === currentQuestionNo"
        >
          <span class="relative z-10">{{ getDisplayLabel(q) }}</span>
          <!-- 当前题标记 -->
          <span
            v-if="q.question_no === currentQuestionNo"
            class="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-white"
          ></span>
          <!-- 收藏标记 -->
          <span
            v-if="chatStore.isBookmarked(props.examId, q.question_no)"
            class="absolute bottom-0.5 right-1 text-[10px] leading-none"
          >⭐</span>
        </button>
      </div>

      <!-- 状态图例 -->
      <div class="mt-6 pt-4 border-t border-slate-100 space-y-2 text-xs text-slate-600">
        <div class="flex items-center gap-2">
          <div class="w-4 h-4 rounded bg-indigo-500"></div>
          <span>当前题目</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-4 h-4 rounded bg-white border-2 border-indigo-300"></div>
          <span>有聊天记录</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-4 h-4 rounded bg-slate-100"></div>
          <span>未访问</span>
        </div>
        <div v-if="dataAnalysisQuestions.length" class="flex items-center gap-2">
          <div class="w-4 h-4 rounded bg-emerald-50"></div>
          <span>资料分析大题</span>
        </div>
      </div>
    </div>

    <!-- 快捷导航按钮 -->
    <div class="p-4 border-t border-slate-100 bg-slate-50/50">
      <div class="flex gap-2">
        <button
          @click="goToPrevQuestion"
          :disabled="!canGoPrev"
          class="flex-1 px-4 py-2 rounded-lg bg-white border border-slate-200 text-slate-700 font-medium hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
          :class="{ 'hover:bg-slate-50': canGoPrev, 'cursor-not-allowed': !canGoPrev }"
        >
          ← 上一题
        </button>
        <button
          @click="goToNextQuestion"
          :disabled="!canGoNext"
          class="flex-1 px-4 py-2 rounded-lg bg-white border border-slate-200 text-slate-700 font-medium hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
          :class="{ 'hover:bg-slate-50': canGoNext, 'cursor-not-allowed': !canGoNext }"
        >
          下一题 →
        </button>
      </div>
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

button:disabled {
  cursor: not-allowed;
}
</style>
