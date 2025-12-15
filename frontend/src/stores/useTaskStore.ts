/**
 * Task Store - Core task state management
 * Coordinates with useLogsStore, useConnectionStore, useResultsStore
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import type { Step, TaskMode, StepStatus } from '@/services/types'
import { useLogsStore } from './useLogsStore'
import { useConnectionStore } from './useConnectionStore'
import { useResultsStore } from './useResultsStore'

const createDefaultSteps = (): Step[] => [
  { index: 0, name: 'pdf_to_images', title: 'PDF 转图片', desc: '将 PDF 每一页转换为高分辨率图像', icon: 'ph-file-image', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
  { index: 1, name: 'extract_questions', title: 'OCR 识别', desc: '使用 PP-StructureV3 识别版面结构并缓存', icon: 'ph-scan', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
  { index: 2, name: 'analyze_data', title: '结构检测', desc: '分析题目边界，检测资料分析区域', icon: 'ph-tree-structure', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
  { index: 3, name: 'compose_long_image', title: '裁剪拼接', desc: '裁剪题目图片，跨页内容智能拼接', icon: 'ph-scissors', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
  { index: 4, name: 'collect_results', title: '结果汇总', desc: '验证输出完整性，生成汇总信息', icon: 'ph-package', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
]

export const useTaskStore = defineStore('task', () => {
  // Core state
  const taskId = ref<string | null>(null)
  const file = ref<File | null>(null)
  const status = ref<'idle' | 'uploading' | 'processing' | 'paused' | 'completed' | 'error'>('idle')
  const mode = ref<TaskMode>('auto')
  const steps = ref<Step[]>(createDefaultSteps())

  // Computed
  const progressPercent = computed(() => {
    if (!steps.value.length) return 0

    const sum = steps.value.reduce((acc, step) => {
      switch (step.status) {
        case 'completed':
        case 'skipped':
          return acc + 1
        case 'running':
          if (typeof step.progress === 'number' && !Number.isNaN(step.progress)) {
            return acc + Math.min(1, Math.max(0, step.progress))
          }
          return acc + 0.1
        case 'failed':
          return acc + 0.5
        default:
          return acc
      }
    }, 0)

    return (sum / steps.value.length) * 100
  })

  const isBusy = computed(() => ['uploading', 'processing'].includes(status.value))

  const currentStepIndex = computed(() => {
    return steps.value.findIndex(s => s.status === 'running')
  })

  // Sibling stores (lazy access to avoid circular deps)
  const getLogsStore = () => useLogsStore()
  const getConnectionStore = () => useConnectionStore()
  const getResultsStore = () => useResultsStore()

  // Step update handler
  function updateSteps(stepsData: any[]) {
    stepsData.forEach((s, idx) => {
      if (steps.value[idx]) {
        steps.value[idx].status = s.status as StepStatus
        steps.value[idx].error = s.error || null
        steps.value[idx].artifact_count = s.artifact_count || 0
        steps.value[idx].progress = s.progress ?? null
        steps.value[idx].progress_text = s.progress_text ?? null
      }
    })
  }

  // Connection handlers
  function createConnectionHandlers() {
    const logsStore = getLogsStore()
    const resultsStore = getResultsStore()

    return {
      onStep: (stepsData: any[]) => updateSteps(stepsData),
      onDone: (doneStatus: string) => {
        status.value = doneStatus === 'completed' ? 'completed' : 'error'
        if (status.value === 'completed') {
          logsStore.addLog('所有任务处理完成！', 'success')
          if (taskId.value) resultsStore.loadResults(taskId.value)
        } else {
          logsStore.addLog('处理失败', 'error')
        }
      },
      onFallbackToPolling: () => startPolling(),
    }
  }

  function createPollingHandlers() {
    const logsStore = getLogsStore()
    const resultsStore = getResultsStore()

    return {
      onStatus: (data: any) => {
        if (data.steps) updateSteps(data.steps)

        if (data.status === 'pending' && mode.value === 'manual') {
          const hasRunning = steps.value.some(s => s.status === 'running')
          if (!hasRunning) {
            status.value = 'paused'
            getConnectionStore().stopPolling()
            logsStore.addLog('步骤执行完成', 'success')
          }
        }
      },
      onComplete: async () => {
        status.value = 'completed'
        logsStore.addLog('所有任务处理完成！', 'success')
        if (taskId.value) await resultsStore.loadResults(taskId.value)
      },
      onError: (error: string) => {
        status.value = 'error'
        logsStore.addLog(`处理失败: ${error}`, 'error')
      },
    }
  }

  function startPolling() {
    if (!taskId.value) return
    getConnectionStore().startPolling(taskId.value, createPollingHandlers())
  }

  // Actions
  function reset() {
    getConnectionStore().reset()
    getLogsStore().reset()
    getResultsStore().reset()

    taskId.value = null
    file.value = null
    status.value = 'idle'
    steps.value = createDefaultSteps()
  }

  async function uploadFile(selectedFile: File, selectedMode: TaskMode) {
    const logsStore = getLogsStore()

    status.value = 'uploading'
    file.value = selectedFile
    mode.value = selectedMode

    try {
      logsStore.addLog(`正在上传文件: ${selectedFile.name}`, 'info')

      const response = await api.upload(selectedFile, selectedMode)
      taskId.value = response.data.task_id

      if (response.data.steps) {
        response.data.steps.forEach((s, idx) => {
          if (steps.value[idx]) {
            steps.value[idx].status = s.status
            steps.value[idx].artifact_count = s.artifact_count || 0
          }
        })
      }

      logsStore.addLog('文件上传成功', 'success')

      if (selectedMode === 'auto') {
        await startProcessing()
      } else {
        status.value = 'paused'
        logsStore.addLog('已上传，请手动执行各步骤', 'info')
      }
    } catch (error) {
      status.value = 'error'
      logsStore.addLog(`上传失败: ${error}`, 'error')
    }
  }

  async function startProcessing() {
    if (!taskId.value) return

    const logsStore = getLogsStore()
    const connectionStore = getConnectionStore()

    status.value = 'processing'
    logsStore.addLog('开始处理流程...', 'info')

    try {
      await api.startProcess(taskId.value)
      connectionStore.connectEventSource(taskId.value, createConnectionHandlers())
    } catch (error) {
      logsStore.addLog(`启动处理失败: ${error}`, 'error')
      startPolling()
    }
  }

  async function startStep(stepIndex: number, runToEnd: boolean = false) {
    if (!taskId.value) return

    const logsStore = getLogsStore()
    const connectionStore = getConnectionStore()

    status.value = 'processing'
    steps.value[stepIndex].status = 'running'
    const action = runToEnd ? '从此步执行到最后' : '执行此步'
    logsStore.addLog(`${action}: ${steps.value[stepIndex].title}`, 'info')

    try {
      await api.startStep(taskId.value, stepIndex, runToEnd)
      connectionStore.connectEventSource(taskId.value, createConnectionHandlers())
    } catch (error) {
      logsStore.addLog(`步骤启动失败: ${error}`, 'error')
      steps.value[stepIndex].status = 'failed'
      status.value = 'paused'
    }
  }

  async function restartFromStep(stepIndex: number) {
    if (!taskId.value) return

    const logsStore = getLogsStore()

    try {
      const response = await api.restartFromStep(taskId.value, stepIndex)

      if (response.data.steps) {
        response.data.steps.forEach((s: any, idx: number) => {
          if (steps.value[idx]) {
            steps.value[idx].status = s.status
            steps.value[idx].error = null
            steps.value[idx].artifact_count = 0
            steps.value[idx].progress = null
            steps.value[idx].progress_text = null
          }
        })
      }

      logsStore.addLog(response.data.message || `已重置步骤 ${stepIndex + 1}`, 'info')

      if (mode.value === 'manual') {
        await startStep(stepIndex)
      }
    } catch (error) {
      logsStore.addLog(`重置失败: ${error}`, 'error')
    }
  }

  // Helper functions
  function getStepDisplayStatus(step: Step): StepStatus {
    return step.status || 'pending'
  }

  function getStepStatusText(step: Step): string {
    const statusMap: Record<StepStatus, string> = {
      pending: '待执行',
      running: '进行中',
      completed: '已完成',
      failed: '失败',
      skipped: '已跳过',
    }
    return statusMap[step.status] || '待执行'
  }

  function canStartStep(step: Step): boolean {
    if (isBusy.value) return false
    if (step.status !== 'pending') return false

    const hasRunning = steps.value.some(s => s.status === 'running')
    if (hasRunning) return false

    if (mode.value !== 'manual' && step.index > 0) {
      const prevStep = steps.value[step.index - 1]
      if (prevStep.status !== 'completed') return false
    }

    return true
  }

  // Expose logs and results for backward compatibility
  const logs = computed(() => getLogsStore().logs)
  const results = computed(() => getResultsStore().results)

  function addLog(message: string, type: 'default' | 'info' | 'success' | 'error' = 'default') {
    getLogsStore().addLog(message, type)
  }

  function loadResults() {
    if (taskId.value) getResultsStore().loadResults(taskId.value)
  }

  function downloadAll() {
    if (taskId.value) getResultsStore().downloadAll(taskId.value)
  }

  return {
    // Core state
    taskId,
    file,
    status,
    mode,
    steps,

    // Computed
    progressPercent,
    isBusy,
    currentStepIndex,

    // Backward compatible accessors
    logs,
    results,

    // Actions
    addLog,
    reset,
    uploadFile,
    startProcessing,
    startStep,
    restartFromStep,
    loadResults,
    downloadAll,

    // Helpers
    getStepDisplayStatus,
    getStepStatusText,
    canStartStep,
  }
})
