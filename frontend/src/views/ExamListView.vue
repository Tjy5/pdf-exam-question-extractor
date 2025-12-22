<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import ExamList from '@/components/exams/ExamList.vue'
import LocalExamImporter from '@/components/exams/LocalExamImporter.vue'
import { useExamStore } from '@/stores/useExamStore'

const showLocalImporter = ref(false)
const examStore = useExamStore()

function onLocalImportSuccess() {
  // 刷新试卷列表
  examStore.fetchExams()
}
</script>

<template>
  <div class="container mx-auto px-4 py-8 max-w-6xl">
    <!-- Page Header -->
    <header class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8 animate-float">
      <div>
        <h1 class="text-3xl font-extrabold text-slate-900 flex items-center gap-3">
          <span class="text-4xl">📚</span>
          <span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-violet-600">我的题库</span>
        </h1>
        <p class="text-slate-500 mt-2 text-lg">管理和复习所有已处理的试卷</p>
      </div>
      <div class="flex items-center gap-3">
        <button
          @click="showLocalImporter = true"
          class="px-5 py-2.5 text-indigo-600 bg-white border border-indigo-200 hover:bg-indigo-50 rounded-xl transition-colors font-medium shadow-sm hover:shadow-indigo-500/10 flex items-center gap-2"
        >
          <span>📂</span> 导入本地
        </button>

        <RouterLink
          to="/dashboard"
          class="px-5 py-2.5 text-white bg-indigo-600 hover:bg-indigo-700 rounded-xl transition-colors font-medium shadow-lg hover:shadow-indigo-500/30 flex items-center gap-2"
        >
          <span>📤</span> 上传新试卷
        </RouterLink>
      </div>
    </header>

    <!-- Main Content -->
    <ErrorBoundary>
      <ExamList />
    </ErrorBoundary>

    <!-- Local Exam Importer Modal -->
    <LocalExamImporter
      v-if="showLocalImporter"
      @close="showLocalImporter = false"
      @success="onLocalImportSuccess"
    />
  </div>
</template>

<style scoped>
.animate-float {
  animation: float 8s ease-in-out infinite;
}

@keyframes float {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}
</style>
