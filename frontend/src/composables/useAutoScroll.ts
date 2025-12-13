/**
 * Auto-scroll composable for log terminal
 * Keeps view at bottom to show newest logs
 */

import { ref, watch, nextTick, type Ref } from 'vue'

export function useAutoScroll(items: Ref<any[]>) {
  const containerRef = ref<HTMLElement | null>(null)
  const autoScroll = ref(true)

  // Watch for new items and scroll to bottom
  watch(
    () => items.value.length,
    async () => {
      if (autoScroll.value && containerRef.value) {
        await nextTick()
        const el = containerRef.value
        el.scrollTop = el.scrollHeight
      }
    }
  )

  function handleScroll() {
    if (!containerRef.value) return

    // Check if user has scrolled away from bottom
    const { scrollTop, scrollHeight, clientHeight } = containerRef.value
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight
    autoScroll.value = distanceFromBottom < 50
  }

  return {
    containerRef,
    autoScroll,
    handleScroll,
  }
}
