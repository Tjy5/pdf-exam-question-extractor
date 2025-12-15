/**
 * Connection Store - SSE/Polling connection management with exponential backoff
 * Features: generation-based race condition prevention, jittered backoff, proper cleanup
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import { useLogsStore } from './useLogsStore'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting'

const MAX_RETRIES = 5
const BASE_DELAY = 1000
const MAX_DELAY = 30000

export const useConnectionStore = defineStore('connection', () => {
  const eventSource = ref<EventSource | null>(null)
  const pollTimer = ref<number | null>(null)
  const retryTimer = ref<number | null>(null)
  const connectionStatus = ref<ConnectionStatus>('disconnected')
  const retryCount = ref(0)
  const lastEventId = ref<string | null>(null)
  const generation = ref(0)

  const isConnected = computed(() => connectionStatus.value === 'connected')
  const isReconnecting = computed(() => connectionStatus.value === 'reconnecting')

  function getRetryDelayWithJitter(): number {
    const baseDelay = Math.min(BASE_DELAY * Math.pow(2, retryCount.value), MAX_DELAY)
    const jitter = Math.random() * baseDelay * 0.5
    return Math.floor(baseDelay + jitter)
  }

  function clearRetryTimer() {
    if (retryTimer.value !== null) {
      clearTimeout(retryTimer.value)
      retryTimer.value = null
    }
  }

  function connectEventSource(
    taskId: string,
    handlers: {
      onStep: (steps: any[]) => void
      onDone: (status: string) => void
      onFallbackToPolling: () => void
    }
  ) {
    generation.value++
    const currentGen = generation.value

    clearRetryTimer()
    disconnectEventSourceInternal()
    stopPollingInternal()

    connectionStatus.value = 'connecting'

    const logsStore = useLogsStore()
    // Pass lastEventId for SSE replay on reconnection
    const url = api.getStreamUrl(taskId, lastEventId.value)
    const es = new EventSource(url)

    es.onopen = () => {
      if (generation.value !== currentGen) {
        es.close()
        return
      }
      connectionStatus.value = 'connected'
      retryCount.value = 0
    }

    es.addEventListener('step', (e) => {
      if (generation.value !== currentGen) return
      try {
        // Only update lastEventId if present (live-only events have no id)
        if (e.lastEventId) {
          lastEventId.value = e.lastEventId
        }
        const data = JSON.parse(e.data)
        if (data.steps) {
          handlers.onStep(data.steps)
        }
      } catch (err) {
        console.error('Failed to parse step event:', err)
      }
    })

    es.addEventListener('log', (e) => {
      if (generation.value !== currentGen) return
      try {
        // Only update lastEventId if present
        if (e.lastEventId) {
          lastEventId.value = e.lastEventId
        }
        const log = JSON.parse(e.data)
        logsStore.appendLog(log)
      } catch (err) {
        console.error('Failed to parse log event:', err)
      }
    })

    es.addEventListener('done', (e) => {
      if (generation.value !== currentGen) return
      // Only update lastEventId if present
      if (e.lastEventId) {
        lastEventId.value = e.lastEventId
      }
      disconnectEventSourceInternal()
      handlers.onDone(e.data)
    })

    es.onerror = () => {
      if (generation.value !== currentGen) {
        es.close()
        return
      }

      console.warn('SSE connection error')
      disconnectEventSourceInternal()

      if (retryCount.value < MAX_RETRIES) {
        connectionStatus.value = 'reconnecting'
        const delay = getRetryDelayWithJitter()
        console.log(`Retrying SSE in ${delay}ms (attempt ${retryCount.value + 1}/${MAX_RETRIES})`)

        retryTimer.value = window.setTimeout(() => {
          if (generation.value !== currentGen) return
          retryCount.value++
          connectEventSource(taskId, handlers)
        }, delay)
      } else {
        console.warn('Max SSE retries reached, falling back to polling')
        retryCount.value = 0
        connectionStatus.value = 'disconnected'
        handlers.onFallbackToPolling()
      }
    }

    eventSource.value = es
  }

  function disconnectEventSourceInternal() {
    if (eventSource.value) {
      eventSource.value.close()
      eventSource.value = null
    }
  }

  function disconnectEventSource() {
    generation.value++
    clearRetryTimer()
    disconnectEventSourceInternal()
    if (connectionStatus.value !== 'reconnecting') {
      connectionStatus.value = 'disconnected'
    }
  }

  function startPolling(
    taskId: string,
    handlers: {
      onStatus: (data: any) => void
      onComplete: () => void
      onError: (error: string) => void
    }
  ) {
    generation.value++
    const currentGen = generation.value

    clearRetryTimer()
    disconnectEventSourceInternal()
    stopPollingInternal()

    connectionStatus.value = 'connected'

    const logsStore = useLogsStore()

    pollTimer.value = window.setInterval(async () => {
      if (generation.value !== currentGen) {
        stopPollingInternal()
        return
      }

      try {
        const response = await api.getStatus(taskId, logsStore.cursor)
        const data = response.data

        if (generation.value !== currentGen) return

        handlers.onStatus(data)

        if (data.logs?.length) {
          logsStore.appendLogs(data.logs)
          logsStore.updateCursor(data.total_logs)
        }

        if (data.status === 'completed') {
          stopPollingInternal()
          connectionStatus.value = 'disconnected'
          handlers.onComplete()
        } else if (data.status === 'failed') {
          stopPollingInternal()
          connectionStatus.value = 'disconnected'
          handlers.onError(data.error || 'Unknown error')
        }
      } catch (error) {
        console.error('Polling error:', error)
      }
    }, 2000)
  }

  function stopPollingInternal() {
    if (pollTimer.value !== null) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
  }

  function stopPolling() {
    generation.value++
    stopPollingInternal()
    connectionStatus.value = 'disconnected'
  }

  function reset() {
    generation.value++
    clearRetryTimer()
    disconnectEventSourceInternal()
    stopPollingInternal()
    connectionStatus.value = 'disconnected'
    retryCount.value = 0
    lastEventId.value = null
  }

  return {
    connectionStatus,
    retryCount,
    lastEventId,
    isConnected,
    isReconnecting,
    connectEventSource,
    disconnectEventSource,
    startPolling,
    stopPolling,
    reset,
  }
})
