<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/services/api'

const emit = defineEmits<{
  close: []
  success: []
}>()

const directories = ref<string[]>([])
const selectedDir = ref<string>('')
const loading = ref(false)
const importing = ref(false)
const errorMessage = ref<string | null>(null)
const result = ref<any>(null)
const dryRun = ref(false)
const overwrite = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const response = await api.listLocalExamDirectories()
    directories.value = response.data.directories
  } catch (err: any) {
    errorMessage.value = err.message || '加载目录失败'
  } finally {
    loading.value = false
  }
})

async function handleImport() {
  if (!selectedDir.value) return

  importing.value = true
  errorMessage.value = null
  result.value = null

  try {
    const response = await api.importLocalExam({
      exam_dir_name: selectedDir.value,
      dry_run: dryRun.value,
      overwrite: overwrite.value
    })
    result.value = response.data

    if (!dryRun.value && response.data && !response.data.errors?.length && !response.data.warnings?.length) {
      emit('success')
      setTimeout(() => {
        emit('close')
      }, 2000)
    } else if (!dryRun.value && response.data && !response.data.errors?.length) {
      // 有警告但无错误，仍然触发success但不自动关闭
      emit('success')
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
  <div
    class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
    @click.self="cancel"
  >
    <div class="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 animate-fade-in">
      <!-- Header -->
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-slate-800 flex items-center">
          <span class="text-indigo-500 mr-2">📂</span>
          导入本地试卷
        </h2>
        <button
          @click="cancel"
          class="text-slate-400 hover:text-slate-600 transition-colors"
        >
          ✕
        </button>
      </div>

      <!-- Content -->
      <div v-if="loading" class="py-8 text-center text-slate-500">
        加载目录中...
      </div>

      <div v-else-if="!result" class="space-y-6">
        <!-- Directory Selection -->
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-2">
            选择试卷目录 (pdf_images/)
          </label>
          <select
            v-model="selectedDir"
            class="w-full rounded-lg border-slate-300 focus:border-indigo-500 focus:ring-indigo-500"
            size="5"
          >
            <option v-for="dir in directories" :key="dir" :value="dir" class="py-1 px-2">
              {{ dir }}
            </option>
          </select>
          <p class="mt-1 text-xs text-slate-500" v-if="directories.length === 0">
            没有找到可用的本地试卷目录
          </p>
        </div>

        <!-- Options -->
        <div class="flex flex-col gap-2">
          <label class="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
            <input type="checkbox" v-model="dryRun" class="rounded text-indigo-600 focus:ring-indigo-500">
            <span>仅模拟运行 (Dry Run)</span>
          </label>
          <label class="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
            <input type="checkbox" v-model="overwrite" class="rounded text-indigo-600 focus:ring-indigo-500">
            <span>覆盖已存在的试卷</span>
          </label>
        </div>
      </div>

      <!-- Result Display -->
      <div v-if="result" class="mb-6">
        <div
          class="rounded-lg p-4 border"
          :class="result.errors?.length ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'"
        >
          <div class="flex items-center gap-2 mb-2">
            <span class="text-2xl">{{ result.errors?.length ? '❌' : '✅' }}</span>
            <h3 class="text-lg font-bold" :class="result.errors?.length ? 'text-red-700' : 'text-green-700'">
              {{ result.errors?.length ? '导入失败' : (dryRun ? '模拟成功' : '导入成功') }}
            </h3>
          </div>

          <div class="text-sm space-y-1" :class="result.errors?.length ? 'text-red-700' : 'text-green-700'">
            <p>试卷名称: {{ result.display_name }}</p>
            <p>题目数量: {{ result.question_count }}</p>
            <p v-if="result.data_analysis_count > 0">资料分析: {{ result.data_analysis_count }} 题</p>
            <p v-if="!dryRun">导入成功: {{ result.imported }} 题</p>
            <p v-if="!dryRun && result.skipped > 0">跳过: {{ result.skipped }} 题</p>

            <div v-if="result.warnings?.length" class="mt-2 text-xs opacity-75">
              <p class="font-medium">警告:</p>
              <ul class="list-disc list-inside">
                <li v-for="(warn, idx) in result.warnings.slice(0, 3)" :key="idx">{{ warn }}</li>
              </ul>
            </div>

            <div v-if="result.errors?.length" class="mt-2">
              <p class="font-medium">错误:</p>
              <ul class="list-disc list-inside">
                <li v-for="(err, idx) in result.errors.slice(0, 3)" :key="idx">{{ err }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="errorMessage" class="mb-6 bg-red-50 border border-red-200 rounded-lg p-4 text-red-600">
        ❌ {{ errorMessage }}
      </div>

      <!-- Actions -->
      <div class="flex gap-3 mt-6">
        <button
          v-if="!result || dryRun || result.errors?.length"
          @click="handleImport"
          :disabled="!selectedDir || importing"
          class="flex-1 px-6 py-3 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {{ importing ? '处理中...' : (dryRun ? '开始模拟' : '开始导入') }}
        </button>
        <button
          @click="cancel"
          class="flex-1 px-6 py-3 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg font-medium transition-colors"
        >
          {{ (result && !dryRun && !result.errors?.length) ? '完成' : '取消' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes fadeIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.animate-fade-in {
  animation: fadeIn 0.2s ease-out;
}
</style>
