<script setup lang="ts">
import { useTaskStore } from '@/stores/useTaskStore'

const store = useTaskStore()

function previewImage(src: string) {
  window.open(src, '_blank')
}
</script>

<template>
  <div class="glass-panel rounded-3xl p-8 min-h-[300px]">
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-xl font-bold flex items-center">
        <span class="text-emerald-500 mr-2 text-2xl">🖼️</span>
        识别结果展示
        <span
          v-if="store.results.length > 0"
          class="ml-2 text-sm font-normal text-slate-500 bg-slate-100 px-2 py-1 rounded-md"
        >
          {{ store.results.length }} 道题目
        </span>
      </h3>
      <div v-if="store.results.length > 0" class="flex gap-2">
        <button
          @click="store.downloadAll()"
          class="text-sm bg-white border border-slate-200 hover:bg-slate-50 px-3 py-1.5 rounded-lg text-slate-600 transition-colors flex items-center gap-1"
        >
          ⬇️ 批量下载
        </button>
      </div>
    </div>

    <!-- Empty State -->
    <div
      v-if="store.results.length === 0"
      class="flex flex-col items-center justify-center py-12 text-slate-400 border-2 border-dashed border-slate-100 rounded-2xl bg-slate-50/50"
    >
      <span class="text-6xl mb-4 opacity-50">🖼️</span>
      <p class="text-lg font-medium">暂无结果</p>
      <p class="text-sm opacity-70">处理完成后图片将在这里显示</p>
    </div>

    <!-- Grid -->
    <div
      v-else
      class="grid grid-cols-2 md:grid-cols-3 gap-4"
    >
      <div
        v-for="(img, idx) in store.results"
        :key="idx"
        @click="previewImage(img.src)"
        class="group relative aspect-[3/4] bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden cursor-zoom-in hover:shadow-md transition-all"
      >
        <img
          :src="img.src"
          class="w-full h-full object-contain p-2"
          alt="Question"
        >
        <div class="absolute inset-0 bg-slate-900/0 group-hover:bg-slate-900/10 transition-colors duration-300"></div>
        <div class="absolute bottom-0 left-0 right-0 p-3 bg-white/90 backdrop-blur-sm translate-y-full group-hover:translate-y-0 transition-transform duration-300 border-t border-slate-100">
          <p class="text-xs font-bold text-slate-700 truncate">{{ img.name }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
