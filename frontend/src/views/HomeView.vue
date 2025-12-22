<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { useExamStore } from '@/stores/useExamStore'

const router = useRouter()
const examStore = useExamStore()

onMounted(() => {
  if (!examStore.loading && examStore.exams.length === 0) {
    examStore.fetchExams().catch(err => {
      console.error('Failed to fetch exams on mount:', err)
    })
  }
})

const recentExams = computed(() => {
  return [...examStore.exams]
    .sort((a, b) => Number(b.id) - Number(a.id))
    .slice(0, 5)
})

const hasExams = computed(() => examStore.exams.length > 0)
const isLoading = computed(() => examStore.loading)

function navigateToChat(examId: number) {
  router.push({ name: 'ExamChat', params: { examId: String(examId) }, query: { q: '1' } })
}
</script>

<template>
  <div class="min-h-screen flex flex-col items-center justify-center p-4 relative overflow-hidden bg-slate-50 selection:bg-indigo-100 selection:text-indigo-700">
    <!-- Background Decor -->
    <div class="absolute inset-0 overflow-hidden pointer-events-none z-0">
       <div class="absolute -top-[30%] -left-[10%] w-[70vw] h-[70vw] bg-indigo-200/30 rounded-full blur-[100px] animate-blob"></div>
       <div class="absolute top-[20%] -right-[10%] w-[60vw] h-[60vw] bg-violet-200/30 rounded-full blur-[100px] animate-blob animation-delay-2000"></div>
       <div class="absolute -bottom-[20%] left-[20%] w-[50vw] h-[50vw] bg-blue-200/30 rounded-full blur-[100px] animate-blob animation-delay-4000"></div>
    </div>

    <header class="text-center mb-16 relative z-10 animate-fade-in-down">
      <div class="inline-flex items-center justify-center p-4 bg-white/80 backdrop-blur-md rounded-2xl shadow-lg shadow-indigo-100/50 mb-8 ring-1 ring-white/60">
        <!-- Rocket Icon -->
        <svg class="w-10 h-10 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.59 14.37a6 6 0 01-5.84 7.38v-4.8m5.84-2.58a14.98 14.98 0 006.16-12.12A14.98 14.98 0 009.631 8.41m5.96 5.96a14.926 14.926 0 01-5.841 2.58m-.119-8.54a6 6 0 00-7.381 5.84h4.8m2.581-5.84a14.927 14.927 0 00-2.58 5.84m2.699 2.7c-.103.021-.207.041-.311.06a15.09 15.09 0 01-2.448-2.448 14.9 14.9 0 01.06-.312m-2.24 2.39a4.493 4.493 0 00-1.757 4.306 4.493 4.493 0 004.306-1.758M16.5 9a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z" />
        </svg>
      </div>
      <h1 class="text-5xl md:text-7xl font-black text-slate-900 tracking-tight mb-6 drop-shadow-sm">
        智能试卷<span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 via-violet-600 to-fuchsia-600">处理与答疑</span>
      </h1>
      <p class="text-xl text-slate-600 max-w-3xl mx-auto leading-relaxed font-light">
        从 PDF 自动化处理到 AI 深度答疑，体验前所未有的智能备考流。
      </p>
    </header>

    <div class="w-full max-w-5xl px-4 relative z-10">
      
      <!-- Recent Exams Section (List View) -->
      <div v-if="hasExams" class="bg-white/60 backdrop-blur-xl border border-white/60 rounded-3xl p-8 shadow-xl shadow-indigo-100/20 animate-fade-in-up">
        <div class="flex items-center justify-between mb-6">
          <h2 class="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <span class="text-indigo-600">🕒</span> 最近试卷
          </h2>
          <RouterLink to="/exams" class="text-sm font-medium text-slate-500 hover:text-indigo-600 transition-colors flex items-center gap-1">
            查看全部 <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
          </RouterLink>
        </div>
        
        <div class="grid gap-3">
          <div
            v-for="exam in recentExams"
            :key="exam.id"
            @click="navigateToChat(exam.id)"
            class="group cursor-pointer p-4 rounded-xl bg-white/50 border border-slate-200/50 hover:bg-white hover:border-indigo-200 hover:shadow-md transition-all duration-200 flex items-center justify-between"
          >
            <div class="flex items-center gap-4">
              <div class="w-10 h-10 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center font-bold text-lg group-hover:bg-indigo-600 group-hover:text-white transition-colors">
                {{ exam.id }}
              </div>
              <div>
                <h3 class="font-bold text-slate-700 group-hover:text-indigo-700 transition-colors">{{ exam.display_name || exam.exam_dir_name }}</h3>
                <p class="text-xs text-slate-400">点击进入答疑</p>
              </div>
            </div>
            <div class="flex items-center gap-3">
               <span class="text-xs font-medium px-2 py-1 rounded-md bg-slate-100 text-slate-500 group-hover:bg-indigo-50 group-hover:text-indigo-600 transition-colors">AI 答疑</span>
               <svg class="w-5 h-5 text-slate-300 group-hover:text-indigo-500 transform group-hover:translate-x-1 transition-all" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                 <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
               </svg>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else class="text-center py-12 animate-fade-in-up">
        <div class="inline-flex items-center justify-center w-20 h-20 bg-indigo-50 text-indigo-200 rounded-full mb-6">
           <svg class="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor">
             <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
           </svg>
        </div>
        <h3 class="text-xl font-bold text-slate-700 mb-2">开始您的第一个任务</h3>
        <p class="text-slate-500 mb-8 max-w-md mx-auto">暂无试卷记录。请点击上方导航栏的 "试卷处理" 或下方按钮开始上传。</p>
        <RouterLink to="/dashboard" class="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 text-white rounded-xl font-medium shadow-lg hover:bg-indigo-700 hover:shadow-indigo-500/30 transition-all hover:-translate-y-0.5">
           <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
             <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
           </svg>
           上传新试卷
        </RouterLink>
      </div>

    </div>
  </div>
</template>

<style scoped>
.font-display {
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  letter-spacing: -0.025em;
}

@keyframes blob {
  0% { transform: translate(0px, 0px) scale(1); }
  33% { transform: translate(30px, -50px) scale(1.1); }
  66% { transform: translate(-20px, 20px) scale(0.9); }
  100% { transform: translate(0px, 0px) scale(1); }
}

.animate-blob {
  animation: blob 7s infinite;
}

.animation-delay-2000 {
  animation-delay: 2s;
}

.animation-delay-4000 {
  animation-delay: 4s;
}

@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translate3d(0, -20px, 0);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0);
  }
}

.animate-fade-in-down {
  animation: fadeInDown 0.8s ease-out;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translate3d(0, 20px, 0);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0);
  }
}

.animate-fade-in-up {
  animation: fadeInUp 0.8s ease-out backwards;
}
</style>
