<script setup lang="ts">
import { ref } from 'vue'
import { useTaskStore } from '@/stores/useTaskStore'
import { useDragDrop } from '@/composables/useDragDrop'

const store = useTaskStore()
const fileInput = ref<HTMLInputElement>()

const { isDragging, handleDragOver, handleDragLeave, handleDrop } = useDragDrop((file) => {
  store.uploadFile(file, store.mode)
})

function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files?.length) {
    store.uploadFile(target.files[0], store.mode)
  }
}

function handleClick() {
  fileInput.value?.click()
}
</script>

<template>
  <div class="glass-panel rounded-3xl p-6 transition-transform hover:scale-[1.02] duration-300">
    <h3 class="text-xl font-bold mb-4 flex items-center">
      <span class="text-rose-500 mr-2 text-2xl">📄</span>
      第一步: 上传文件
    </h3>

    <!-- Mode Selector -->
    <div class="mb-4 flex items-center justify-center gap-2 p-2 bg-slate-100 rounded-xl">
      <button
        @click="store.mode = 'auto'"
        class="flex-1 py-2 px-4 rounded-lg font-medium transition-all flex items-center justify-center gap-2"
        :class="store.mode === 'auto' ? 'bg-white shadow-sm text-indigo-600' : 'text-slate-500 hover:text-slate-700'"
      >
        <span>▶️</span>
        <span class="text-sm">自动模式</span>
      </button>
      <button
        @click="store.mode = 'manual'"
        class="flex-1 py-2 px-4 rounded-lg font-medium transition-all flex items-center justify-center gap-2"
        :class="store.mode === 'manual' ? 'bg-white shadow-sm text-indigo-600' : 'text-slate-500 hover:text-slate-700'"
      >
        <span>📋</span>
        <span class="text-sm">手动分步</span>
      </button>
    </div>

    <!-- Mode Description -->
    <div class="mb-4 text-xs text-slate-500 bg-blue-50 border border-blue-100 rounded-lg p-3">
      <span v-if="store.mode === 'auto'">
        <strong>自动模式:</strong> 一键完成全部5个处理步骤
      </span>
      <span v-else>
        <strong>手动分步:</strong> 您可以逐步执行并查看每步结果
      </span>
    </div>

    <!-- Drop Zone -->
    <div
      class="border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-colors group relative overflow-hidden"
      :class="isDragging ? 'border-indigo-500 bg-indigo-50' : 'border-indigo-200 hover:border-indigo-500 hover:bg-indigo-50/50'"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
      @drop="handleDrop"
      @click="handleClick"
    >
      <input
        ref="fileInput"
        type="file"
        accept=".pdf"
        class="hidden"
        @change="handleFileSelect"
      >

      <div v-if="!store.file" class="space-y-3">
        <div class="w-16 h-16 bg-indigo-100 text-indigo-600 rounded-full flex items-center justify-center mx-auto transition-transform group-hover:scale-110 duration-300">
          <span class="text-3xl">☁️</span>
        </div>
        <p class="text-slate-600 font-medium">点击或拖拽 PDF 文件到这里</p>
        <p class="text-xs text-slate-400">支持 .pdf 格式</p>
      </div>

      <div v-else class="space-y-3">
        <div class="w-16 h-16 bg-rose-100 text-rose-600 rounded-full flex items-center justify-center mx-auto">
          <span class="text-3xl">📄</span>
        </div>
        <p class="text-slate-800 font-bold truncate">{{ store.file.name }}</p>
        <button
          @click.stop="store.reset()"
          class="text-xs text-rose-500 hover:underline"
        >
          移除并重新上传
        </button>
      </div>
    </div>

    <!-- Action Button for Auto Mode -->
    <button
      v-if="store.mode === 'auto'"
      @click="store.startProcessing()"
      :disabled="!store.file || store.isBusy"
      class="w-full mt-6 py-4 rounded-xl font-bold text-white shadow-lg shadow-indigo-200 transition-all transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
      :class="store.isBusy ? 'bg-slate-400' : 'bg-gradient-to-r from-indigo-600 to-violet-600 hover:shadow-indigo-300 hover:-translate-y-1'"
    >
      <span v-if="!store.isBusy" class="flex items-center gap-2">
        ▶️ 一键自动处理
      </span>
      <span v-else class="flex items-center gap-2">
        ⏳ 处理中...
      </span>
    </button>

    <!-- Upload Button for Manual Mode -->
    <button
      v-else
      @click="store.uploadFile(store.file!, store.mode)"
      :disabled="!store.file || store.taskId !== null"
      class="w-full mt-6 py-4 rounded-xl font-bold text-white shadow-lg shadow-indigo-200 transition-all transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
      :class="store.taskId ? 'bg-emerald-500' : 'bg-gradient-to-r from-indigo-600 to-violet-600 hover:shadow-indigo-300 hover:-translate-y-1'"
    >
      <span v-if="!store.taskId" class="flex items-center gap-2">
        ⬆️ 上传文件
      </span>
      <span v-else class="flex items-center gap-2">
        ✅ 已上传，请执行步骤
      </span>
    </button>
  </div>
</template>
