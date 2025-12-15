/**
 * Results Store - Result images management
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'
import type { ImageResult } from '@/services/types'
import { useLogsStore } from './useLogsStore'

export const useResultsStore = defineStore('results', () => {
  const results = ref<ImageResult[]>([])

  async function loadResults(taskId: string) {
    const logsStore = useLogsStore()

    try {
      const response = await api.getResults(taskId)
      results.value = response.data.images.map(img => ({
        src: api.getImageUrl(taskId, img.filename),
        name: img.name,
        path: img.path,
      }))
    } catch (error) {
      logsStore.addLog(`加载结果失败: ${error}`, 'error')
    }
  }

  function downloadAll(taskId: string) {
    window.location.href = api.getDownloadUrl(taskId)
  }

  function reset() {
    results.value = []
  }

  return {
    results,
    loadResults,
    downloadAll,
    reset,
  }
})
