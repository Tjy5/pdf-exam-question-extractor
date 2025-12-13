/**
 * EventSource (SSE) composable
 */

import { ref, onUnmounted } from 'vue'

export interface SSEOptions {
  onStep?: (data: any) => void
  onLog?: (data: any) => void
  onDone?: (status: string) => void
  onError?: (error: Event) => void
}

export function useEventSource() {
  const eventSource = ref<EventSource | null>(null)
  const isConnected = ref(false)

  function connect(url: string, options: SSEOptions = {}) {
    disconnect()

    const es = new EventSource(url)

    es.addEventListener('step', (e) => {
      try {
        const data = JSON.parse(e.data)
        options.onStep?.(data)
      } catch (err) {
        console.error('Failed to parse step event:', err)
      }
    })

    es.addEventListener('log', (e) => {
      try {
        const data = JSON.parse(e.data)
        options.onLog?.(data)
      } catch (err) {
        console.error('Failed to parse log event:', err)
      }
    })

    es.addEventListener('done', (e) => {
      options.onDone?.(e.data)
      disconnect()
    })

    es.onerror = (error) => {
      console.error('SSE error:', error)
      options.onError?.(error)
      disconnect()
    }

    es.onopen = () => {
      isConnected.value = true
    }

    eventSource.value = es
  }

  function disconnect() {
    if (eventSource.value) {
      eventSource.value.close()
      eventSource.value = null
      isConnected.value = false
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    eventSource,
    isConnected,
    connect,
    disconnect,
  }
}
