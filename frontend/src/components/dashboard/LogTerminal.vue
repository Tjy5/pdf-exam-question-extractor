<script setup lang="ts">
import { useTaskStore } from '@/stores/useTaskStore'
import { useAutoScroll } from '@/composables/useAutoScroll'
import { computed } from 'vue'

const store = useTaskStore()
const { containerRef, handleScroll } = useAutoScroll(computed(() => store.logs))

function getLogStyle(type: string) {
  const styles: Record<string, { text: string; bg: string; border: string; icon: string }> = {
    success: {
      text: 'text-emerald-300',
      bg: 'bg-emerald-900/40',
      border: 'border-emerald-700/50',
      icon: '✓',
    },
    error: {
      text: 'text-rose-300',
      bg: 'bg-rose-900/50',
      border: 'border-rose-600/50',
      icon: '✗',
    },
    info: {
      text: 'text-blue-300',
      bg: 'bg-blue-900/30',
      border: 'border-blue-700/50',
      icon: 'ℹ',
    },
    default: {
      text: 'text-slate-300',
      bg: 'bg-slate-800/50',
      border: 'border-slate-700/30',
      icon: '•',
    },
  }
  return styles[type] || styles.default
}
</script>

<template>
  <div class="glass-panel rounded-3xl p-6 h-[400px] flex flex-col">
    <h3 class="text-lg font-bold mb-4 flex items-center text-slate-700">
      <span class="text-indigo-500 mr-2 text-2xl">💻</span>
      系统日志
    </h3>
    <div
      ref="containerRef"
      @scroll="handleScroll"
      class="flex-1 bg-slate-900 rounded-xl p-3 overflow-y-auto font-mono text-sm flex flex-col gap-1.5 shadow-inner"
    >
      <div
        v-if="store.logs.length === 0"
        class="text-slate-600 italic text-center mt-10"
      >
        等待任务开始...
      </div>
      <div
        v-for="log in store.logs"
        :key="log.id"
        class="flex items-start gap-2 px-2.5 py-1.5 rounded-md border transition-all duration-200"
        :class="[getLogStyle(log.type).bg, getLogStyle(log.type).border, log.type === 'error' ? 'ring-1 ring-rose-500/30' : '']"
      >
        <span class="w-4 text-center flex-shrink-0" :class="getLogStyle(log.type).text">
          {{ getLogStyle(log.type).icon }}
        </span>
        <span class="text-slate-500 flex-shrink-0 text-xs tabular-nums">{{ log.time }}</span>
        <span :class="getLogStyle(log.type).text" class="break-all">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>
