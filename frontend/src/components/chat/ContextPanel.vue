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
  <div class="h-full flex flex-col bg-white/80 backdrop-blur-md border-l border-slate-200/60">
    <div class="p-4 border-b border-slate-100 bg-slate-50/50">
      <h3 class="font-semibold text-slate-700 flex items-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.414.086l4 4a1 1 0 01.586 1.414V19a2 2 0 01-2 2z" />
        </svg>
        题目信息
      </h3>
    </div>

    <!-- 快捷导航按钮 -->
    <div v-if="context" class="px-4 py-3 border-b border-slate-100 bg-white/50">
      <div class="flex gap-2">
        <button
          @click="handleNavigate('prev')"
          :disabled="!canGoPrev"
          class="flex-1 px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200 text-slate-700 font-medium hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
          :class="{ 'hover:bg-slate-100': canGoPrev }"
        >
          ← 上一题
        </button>
        <button
          @click="handleNavigate('next')"
          :disabled="!canGoNext"
          class="flex-1 px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200 text-slate-700 font-medium hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
          :class="{ 'hover:bg-slate-100': canGoNext }"
        >
          下一题 →
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex-1 p-6 flex justify-center items-center">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div>
    </div>

    <div v-else-if="error" class="flex-1 p-6 flex justify-center items-center">
      <div class="text-center max-w-xs">
        <div class="text-rose-500 mb-2 font-medium">{{ error }}</div>
        <p class="text-sm text-slate-400 mb-4">题目内容加载失败</p>
        <div class="flex flex-col gap-2">
          <button
            type="button"
            class="w-full px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-medium transition-colors text-sm"
            @click="emit('retry')"
          >
            重试
          </button>
          <button
            type="button"
            class="w-full px-4 py-2 rounded-lg bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-medium transition-colors text-sm"
            @click="emit('continueWithoutContext')"
          >
            不加载题目继续聊天
          </button>
        </div>
      </div>
    </div>

    <div v-else-if="skipped" class="flex-1 p-6 flex justify-center items-center">
      <div class="text-center max-w-xs">
        <div class="text-slate-700 mb-2 font-medium">已跳过题目信息加载</div>
        <p class="text-sm text-slate-400 mb-4">你可以继续聊天；需要时可重新加载题目内容。</p>
        <button
          type="button"
          class="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-medium transition-colors text-sm"
          @click="emit('retry')"
        >
          加载题目内容
        </button>
      </div>
    </div>

    <div v-else-if="context" class="flex-1 overflow-y-auto p-4 space-y-4">
      <!-- 题目图片 -->
      <div class="relative group rounded-lg overflow-hidden border border-slate-200">
        <img
          :src="context.imageUrl"
          alt="题目图片"
          class="w-full h-auto object-cover cursor-zoom-in transition-transform duration-300 group-hover:scale-105"
          @click="emit('openImage', context.imageUrl)"
        />
        <div
          class="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors flex items-center justify-center pointer-events-none"
        >
          <span class="opacity-0 group-hover:opacity-100 text-white bg-black/50 px-3 py-1 rounded-full text-sm font-medium backdrop-blur-sm transition-opacity">
            点击放大
          </span>
        </div>
      </div>

      <!-- OCR文本 -->
      <div v-if="context.ocrText" class="bg-slate-50 p-3 rounded-lg text-slate-600 text-sm leading-relaxed border border-slate-100">
        <div class="flex items-center justify-between mb-2">
          <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider">题目文本 (OCR)</h4>
        </div>
        <div class="font-serif whitespace-pre-wrap">{{ context.ocrText }}</div>
      </div>

       <!-- 答案对比 -->
       <div class="space-y-3">
         <div v-if="context.correctAnswer">
           <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">正确答案</h4>
           <template v-if="isDataAnalysisBigQuestion && correctAnswerParts.length > 1">
             <div class="grid grid-cols-5 gap-2">
               <div
                 v-for="(ans, idx) in correctAnswerParts"
                 :key="idx"
                 class="rounded-lg bg-emerald-100 text-emerald-700 border border-emerald-200 p-2 flex flex-col items-center justify-center"
               >
                 <div class="text-[10px] leading-none opacity-80">{{ dataAnalysisSubStartNo ? dataAnalysisSubStartNo + idx : idx + 1 }}</div>
                 <div class="text-lg font-bold leading-none">{{ ans }}</div>
               </div>
             </div>
             <div class="text-xs text-slate-500 mt-2">
               资料分析（按 5 小题）标准答案
             </div>
           </template>
           <div v-else class="flex items-center gap-2">
             <div class="w-10 h-10 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-xl border border-emerald-200">
               {{ context.correctAnswer }}
             </div>
             <div class="flex-1 text-xs text-slate-500">
               标准答案
             </div>
           </div>
         </div>

         <div v-if="context.userAnswer">
           <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">你的答案</h4>
           <template v-if="isDataAnalysisBigQuestion && userAnswerParts.length > 1">
             <div class="grid grid-cols-5 gap-2">
               <div
                 v-for="(ans, idx) in userAnswerParts"
                 :key="idx"
                 class="rounded-lg border p-2 flex flex-col items-center justify-center"
                 :class="ans === correctAnswerParts[idx]
                   ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
                   : 'bg-rose-100 text-rose-700 border-rose-200'
                 "
               >
                 <div class="text-[10px] leading-none opacity-80">{{ dataAnalysisSubStartNo ? dataAnalysisSubStartNo + idx : idx + 1 }}</div>
                 <div class="text-lg font-bold leading-none">{{ ans }}</div>
               </div>
             </div>
             <div class="text-xs mt-2" :class="context.userAnswer === context.correctAnswer ? 'text-emerald-600' : 'text-rose-600'">
               {{ context.userAnswer === context.correctAnswer ? '全部小题回答正确' : '存在小题错误' }}
             </div>
           </template>
           <div v-else class="flex items-center gap-2">
             <div
               class="w-10 h-10 rounded-lg flex items-center justify-center font-bold text-xl border"
               :class="context.userAnswer === context.correctAnswer
                 ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
                 : 'bg-rose-100 text-rose-700 border-rose-200'
               "
             >
               {{ context.userAnswer }}
             </div>
             <div class="flex-1 text-xs" :class="context.userAnswer === context.correctAnswer ? 'text-emerald-600' : 'text-rose-600'">
               {{ context.userAnswer === context.correctAnswer ? '回答正确' : '回答错误' }}
             </div>
           </div>
         </div>
       </div>
     </div>

    <div v-else class="flex-1 p-6 flex flex-col justify-center items-center text-slate-400">
      <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mb-2 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.414.086l4 4a1 1 0 01.586 1.414V19a2 2 0 01-2 2z" />
      </svg>
      <p>选择题目查看详情</p>
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
</style>
