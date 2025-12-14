<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'

const error = ref<Error | null>(null)

onErrorCaptured((err: unknown) => {
  const normalized = err instanceof Error ? err : new Error(String(err))
  console.error('[ErrorBoundary]', normalized)
  error.value = normalized
  return false
})

function retry() {
  error.value = null
}
</script>

<template>
  <div v-if="error" class="glass-panel rounded-3xl p-8 text-center">
    <div class="text-6xl mb-4 opacity-50">⚠️</div>
    <h2 class="text-xl font-bold text-rose-600 mb-2">出错了</h2>
    <p class="text-slate-500 mb-6">{{ error.message }}</p>
    <button
      @click="retry"
      class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg transition-colors"
    >
      重试
    </button>
  </div>
  <slot v-else />
</template>
