<script setup lang="ts">
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import UploadZone from '@/components/dashboard/UploadZone.vue'
import LogTerminal from '@/components/dashboard/LogTerminal.vue'
import PipelineView from '@/components/dashboard/PipelineView.vue'
import ResultGallery from '@/components/dashboard/ResultGallery.vue'
</script>

<template>
  <div class="bg-slate-50 text-slate-800 font-sans min-h-screen relative overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-700">
    <!-- Background Decoration -->
    <div class="fixed top-0 left-0 w-full h-full overflow-hidden -z-10 pointer-events-none">
      <div class="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-indigo-200/30 rounded-full mix-blend-multiply filter blur-3xl opacity-70 animate-float"></div>
      <div class="absolute top-[20%] right-[-10%] w-[35%] h-[35%] bg-violet-200/30 rounded-full mix-blend-multiply filter blur-3xl opacity-70 animate-float" style="animation-delay: 2s;"></div>
      <div class="absolute bottom-[-10%] left-[20%] w-[40%] h-[40%] bg-blue-200/30 rounded-full mix-blend-multiply filter blur-3xl opacity-70 animate-float" style="animation-delay: 4s;"></div>
    </div>

    <!-- Main App Container -->
    <div class="container mx-auto px-4 py-8 max-w-6xl">
      <!-- Header -->
      <header class="text-center mb-12 animate-float">
        <div class="inline-flex items-center justify-center p-3 bg-white rounded-2xl shadow-sm mb-4">
          <span class="text-3xl mr-2">📝</span>
          <span class="text-sm font-bold text-slate-600 tracking-wide uppercase">AI Exam Processor</span>
        </div>
        <h1 class="text-4xl md:text-5xl font-extrabold text-slate-900 tracking-tight mb-4">
          智能试卷<span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-violet-600">自动化处理</span>系统
        </h1>
        <p class="text-lg text-slate-500 max-w-2xl mx-auto">
          上传 PDF 试卷，自动进行切题、去重、数据分析重组。全流程可视化，让复杂的代码逻辑变得简单直观。
        </p>
      </header>

      <!-- Main Content Area -->
      <ErrorBoundary>
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-8">
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
      </ErrorBoundary>
    </div>
  </div>
</template>
