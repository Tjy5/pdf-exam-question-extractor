/**
 * Drag and Drop composable for file upload
 */

import { ref } from 'vue'

export function useDragDrop(onFileDrop: (file: File) => void) {
  const isDragging = ref(false)

  function handleDragOver(e: DragEvent) {
    e.preventDefault()
    isDragging.value = true
  }

  function handleDragLeave(e: DragEvent) {
    e.preventDefault()
    isDragging.value = false
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    isDragging.value = false

    const files = e.dataTransfer?.files
    if (files && files.length > 0) {
      const file = files[0]
      if (file.type === 'application/pdf') {
        onFileDrop(file)
      } else {
        console.warn('Only PDF files are accepted')
      }
    }
  }

  return {
    isDragging,
    handleDragOver,
    handleDragLeave,
    handleDrop,
  }
}
