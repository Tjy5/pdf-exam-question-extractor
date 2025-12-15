/**
 * Logs Store - Log management
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LogEntry } from '@/services/types'

const MAX_LOGS = 100

export const useLogsStore = defineStore('logs', () => {
  const logs = ref<LogEntry[]>([])
  const cursor = ref(0)
  const seenIds = ref<Set<string>>(new Set())

  function addLog(message: string, type: LogEntry['type'] = 'default') {
    const now = new Date()
    const timeString = now.toTimeString().split(' ')[0]
    const id = `${Date.now()}-${Math.random().toString(36).substr(2, 8)}`

    logs.value.push({ id, time: timeString, message, type })

    while (logs.value.length > MAX_LOGS) {
      const removed = logs.value.shift()
      if (removed) seenIds.value.delete(removed.id)
    }
  }

  function appendLog(log: LogEntry) {
    if (!seenIds.value.has(log.id)) {
      seenIds.value.add(log.id)
      logs.value.push(log)
    }
  }

  function appendLogs(newLogs: LogEntry[]) {
    newLogs.forEach(log => appendLog(log))
  }

  function updateCursor(total: number) {
    cursor.value = total
  }

  function reset() {
    logs.value = []
    cursor.value = 0
    seenIds.value.clear()
  }

  return {
    logs,
    cursor,
    addLog,
    appendLog,
    appendLogs,
    updateCursor,
    reset,
  }
})
