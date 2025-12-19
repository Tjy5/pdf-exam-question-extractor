<script setup lang="ts">
import { RouterLink } from 'vue-router'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import UploadZone from '@/components/upload/UploadZone.vue'
import LogTerminal from '@/components/logs/LogTerminal.vue'
import PipelineView from '@/components/pipeline/PipelineView.vue'
import ResultGallery from '@/components/results/ResultGallery.vue'
import ExamList from '@/components/exams/ExamList.vue'
</script>

<template>
  <div class="container mx-auto px-4 py-8 max-w-6xl">
    <!-- Header -->
    <header class="text-center mb-12 animate-float">
      <div class="inline-flex items-center justify-center p-3 bg-white rounded-2xl shadow-sm mb-4">
        <span class="text-3xl mr-2">📝</span>
        <span class="text-sm font-bold text-slate-600 tracking-wide uppercase">AI 试卷处理器</span>
      </div>
      <h1 class="text-4xl md:text-5xl font-extrabold text-slate-900 tracking-tight mb-4">
        智能试卷<span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-violet-600">自动化处理</span>系统
      </h1>
      <p class="text-lg text-slate-500 max-w-2xl mx-auto mb-6">
        上传 PDF 试卷，自动进行切题、去重、数据分析重组。全流程可视化，让复杂的代码逻辑变得简单直观。
      </p>
      <RouterLink
        to="/wrong-notebook"
        class="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-amber-500 to-orange-500 text-white rounded-xl font-medium shadow-lg hover:shadow-xl transition-all hover:-translate-y-0.5"
      >
        <span class="text-xl">📚</span>
        错题本
      </RouterLink>
    </header>

    <!-- Main Content Area -->
    <ErrorBoundary>
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 mb-8">
        <!-- Left Column: Controls & Upload -->
        <div class="lg:col-span-4 space-y-6">
          <UploadZone />
          <LogTerminal />
        </div>

        <!-- Right Column: Workflow & Results -->
        <div class="lg:col-span-8 space-y-6">
          <PipelineView />
          <ResultGallery />
        </div>
      </div>

      <!-- Exam List Section -->
      <div class="mt-8">
        <ExamList />
      </div>
    </ErrorBoundary>
  </div>
</template>
