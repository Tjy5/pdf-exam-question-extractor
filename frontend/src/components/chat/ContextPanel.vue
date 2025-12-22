<script setup lang="ts">
import { computed } from 'vue'
import type { QuestionContext } from '@/stores/useChatStore'

const props = defineProps<{
  context: QuestionContext | null
  loading: boolean
  error: string | null
  skipped?: boolean
  totalQuestions?: number
}>()

const emit = defineEmits<{
  (e: 'openImage', src: string): void
  (e: 'navigate', direction: 'prev' | 'next'): void
  (e: 'retry'): void
  (e: 'continueWithoutContext'): void
}>()

const canGoPrev = computed(() => {
  return props.context !== null && props.context.questionNo > 1
})

const canGoNext = computed(() => {
  if (!props.context || !props.totalQuestions) return false
  return props.context.questionNo < props.totalQuestions
})

function splitDataAnalysisAnswer(answer: string | undefined): string[] {
  if (!answer) return []
  const letters = answer.toUpperCase().match(/[A-E]/g)
  return Array.isArray(letters) ? letters : []
}

const isDataAnalysisBigQuestion = computed(() => {
  return !!props.context && props.context.questionNo > 1000
})

const correctAnswerParts = computed(() => {
  if (!isDataAnalysisBigQuestion.value) return []
  return splitDataAnalysisAnswer(props.context?.correctAnswer)
})

const userAnswerParts = computed(() => {
  if (!isDataAnalysisBigQuestion.value) return []
  return splitDataAnalysisAnswer(props.context?.userAnswer)
})

const dataAnalysisSubStartNo = computed(() => {
  if (!props.context || !isDataAnalysisBigQuestion.value) return null
  const order = props.context.questionNo - 1000
  if (!Number.isFinite(order) || order <= 0) return null
  return 111 + (order - 1) * 5
})

function handleNavigate(direction: 'prev' | 'next') {
  emit('navigate', direction)
}
</script>

<template>
  <div class="h-full flex flex-col bg-transparent font-sans">
    <div class="p-4 shrink-0 bg-transparent flex items-center justify-between">
      <h3 class="font-bold text-slate-800 flex items-center text-lg">
        <span class="w-8 h-8 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center mr-2 ring-1 ring-indigo-50">
           <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.414.086l4 4a1 1 0 01.586 1.414V19a2 2 0 01-2 2z" />
          </svg>
        </span>
        题目详情
      </h3>
    </div>

    <!-- 快捷导航按钮 -->
    <div v-if="context" class="px-4 pb-4 shrink-0">
      <div class="flex gap-2 bg-slate-100/50 p-1 rounded-xl">
        <button
          @click="handleNavigate('prev')"
          :disabled="!canGoPrev"
          class="flex-1 px-3 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1 group"
          :class="!canGoPrev
            ? 'text-slate-300 cursor-not-allowed' 
            : 'bg-white text-slate-700 shadow-sm hover:text-indigo-600 hover:shadow-md ring-1 ring-black/5'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 transition-transform group-hover:-translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          上一题
        </button>
        <button
          @click="handleNavigate('next')"
          :disabled="!canGoNext"
          class="flex-1 px-3 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1 group"
           :class="!canGoNext
            ? 'text-slate-300 cursor-not-allowed' 
            : 'bg-white text-slate-700 shadow-sm hover:text-indigo-600 hover:shadow-md ring-1 ring-black/5'"
        >
          下一题
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
          </svg>
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex-1 p-6 flex flex-col justify-center items-center">
      <div class="relative w-12 h-12 mb-4">
        <div class="absolute inset-0 border-4 border-slate-100 rounded-full"></div>
        <div class="absolute inset-0 border-4 border-indigo-500 rounded-full border-t-transparent animate-spin"></div>
      </div>
      <p class="text-slate-400 text-sm font-medium animate-pulse">正在加载题目...</p>
    </div>

    <div v-else-if="error" class="flex-1 p-8 flex flex-col justify-center items-center text-center">
      <div class="w-16 h-16 bg-rose-50 rounded-2xl flex items-center justify-center mb-4 text-3xl">⚠️</div>
      <div class="text-rose-600 mb-2 font-bold">{{ error }}</div>
      <p class="text-sm text-slate-400 mb-6 max-w-[200px]">题目内容加载出了点问题</p>
      
      <div class="flex flex-col gap-3 w-full max-w-xs">
        <button
          type="button"
          class="w-full px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white font-bold transition-all shadow-lg shadow-indigo-200"
          @click="emit('retry')"
        >
          重试加载
        </button>
        <button
          type="button"
          class="w-full px-4 py-2.5 rounded-xl bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 font-medium transition-colors text-sm"
          @click="emit('continueWithoutContext')"
        >
          暂时跳过
        </button>
      </div>
    </div>

    <div v-else-if="skipped" class="flex-1 p-8 flex flex-col justify-center items-center text-center">
      <div class="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mb-4 text-3xl opacity-50">🙈</div>
      <div class="text-slate-700 mb-2 font-bold">已跳过题目</div>
      <p class="text-sm text-slate-400 mb-6 max-w-[200px]">你可以继续与 AI 对话，需要时可重新加载。</p>
      <button
        type="button"
        class="px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold transition-all shadow-lg shadow-indigo-200"
        @click="emit('retry')"
      >
        加载题目内容
      </button>
    </div>

    <div v-else-if="context" class="flex-1 overflow-y-auto px-4 pb-6 space-y-6 scroll-smooth">
      <!-- 题目图片 -->
      <div class="relative group rounded-2xl overflow-hidden shadow-sm ring-1 ring-slate-900/5 bg-white">
        <img
          :src="context.imageUrl"
          alt="题目图片"
          class="w-full h-auto object-contain bg-slate-50 min-h-[100px] cursor-zoom-in transition-transform duration-500 group-hover:scale-105"
          @click="emit('openImage', context.imageUrl)"
        />
        <div
          class="absolute inset-0 bg-indigo-900/0 group-hover:bg-indigo-900/10 transition-colors flex items-center justify-center pointer-events-none"
        >
          <span class="opacity-0 group-hover:opacity-100 translate-y-2 group-hover:translate-y-0 text-white bg-black/60 px-4 py-1.5 rounded-full text-sm font-bold backdrop-blur-md transition-all duration-300 shadow-xl">
            点击放大查看
          </span>
        </div>
      </div>

      <!-- OCR文本 -->
      <div v-if="context.ocrText" class="bg-white/60 p-5 rounded-2xl border border-white shadow-sm ring-1 ring-slate-200/50">
        <div class="flex items-center gap-2 mb-3">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-indigo-500" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clip-rule="evenodd" />
          </svg>
          <h4 class="text-xs font-bold text-slate-500 uppercase tracking-wider">OCR 识别文本</h4>
        </div>
        <div class="text-slate-600 text-sm leading-relaxed whitespace-pre-wrap font-serif">{{ context.ocrText }}</div>
      </div>

       <!-- 答案对比 -->
       <div class="bg-white/60 rounded-2xl border border-white shadow-sm ring-1 ring-slate-200/50 p-5 space-y-5">
         <div v-if="context.correctAnswer">
           <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1">
             <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
             正确答案
           </h4>
           <template v-if="isDataAnalysisBigQuestion && correctAnswerParts.length > 1">
             <div class="grid grid-cols-5 gap-2">
               <div
                 v-for="(ans, idx) in correctAnswerParts"
                 :key="idx"
                 class="aspect-square rounded-xl bg-emerald-50 text-emerald-600 border border-emerald-100 flex flex-col items-center justify-center transition-colors hover:bg-emerald-100"
               >
                 <div class="text-[10px] uppercase font-bold text-emerald-400 mb-0.5">{{ dataAnalysisSubStartNo ? dataAnalysisSubStartNo + idx : idx + 1 }}</div>
                 <div class="text-lg font-bold leading-none">{{ ans }}</div>
               </div>
             </div>
             <div class="text-xs text-slate-400 mt-2 text-center bg-slate-50 rounded-lg py-1">
               此题为资料分析题，包含 5 小题
             </div>
           </template>
           <div v-else class="flex items-center gap-3">
             <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-50 to-teal-50 text-emerald-600 flex items-center justify-center font-bold text-2xl shadow-inner border border-emerald-100">
               {{ context.correctAnswer }}
             </div>
             <div class="flex-1">
                <div class="text-sm font-bold text-slate-700">标准答案</div>
                <div class="text-xs text-slate-400">Answer Key</div>
             </div>
           </div>
         </div>

         <div v-if="context.userAnswer" class="pt-4 border-t border-slate-100">
           <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1">
             <span class="w-1.5 h-1.5 rounded-full bg-indigo-500"></span>
             你的答案
           </h4>
           <template v-if="isDataAnalysisBigQuestion && userAnswerParts.length > 1">
             <div class="grid grid-cols-5 gap-2">
               <div
                 v-for="(ans, idx) in userAnswerParts"
                 :key="idx"
                 class="aspect-square rounded-xl border flex flex-col items-center justify-center transition-all"
                 :class="ans === correctAnswerParts[idx]
                   ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                   : 'bg-rose-50 text-rose-600 border-rose-100'
                 "
               >
                 <div class="text-[10px] uppercase font-bold mb-0.5 opacity-60">{{ dataAnalysisSubStartNo ? dataAnalysisSubStartNo + idx : idx + 1 }}</div>
                 <div class="text-lg font-bold leading-none">{{ ans }}</div>
               </div>
             </div>
             <div class="text-xs mt-2 text-center font-medium py-1 rounded-lg" :class="context.userAnswer === context.correctAnswer ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
               {{ context.userAnswer === context.correctAnswer ? '🎉 全部正确' : '⚠️ 存在错误' }}
             </div>
           </template>
           <div v-else class="flex items-center gap-3">
             <div
               class="w-14 h-14 rounded-2xl flex items-center justify-center font-bold text-2xl shadow-inner border"
               :class="context.userAnswer === context.correctAnswer
                 ? 'bg-gradient-to-br from-emerald-50 to-teal-50 text-emerald-600 border-emerald-100'
                 : 'bg-gradient-to-br from-rose-50 to-orange-50 text-rose-600 border-rose-100'
               "
             >
               {{ context.userAnswer }}
             </div>
             <div class="flex-1">
               <div class="text-sm font-bold text-slate-700">用户作答</div>
               <div class="text-xs font-medium" :class="context.userAnswer === context.correctAnswer ? 'text-emerald-500' : 'text-rose-500'">
                 {{ context.userAnswer === context.correctAnswer ? '回答正确' : '回答错误' }}
               </div>
             </div>
           </div>
         </div>
       </div>
    </div>

    <div v-else class="flex-1 p-6 flex flex-col justify-center items-center text-slate-400 text-center">
      <div class="w-20 h-20 bg-slate-100 rounded-full flex items-center justify-center mb-4 opacity-50">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122" />
        </svg>
      </div>
      <p class="font-medium text-slate-500 mb-1">暂无选中题目</p>
      <p class="text-sm text-slate-400">请从左侧列表选择一道题目开始</p>
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
  background-color: #e2e8f0;
  border-radius: 20px;
}
div::-webkit-scrollbar-thumb:hover {
  background-color: #cbd5e1;
}
</style>
