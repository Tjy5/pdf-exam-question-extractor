<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useExamStore } from '@/stores/useExamStore'
import AnswerImporter from './AnswerImporter.vue'

const examStore = useExamStore()
const router = useRouter()

const showImporter = ref(false)
const selectedExam = ref<{ id: number; name: string } | null>(null)

onMounted(() => {
  examStore.fetchExams()
})

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '未知'
  try {
    const date = new Date(dateStr)
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return dateStr
  }
}

function goToChat(examId: number, questionNo: number = 1) {
  router.push({
    path: `/exam/${examId}/chat`,
    query: { q: questionNo }
  })
}

function goToReview(examId: number) {
  router.push(`/exam/${examId}/review`)
}

function openImporter(examId: number, examName: string) {
  selectedExam.value = { id: examId, name: examName }
  showImporter.value = true
}

function closeImporter() {
  showImporter.value = false
  selectedExam.value = null
}

function handleImportSuccess(result: any) {
  // 刷新试卷列表以更新 has_answers 状态
  examStore.fetchExams()
}
</script>

<template>
  <div class="glass-panel rounded-3xl p-8">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-2xl font-bold text-slate-800 flex items-center">
        <span class="text-indigo-500 mr-2 text-3xl">📚</span>
        试卷列表
      </h2>
      <button
        @click="examStore.fetchExams()"
        class="px-4 py-2 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg font-medium transition-colors"
        :disabled="examStore.loading"
      >
        {{ examStore.loading ? '刷新中...' : '🔄 刷新' }}
      </button>
    </div>

    <!-- 加载状态 -->
    <div v-if="examStore.loading && examStore.exams.length === 0" class="text-center py-12">
      <div class="inline-block animate-spin rounded-full h-12 w-12 border-4 border-indigo-500 border-t-transparent"></div>
      <p class="mt-4 text-slate-500">加载中...</p>
    </div>

    <!-- 错误提示 -->
    <div v-else-if="examStore.error" class="bg-red-50 border border-red-200 rounded-lg p-4 text-red-600">
      ❌ {{ examStore.error }}
    </div>

    <!-- 空状态 -->
    <div v-else-if="examStore.exams.length === 0" class="text-center py-12">
      <div class="text-6xl mb-4">📄</div>
      <p class="text-slate-400 text-lg">还没有处理过的试卷</p>
      <p class="text-slate-400 text-sm mt-2">请先上传 PDF 试卷进行处理</p>
    </div>

    <!-- 试卷卡片列表 -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div
        v-for="exam in examStore.exams"
        :key="exam.id"
        class="bg-white rounded-2xl p-6 shadow-sm hover:shadow-md transition-shadow border border-slate-100"
      >
        <!-- 试卷标题 -->
        <div class="mb-4">
          <h3 class="text-lg font-bold text-slate-800 mb-2 line-clamp-2">
            {{ exam.display_name || exam.exam_dir_name }}
          </h3>
          <div class="flex items-center gap-4 text-sm text-slate-500">
            <span class="flex items-center gap-1">
              📝 {{ exam.question_count }} 题
            </span>
            <span
              v-if="exam.has_answers"
              class="flex items-center gap-1 text-green-600"
            >
              ✓ 已导入答案
            </span>
            <span v-else class="flex items-center gap-1 text-orange-500">
              ⚠️ 未导入答案
            </span>
          </div>
        </div>

        <!-- 时间信息 -->
        <div class="text-xs text-slate-400 mb-4">
          <div>创建：{{ formatDate(exam.created_at) }}</div>
          <div v-if="exam.processed_at">
            处理：{{ formatDate(exam.processed_at) }}
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="space-y-2">
          <div class="flex gap-2">
            <button
              @click="goToChat(exam.id)"
              class="flex-1 px-4 py-2 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg font-medium text-sm transition-colors"
            >
              💬 AI 答疑
            </button>
            <button
              @click="goToReview(exam.id)"
              class="flex-1 px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg font-medium text-sm transition-colors"
            >
              📖 复习
            </button>
          </div>
          <button
            v-if="!exam.has_answers"
            @click="openImporter(exam.id, exam.display_name || exam.exam_dir_name)"
            class="w-full px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg font-medium text-sm transition-colors"
          >
            📥 导入答案
          </button>
        </div>
      </div>
    </div>

    <!-- 答案导入对话框 -->
    <AnswerImporter
      v-if="showImporter && selectedExam"
      :exam-id="selectedExam.id"
      :exam-name="selectedExam.name"
      @close="closeImporter"
      @success="handleImportSuccess"
    />
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
