<script setup lang="ts">
import { ref } from 'vue'
import { useExamStore } from '@/stores/useExamStore'

const props = defineProps<{
  examId: number
  examName: string
}>()

const emit = defineEmits<{
  close: []
  success: [result: any]
}>()

const examStore = useExamStore()
const selectedFile = ref<File | null>(null)
const dragOver = ref(false)
const importing = ref(false)
const result = ref<any>(null)
const errorMessage = ref<string | null>(null)

function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    selectedFile.value = target.files[0]
  }
}

function handleDrop(event: DragEvent) {
  dragOver.value = false
  if (event.dataTransfer?.files && event.dataTransfer.files.length > 0) {
    selectedFile.value = event.dataTransfer.files[0]
  }
}

function handleDragOver(event: DragEvent) {
  event.preventDefault()
  dragOver.value = true
}

function handleDragLeave() {
  dragOver.value = false
}

async function handleImport() {
  if (!selectedFile.value) {
    errorMessage.value = '请先选择文件'
    return
  }

  // 检查文件类型
  const fileName = selectedFile.value.name.toLowerCase()
  if (!fileName.endsWith('.json') && !fileName.endsWith('.csv') && !fileName.endsWith('.pdf')) {
    errorMessage.value = '只支持 JSON、CSV 和 PDF 格式文件'
    return
  }

  importing.value = true
  errorMessage.value = null
  result.value = null

  try {
    const importResult = await examStore.importAnswers(props.examId, selectedFile.value)
    result.value = importResult

    if (importResult.imported > 0) {
      emit('success', importResult)

      // 3秒后自动关闭
      setTimeout(() => {
        emit('close')
      }, 3000)
    }
  } catch (err: any) {
    errorMessage.value = err.message || '导入失败'
  } finally {
    importing.value = false
  }
}

function cancel() {
  emit('close')
}
</script>

<template>
  <!-- 遮罩层 -->
  <div
    class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
    @click.self="cancel"
  >
    <!-- 对话框 -->
    <div class="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 animate-float">
      <!-- 标题 -->
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-slate-800 flex items-center">
          <span class="text-indigo-500 mr-2">📥</span>
          导入答案
        </h2>
        <button
          @click="cancel"
          class="text-slate-400 hover:text-slate-600 transition-colors"
        >
          ✕
        </button>
      </div>

      <!-- 试卷名称 -->
      <div class="mb-4 p-3 bg-slate-50 rounded-lg">
        <p class="text-sm text-slate-600">试卷：<span class="font-medium text-slate-800">{{ examName }}</span></p>
      </div>

      <!-- 文件上传区域 -->
      <div
        v-if="!result"
        class="mb-6 border-2 border-dashed rounded-xl p-8 text-center transition-colors"
        :class="dragOver ? 'border-indigo-500 bg-indigo-50' : 'border-slate-300'"
        @drop.prevent="handleDrop"
        @dragover.prevent="handleDragOver"
        @dragleave="handleDragLeave"
      >
        <div v-if="!selectedFile">
          <div class="text-6xl mb-4">📄</div>
          <p class="text-slate-600 mb-2">拖拽文件到此处，或点击选择文件</p>
          <p class="text-sm text-slate-400 mb-4">支持 JSON、CSV、PDF 格式</p>
          <input
            type="file"
            accept=".json,.csv,.pdf"
            class="hidden"
            id="file-input"
            @change="handleFileSelect"
          />
          <label
            for="file-input"
            class="inline-block px-6 py-2 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg font-medium cursor-pointer transition-colors"
          >
            选择文件
          </label>
        </div>

        <div v-else class="flex items-center justify-between bg-white rounded-lg p-4">
          <div class="flex items-center gap-3">
            <span class="text-3xl">📄</span>
            <div class="text-left">
              <p class="font-medium text-slate-800">{{ selectedFile.name }}</p>
              <p class="text-sm text-slate-500">{{ (selectedFile.size / 1024).toFixed(2) }} KB</p>
            </div>
          </div>
          <button
            @click="selectedFile = null"
            class="text-red-500 hover:text-red-700 font-medium"
          >
            删除
          </button>
        </div>
      </div>

      <!-- 导入结果 -->
      <div v-if="result" class="mb-6">
        <div class="bg-green-50 border border-green-200 rounded-lg p-4">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-2xl">✅</span>
            <h3 class="text-lg font-bold text-green-700">导入成功</h3>
          </div>
          <div class="text-sm text-green-700 space-y-1">
            <p>✓ 成功导入 {{ result.imported }} 条答案</p>
            <p v-if="result.skipped > 0">⊙ 跳过 {{ result.skipped }} 条</p>
            <p v-if="result.errors && result.errors.length > 0" class="text-orange-600">
              ⚠️ {{ result.errors.length }} 条错误
            </p>
          </div>
          <div v-if="result.errors && result.errors.length > 0" class="mt-3 text-xs text-slate-600 max-h-32 overflow-y-auto">
            <p v-for="(error, idx) in result.errors" :key="idx" class="mb-1">
              • {{ error }}
            </p>
          </div>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="errorMessage" class="mb-6 bg-red-50 border border-red-200 rounded-lg p-4 text-red-600">
        ❌ {{ errorMessage }}
      </div>

      <!-- 格式说明 -->
      <div v-if="!result" class="mb-6 bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm">
        <p class="font-medium text-blue-800 mb-2">📖 格式说明：</p>
        <div class="text-blue-700 space-y-2">
          <div>
            <p class="font-medium">JSON 格式：</p>
            <code class="block bg-white px-2 py-1 rounded mt-1 text-xs">
              [{"question_no": 1, "answer": "A"}, ...]
            </code>
          </div>
          <div>
            <p class="font-medium">CSV 格式：</p>
            <code class="block bg-white px-2 py-1 rounded mt-1 text-xs">
              question_no,answer<br>1,A<br>2,C
            </code>
          </div>
          <div>
            <p class="font-medium">PDF 格式：</p>
            <p class="text-xs mt-1">答案 PDF 文件，如 "1--5 DDCCA"</p>
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex gap-3">
        <button
          v-if="!result"
          @click="handleImport"
          :disabled="!selectedFile || importing"
          class="flex-1 px-6 py-3 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {{ importing ? '导入中...' : '开始导入' }}
        </button>
        <button
          @click="cancel"
          class="flex-1 px-6 py-3 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg font-medium transition-colors"
        >
          {{ result ? '完成' : '取消' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

.animate-float {
  animation: float 0.3s ease-out;
}
</style>
