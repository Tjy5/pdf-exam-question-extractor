<script setup lang="ts">
import { computed } from 'vue'
import { useTaskStore } from '@/stores/useTaskStore'
import type { Step } from '@/services/types'

const props = defineProps<{
  step: Step
}>()

const store = useTaskStore()

const displayStatus = computed(() => store.getStepDisplayStatus(props.step))
const statusText = computed(() => store.getStepStatusText(props.step))
const canStart = computed(() => store.canStartStep(props.step))

const iconClass = computed(() => {
  switch (displayStatus.value) {
    case 'running': return 'bg-indigo-600 border-indigo-100 text-white scale-110 shadow-indigo-200'
    case 'completed': return 'bg-emerald-500 border-emerald-100 text-white'
    case 'failed': return 'bg-rose-500 border-rose-100 text-white'
    default: return 'bg-white border-slate-100 text-slate-300'
  }
})

const titleClass = computed(() => {
  switch (displayStatus.value) {
    case 'running': return 'text-indigo-700'
    case 'completed': return 'text-emerald-700'
    case 'failed': return 'text-rose-700'
    default: return 'text-slate-400'
  }
})

const badgeClass = computed(() => {
  switch (displayStatus.value) {
    case 'running': return 'bg-indigo-100 text-indigo-700 animate-pulse'
    case 'completed': return 'bg-emerald-100 text-emerald-700'
    case 'failed': return 'bg-rose-100 text-rose-700'
    default: return 'bg-slate-100 text-slate-500'
  }
})

const cardClass = computed(() => {
  switch (displayStatus.value) {
    case 'running': return 'bg-white border-indigo-100 shadow-sm pl-4'
    case 'completed': return 'bg-white border-emerald-100'
    default: return ''
  }
})

const progressDisplayWidth = computed(() => {
  if (displayStatus.value === 'completed') return 100
  if (displayStatus.value === 'failed') return 100
  if (typeof props.step.progress === 'number' && !Number.isNaN(props.step.progress)) {
    return Math.min(100, Math.max(0, Math.round(props.step.progress * 100)))
  }
  if (displayStatus.value === 'running') return 30
  return 0
})

const progressBarColor = computed(() => {
  switch (displayStatus.value) {
    case 'failed': return 'bg-rose-400'
    case 'completed': return 'bg-emerald-500'
    case 'running': return 'bg-indigo-500'
    default: return 'bg-slate-200'
  }
})

const isIndeterminate = computed(() => {
  return displayStatus.value === 'running' && props.step.progress === null
})

const stepIcon = computed(() => {
  const icons: Record<string, string> = {
    'ph-file-image': '🖼️',
    'ph-scan': '🔍',
    'ph-tree-structure': '🧩',
    'ph-scissors': '✂️',
    'ph-package': '📦',
  }
  return icons[props.step.icon] || '📋'
})
</script>

<template>
  <div class="flex items-start gap-4 group">
    <!-- Icon Bubble -->
    <div
      class="w-12 h-12 rounded-full border-4 flex items-center justify-center transition-all duration-500 shadow-sm flex-shrink-0"
      :class="iconClass"
    >
      <span v-if="displayStatus === 'pending' || displayStatus === 'running'" class="text-xl">
        {{ stepIcon }}
      </span>
      <span v-else-if="displayStatus === 'completed'" class="text-xl">✅</span>
      <span v-else-if="displayStatus === 'failed'" class="text-xl">❌</span>
    </div>

    <!-- Text Content with Step Controls -->
    <div
      class="flex-1 bg-white/50 rounded-xl p-3 border border-transparent transition-all duration-300"
      :class="cardClass"
    >
      <div class="flex justify-between items-start mb-2">
        <div class="flex-1">
          <h4 class="font-bold" :class="titleClass">
            {{ step.title }}
          </h4>
          <p class="text-sm text-slate-500 leading-relaxed mt-1">
            {{ step.desc }}
          </p>
          <p v-if="step.progress_text" class="text-xs text-slate-500 mt-1">
            {{ step.progress_text }}
          </p>
          <div class="mt-2 h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500 ease-out"
              :class="[progressBarColor, isIndeterminate ? 'animate-pulse' : '']"
              :style="`width: ${progressDisplayWidth}%`"
            ></div>
          </div>
          <div v-if="displayStatus !== 'pending'" class="mt-1 text-xs text-slate-400 text-right">
            {{ progressDisplayWidth }}%
          </div>
        </div>
        <span
          class="text-xs font-medium px-2 py-0.5 rounded-full ml-2 flex-shrink-0"
          :class="badgeClass"
        >
          {{ statusText }}
        </span>
      </div>

      <!-- Manual Mode Step Controls -->
      <div v-if="store.mode === 'manual' && store.taskId" class="mt-3 flex flex-wrap gap-2">
        <!-- Start Single Step Button -->
        <button
          v-if="canStart"
          @click="store.startStep(step.index, false)"
          class="px-3 py-1.5 bg-indigo-500 hover:bg-indigo-600 text-white text-xs font-medium rounded-lg transition-colors flex items-center gap-1"
        >
          ▶️ 执行此步
        </button>

        <!-- Start From This Step to End Button -->
        <button
          v-if="canStart"
          @click="store.startStep(step.index, true)"
          class="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-medium rounded-lg transition-colors flex items-center gap-1"
        >
          ⏩ 从此步到最后
        </button>

        <!-- View Results Button -->
        <button
          v-if="displayStatus === 'completed'"
          class="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-medium rounded-lg transition-colors flex items-center gap-1"
        >
          👁️ 查看结果
        </button>

        <!-- Restart From This Step -->
        <button
          v-if="displayStatus === 'completed'"
          @click="store.restartFromStep(step.index)"
          class="px-3 py-1.5 bg-amber-100 hover:bg-amber-200 text-amber-800 text-xs font-medium rounded-lg transition-colors flex items-center gap-1"
        >
          🔄 从此步重跑
        </button>

        <!-- Retry Button for Failed Steps -->
        <button
          v-if="displayStatus === 'failed'"
          @click="store.startStep(step.index, false)"
          class="px-3 py-1.5 bg-rose-100 hover:bg-rose-200 text-rose-700 text-xs font-medium rounded-lg transition-colors flex items-center gap-1"
        >
          🔁 重试此步
        </button>

        <!-- Retry From This Step to End -->
        <button
          v-if="displayStatus === 'failed'"
          @click="store.startStep(step.index, true)"
          class="px-3 py-1.5 bg-rose-500 hover:bg-rose-600 text-white text-xs font-medium rounded-lg transition-colors flex items-center gap-1"
        >
          🔁 重试到最后
        </button>
      </div>

      <!-- Error Message -->
      <div
        v-if="step.error"
        class="mt-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2"
      >
        <div class="flex items-start gap-2">
          <span class="text-rose-500 flex-shrink-0">⚠️</span>
          <div class="min-w-0">
            <div class="font-medium text-rose-800 mb-1">执行失败</div>
            <div class="text-rose-600 break-words whitespace-pre-wrap">{{ step.error }}</div>
          </div>
        </div>
      </div>

      <!-- Artifact Count -->
      <div
        v-if="step.artifact_count > 0"
        class="mt-2 text-xs text-slate-500 flex items-center gap-1"
      >
        📁 已生成 <strong>{{ step.artifact_count }}</strong> 个文件
      </div>
    </div>
  </div>
</template>
