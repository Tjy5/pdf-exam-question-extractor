/**
 * Task Store - Pinia store for task state management
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import type { Step, LogEntry, ImageResult, TaskMode, StepStatus } from '@/services/types'

// Default step definitions
const createDefaultSteps = (): Step[] => [
  { index: 0, name: 'pdf_to_images', title: 'PDF 转图片', desc: '将 PDF 每一页转换为高分辨率图像', icon: 'ph-file-image', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
  { index: 1, name: 'extract_questions', title: 'OCR 识别', desc: '使用 PP-StructureV3 识别版面结构并缓存', icon: 'ph-scan', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
  { index: 2, name: 'analyze_data', title: '结构检测', desc: '分析题目边界，检测资料分析区域', icon: 'ph-tree-structure', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
  { index: 3, name: 'compose_long_image', title: '裁剪拼接', desc: '裁剪题目图片，跨页内容智能拼接', icon: 'ph-scissors', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
  { index: 4, name: 'collect_results', title: '结果汇总', desc: '验证输出完整性，生成汇总信息', icon: 'ph-package', status: 'pending', error: null, artifact_count: 0, progress: null, progress_text: null },
]

export const useTaskStore = defineStore('task', () => {
  // State
  const taskId = ref<string | null>(null)
  const file = ref<File | null>(null)
  const status = ref<'idle' | 'uploading' | 'processing' | 'paused' | 'completed' | 'error'>('idle')
  const mode = ref<TaskMode>('auto')
  const steps = ref<Step[]>(createDefaultSteps())
  const logs = ref<LogEntry[]>([])
  const results = ref<ImageResult[]>([])

  // Internal state
  const logCursor = ref(0)
  const eventSource = ref<EventSource | null>(null)
  const pollTimer = ref<number | null>(null)
  const seenLogIds = ref<Set<string>>(new Set())

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

  // Actions
  function addLog(message: string, type: LogEntry['type'] = 'default') {
    const now = new Date()
    const timeString = now.toTimeString().split(' ')[0]
    const id = `${Date.now()}-${Math.random().toString(36).substr(2, 8)}`

    logs.value.push({ id, time: timeString, message, type })

    // Keep log size manageable
    while (logs.value.length > 100) {
      const removed = logs.value.shift()
      if (removed) seenLogIds.value.delete(removed.id)
    }
  }

  function reset() {
    disconnectEventSource()
    stopPolling()

    taskId.value = null
    file.value = null
    status.value = 'idle'
    steps.value = createDefaultSteps()
    logs.value = []
    results.value = []
    logCursor.value = 0
    seenLogIds.value.clear()
  }

  async function uploadFile(selectedFile: File, selectedMode: TaskMode) {
    status.value = 'uploading'
    file.value = selectedFile
    mode.value = selectedMode

    try {
      addLog(`正在上传文件: ${selectedFile.name}`, 'info')

      const response = await api.upload(selectedFile, selectedMode)
      taskId.value = response.data.task_id

      // Apply inferred step states
      if (response.data.steps) {
        response.data.steps.forEach((s, idx) => {
          if (steps.value[idx]) {
            steps.value[idx].status = s.status
            steps.value[idx].artifact_count = s.artifact_count || 0
          }
        })
      }

      addLog('文件上传成功', 'success')

      if (selectedMode === 'auto') {
        await startProcessing()
      } else {
        status.value = 'paused'
        addLog('已上传，请手动执行各步骤', 'info')
      }
    } catch (error) {
      status.value = 'error'
      addLog(`上传失败: ${error}`, 'error')
    }
  }

  async function startProcessing() {
    if (!taskId.value) return

    status.value = 'processing'
    addLog('开始处理流程...', 'info')

    try {
      await api.startProcess(taskId.value)
      connectEventSource()
    } catch (error) {
      addLog(`启动处理失败: ${error}`, 'error')
      // Fallback to polling
      startPolling()
    }
  }

  async function startStep(stepIndex: number, runToEnd: boolean = false) {
    if (!taskId.value) return

    status.value = 'processing'
    steps.value[stepIndex].status = 'running'
    const action = runToEnd ? '从此步执行到最后' : '执行此步'
    addLog(`${action}: ${steps.value[stepIndex].title}`, 'info')

    try {
      await api.startStep(taskId.value, stepIndex, runToEnd)
      connectEventSource()
    } catch (error) {
      addLog(`步骤启动失败: ${error}`, 'error')
      steps.value[stepIndex].status = 'failed'
      status.value = 'paused'
    }
  }

  async function restartFromStep(stepIndex: number) {
    if (!taskId.value) return

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

      addLog(response.data.message || `已重置步骤 ${stepIndex + 1}`, 'info')

      if (mode.value === 'manual') {
        await startStep(stepIndex)
      }
    } catch (error) {
      addLog(`重置失败: ${error}`, 'error')
    }
  }

  function connectEventSource() {
    if (!taskId.value) return

    disconnectEventSource()

    const url = api.getStreamUrl(taskId.value)
    const es = new EventSource(url)

    es.addEventListener('step', (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.steps) {
          data.steps.forEach((s: any, idx: number) => {
            if (steps.value[idx]) {
              steps.value[idx].status = s.status
              steps.value[idx].error = s.error || null
              steps.value[idx].artifact_count = s.artifact_count || 0
              steps.value[idx].progress = s.progress ?? null
              steps.value[idx].progress_text = s.progress_text ?? null
            }
          })
        }
      } catch (err) {
        console.error('Failed to parse step event:', err)
      }
    })

    es.addEventListener('log', (e) => {
      try {
        const log = JSON.parse(e.data)
        if (!seenLogIds.value.has(log.id)) {
          seenLogIds.value.add(log.id)
          logs.value.push(log)
        }
      } catch (err) {
        console.error('Failed to parse log event:', err)
      }
    })

    es.addEventListener('done', (e) => {
      status.value = e.data === 'completed' ? 'completed' : 'error'
      disconnectEventSource()

      if (status.value === 'completed') {
        addLog('所有任务处理完成！', 'success')
        loadResults()
      } else {
        addLog('处理失败', 'error')
      }
    })

    es.onerror = () => {
      console.warn('SSE connection error, falling back to polling')
      disconnectEventSource()
      startPolling()
    }

    eventSource.value = es
  }

  function disconnectEventSource() {
    if (eventSource.value) {
      eventSource.value.close()
      eventSource.value = null
    }
  }

  function startPolling() {
    stopPolling()

    pollTimer.value = window.setInterval(async () => {
      await pollStatus()
    }, 2000)
  }

  function stopPolling() {
    if (pollTimer.value !== null) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
  }

  async function pollStatus() {
    if (!taskId.value) return

    try {
      const response = await api.getStatus(taskId.value, logCursor.value)
      const data = response.data

      // Update steps
      if (data.steps) {
        data.steps.forEach((s, idx) => {
          if (steps.value[idx]) {
            steps.value[idx].status = s.status as StepStatus
            steps.value[idx].error = s.error || null
            steps.value[idx].artifact_count = s.artifact_count || 0
            steps.value[idx].progress = s.progress ?? null
            steps.value[idx].progress_text = s.progress_text ?? null
          }
        })
      }

      // Append new logs
      if (data.logs?.length) {
        data.logs.forEach(log => {
          if (!seenLogIds.value.has(log.id)) {
            seenLogIds.value.add(log.id)
            logs.value.push(log)
          }
        })
        logCursor.value = data.total_logs
      }

      // Check completion
      if (data.status === 'completed') {
        status.value = 'completed'
        stopPolling()
        addLog('所有任务处理完成！', 'success')
        await loadResults()
      } else if (data.status === 'failed') {
        status.value = 'error'
        stopPolling()
        addLog(`处理失败: ${data.error}`, 'error')
      } else if (data.status === 'pending' && mode.value === 'manual') {
        // In manual mode, stop polling when step completes
        const hasRunning = steps.value.some(s => s.status === 'running')
        if (!hasRunning) {
          status.value = 'paused'
          stopPolling()
          addLog('步骤执行完成', 'success')
        }
      }
    } catch (error) {
      console.error('Polling error:', error)
    }
  }

  async function loadResults() {
    if (!taskId.value) return

    try {
      const response = await api.getResults(taskId.value)
      results.value = response.data.images.map(img => ({
        src: api.getImageUrl(taskId.value!, img.filename),
        name: img.name,
        path: img.path,
      }))
    } catch (error) {
      addLog(`加载结果失败: ${error}`, 'error')
    }
  }

  function downloadAll() {
    if (!taskId.value) return
    window.location.href = api.getDownloadUrl(taskId.value)
  }

  // Helper functions for step management
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

  return {
    // State
    taskId,
    file,
    status,
    mode,
    steps,
    logs,
    results,

    // Computed
    progressPercent,
    isBusy,
    currentStepIndex,

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
