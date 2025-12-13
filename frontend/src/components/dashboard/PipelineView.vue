<script setup lang="ts">
import { useTaskStore } from '@/stores/useTaskStore'
import StepItem from './StepItem.vue'

const store = useTaskStore()
</script>

<template>
  <div class="glass-panel rounded-3xl p-8 relative overflow-hidden">
    <h3 class="text-xl font-bold mb-6 flex items-center">
      <span class="text-violet-500 mr-2 text-2xl">🔀</span>
      处理流程进度
    </h3>

    <div class="relative">
      <!-- Connecting Line Background -->
      <div class="absolute left-[23px] top-0 bottom-0 w-[2px] bg-slate-100 z-0"></div>
      <!-- Connecting Line Progress -->
      <div
        class="absolute left-[23px] top-0 w-[2px] bg-indigo-500 z-0 transition-all duration-1000 ease-in-out"
        :style="`height: ${store.progressPercent}%`"
      ></div>

      <div class="space-y-6 relative z-10">
        <StepItem
          v-for="step in store.steps"
          :key="step.index"
          :step="step"
        />
      </div>
    </div>
  </div>
</template>
