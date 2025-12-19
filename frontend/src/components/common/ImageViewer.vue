<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'

const props = defineProps<{
  open: boolean
  src: string
  alt?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const scale = ref(1)
const dragging = ref(false)
const position = ref({ x: 0, y: 0 })
const startPos = ref({ x: 0, y: 0 })

watch(() => props.open, (newVal) => {
  if (newVal) {
    scale.value = 1
    position.value = { x: 0, y: 0 }
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
})

// 确保组件卸载时恢复滚动
onUnmounted(() => {
  document.body.style.overflow = ''
})

const zoomIn = () => scale.value = Math.min(scale.value + 0.5, 5)
const zoomOut = () => scale.value = Math.max(scale.value - 0.5, 0.5)

const handleWheel = (e: WheelEvent) => {
  e.preventDefault()
  const delta = e.deltaY * -0.001
  scale.value = Math.min(Math.max(scale.value + delta, 0.5), 5)
}

const startDrag = (e: MouseEvent | TouchEvent) => {
  if (scale.value <= 1) return
  dragging.value = true
  const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
  const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY
  startPos.value = {
    x: clientX - position.value.x,
    y: clientY - position.value.y
  }
}

const onDrag = (e: MouseEvent | TouchEvent) => {
  if (!dragging.value) return
  e.preventDefault()
  const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
  const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY
  position.value = {
    x: clientX - startPos.value.x,
    y: clientY - startPos.value.y
  }
}

const stopDrag = () => dragging.value = false
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/90 backdrop-blur-sm"
        @click.self="emit('close')"
      >
        <!-- 工具栏 -->
        <div class="absolute top-4 right-4 flex space-x-2 z-10">
          <button
            @click="zoomOut"
            class="p-2 bg-white/10 hover:bg-white/20 text-white rounded-full transition-colors"
            title="缩小"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12H4" />
            </svg>
          </button>
          <button
            @click="zoomIn"
            class="p-2 bg-white/10 hover:bg-white/20 text-white rounded-full transition-colors"
            title="放大"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
          </button>
          <button
            @click="emit('close')"
            class="p-2 bg-white/20 hover:bg-rose-500/80 text-white rounded-full transition-colors ml-4"
            title="关闭"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- 图片容器 -->
        <div
          class="overflow-hidden w-full h-full flex items-center justify-center"
          :class="scale > 1 ? 'cursor-move' : 'cursor-default'"
          @wheel="handleWheel"
          @mousedown="startDrag"
          @mousemove="onDrag"
          @mouseup="stopDrag"
          @mouseleave="stopDrag"
          @touchstart="startDrag"
          @touchmove="onDrag"
          @touchend="stopDrag"
        >
          <img
            :src="src"
            :alt="alt || '查看图片'"
            class="max-w-full max-h-full object-contain transition-transform duration-75 ease-linear select-none"
            :style="{
              transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
            }"
            draggable="false"
          />
        </div>

        <div class="absolute bottom-4 left-1/2 -translate-x-1/2 text-white/50 text-sm pointer-events-none">
          滚动缩放 • 拖拽移动
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
