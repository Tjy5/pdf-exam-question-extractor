<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useExamStore, type Exam } from '@/stores/useExamStore'

const props = defineProps<{
  currentExamId: number
  currentQuestionNo: number
  hasUnsavedInput?: boolean
}>()

const emit = defineEmits<{
  (e: 'switch', examId: number, questionNo: number): void
}>()

const examStore = useExamStore()
const router = useRouter()
const isOpen = ref(false)
const searchQuery = ref('')

onMounted(() => {
  if (examStore.exams.length === 0) {
    examStore.fetchExams()
  }
})

const currentExam = computed(() =>
  examStore.exams.find(e => e.id === props.currentExamId)
)

const filteredExams = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return examStore.exams

  return examStore.exams.filter(exam => {
    const name = exam.display_name || exam.exam_dir_name
    return name.toLowerCase().includes(query)
  })
})

// 最近使用的试卷（简化：取前3个）
const recentExams = computed(() => filteredExams.value.slice(0, 3))

// 其他试卷
const otherExams = computed(() => filteredExams.value.slice(3))

function handleSelectExam(exam: Exam) {
  if (exam.id === props.currentExamId) {
    isOpen.value = false
    return
  }

  // 检查是否有未保存的输入
  if (props.hasUnsavedInput) {
    if (!confirm('切换试卷将清空当前输入，是否继续？')) {
      return
    }
  }

  isOpen.value = false

  // 切换到新试卷的第1题
  router.push({
    path: `/exam/${exam.id}/chat`,
    query: { q: 1 }
  })
}

function getExamDisplayName(exam: Exam) {
  return exam.display_name || exam.exam_dir_name
}

function closeDropdown() {
  isOpen.value = false
  searchQuery.value = ''
}
</script>

<template>
  <div class="relative">
    <button
      @click="isOpen = !isOpen"
      class="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium transition-colors text-sm max-w-xs truncate"
      :class="{ 'bg-slate-200': isOpen }"
    >
      <span class="truncate">
        {{ currentExam ? getExamDisplayName(currentExam) : `试卷 #${currentExamId}` }}
      </span>
      <svg
        xmlns="http://www.w3.org/2000/svg"
        class="h-4 w-4 transition-transform flex-shrink-0"
        :class="{ 'rotate-180': isOpen }"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <!-- 遮罩层 -->
    <div
      v-if="isOpen"
      class="fixed inset-0 z-30"
      @click="closeDropdown"
    ></div>

    <!-- 下拉菜单 -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100 scale-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="isOpen"
        class="absolute left-0 top-full mt-2 w-80 max-h-96 overflow-y-auto bg-white rounded-lg shadow-lg border border-slate-200 z-40"
      >
        <!-- 搜索框 -->
        <div class="p-3 border-b border-slate-100 sticky top-0 bg-white">
          <div class="relative">
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索试卷..."
              class="w-full pl-8 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              @click.stop
            />
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
        </div>

        <!-- 加载状态 -->
        <div v-if="examStore.loading" class="p-6 text-center text-slate-400">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500 mx-auto"></div>
          <p class="mt-2 text-sm">加载中...</p>
        </div>

        <!-- 试卷列表 -->
        <div v-else-if="filteredExams.length > 0" class="py-2">
          <!-- 最近使用 -->
          <div v-if="recentExams.length > 0 && !searchQuery">
            <div class="px-3 py-1 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              最近使用
            </div>
            <button
              v-for="exam in recentExams"
              :key="exam.id"
              @click="handleSelectExam(exam)"
              class="w-full px-3 py-2 hover:bg-slate-50 text-left transition-colors flex items-center justify-between group"
              :class="{ 'bg-indigo-50 hover:bg-indigo-100': exam.id === currentExamId }"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span
                    v-if="exam.id === currentExamId"
                    class="flex-shrink-0 w-1.5 h-1.5 rounded-full bg-indigo-500"
                  ></span>
                  <span class="text-sm font-medium text-slate-700 truncate">
                    {{ getExamDisplayName(exam) }}
                  </span>
                </div>
                <div class="text-xs text-slate-500 mt-0.5 flex items-center gap-2">
                  <span>{{ exam.question_count }} 题</span>
                  <span v-if="exam.has_answers" class="text-emerald-600">✓已导入答案</span>
                </div>
              </div>
            </button>
          </div>

          <!-- 分隔线 -->
          <div v-if="recentExams.length > 0 && otherExams.length > 0 && !searchQuery" class="my-2 border-t border-slate-100"></div>

          <!-- 所有试卷 / 搜索结果 -->
          <div v-if="otherExams.length > 0 || searchQuery">
            <div v-if="!searchQuery" class="px-3 py-1 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              所有试卷
            </div>
            <button
              v-for="exam in (searchQuery ? filteredExams : otherExams)"
              :key="exam.id"
              @click="handleSelectExam(exam)"
              class="w-full px-3 py-2 hover:bg-slate-50 text-left transition-colors flex items-center justify-between group"
              :class="{ 'bg-indigo-50 hover:bg-indigo-100': exam.id === currentExamId }"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span
                    v-if="exam.id === currentExamId"
                    class="flex-shrink-0 w-1.5 h-1.5 rounded-full bg-indigo-500"
                  ></span>
                  <span class="text-sm font-medium text-slate-700 truncate">
                    {{ getExamDisplayName(exam) }}
                  </span>
                </div>
                <div class="text-xs text-slate-500 mt-0.5 flex items-center gap-2">
                  <span>{{ exam.question_count }} 题</span>
                  <span v-if="exam.has_answers" class="text-emerald-600">✓已导入答案</span>
                  <span v-else class="text-amber-600">⚠未导入答案</span>
                </div>
              </div>
            </button>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else class="p-6 text-center text-slate-400">
          <p class="text-sm">{{ searchQuery ? '未找到匹配的试卷' : '暂无试卷' }}</p>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
div::-webkit-scrollbar {
  width: 6px;
}
div::-webkit-scrollbar-track {
  background: transparent;
}
div::-webkit-scrollbar-thumb {
  background-color: #cbd5e1;
  border-radius: 20px;
}
</style>
