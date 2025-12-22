<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import MarkdownRenderer from './MarkdownRenderer.vue'

const props = defineProps<{
  thinking: string
  isStreaming?: boolean
  defaultExpanded?: boolean
  collapseAt?: number
  durationMs?: number
}>()

const contentRef = ref<HTMLDivElement | null>(null)
const isExpanded = ref(props.collapseAt != null ? false : (props.isStreaming ? true : Boolean(props.defaultExpanded)))
const lastCollapseAt = ref<number | undefined>(props.collapseAt)
const userToggled = ref(false)

function toggleExpand() {
  userToggled.value = true
  isExpanded.value = !isExpanded.value
}

function formatDuration(ms?: number): string {
  if (!ms || ms <= 0) return ''
  const seconds = Math.max(1, Math.round(ms / 1000))
  return `${seconds}秒`
}

const statusText = computed(() => {
  // When the panel auto-collapses at "content started", we already have durationMs.
  // Show the finished duration even if the overall message is still streaming.
  if (!isExpanded.value && props.durationMs) {
    return `已深度思考 (耗时 ${formatDuration(props.durationMs)})`
  }
  if (props.isStreaming) return '思考中...'
  return props.thinking ? `${props.thinking.length} 字` : '无内容'
})

// 预览文本：取最后几行
function getPreviewText(text: string): string {
  const lines = text.split('\n').filter(l => l.trim())
  const previewLines = lines.slice(-3).join('\n')
  return previewLines.length > 150 ? '...' + previewLines.slice(-150) : previewLines
}

watch(() => props.defaultExpanded, (nextVal) => {
  if (userToggled.value) return
  isExpanded.value = Boolean(nextVal)
})

watch(() => props.collapseAt, (nextVal) => {
  if (userToggled.value) return
  if (!nextVal || nextVal === lastCollapseAt.value) return
  lastCollapseAt.value = nextVal
  isExpanded.value = false
})

// UX 改进：流式阶段自动滚动到底部，跟随思考过程
watch(() => props.thinking, () => {
  if (props.isStreaming && isExpanded.value && contentRef.value) {
    nextTick(() => {
      if (!contentRef.value) return
      contentRef.value.scrollTop = contentRef.value.scrollHeight
    })
  }
})
</script>

<template>
  <div
    class="thinking-block border rounded-xl overflow-hidden mb-4 transition-all"
    :class="[
      isStreaming ? 'border-indigo-300 bg-gradient-to-br from-indigo-50/50 to-purple-50/30' : 'border-slate-200 bg-slate-50/50',
      isExpanded ? 'shadow-md' : 'shadow-sm'
    ]"
  >
    <!-- 头部：可点击折叠/展开 -->
    <div
      class="thinking-header px-4 py-3 cursor-pointer select-none transition-colors hover:bg-slate-100/50 flex items-center justify-between"
      role="button"
      :aria-expanded="isExpanded"
      aria-controls="thinking-content-body"
      :aria-label="`思考过程，${isStreaming ? '思考中' : '已完成'}，点击${isExpanded ? '折叠' : '展开'}`"
      tabindex="0"
      @click="toggleExpand"
      @keydown.enter.prevent="toggleExpand"
      @keydown.space.prevent="toggleExpand"
    >
      <div class="flex items-center gap-3">
        <!-- 图标 -->
        <div
          class="w-8 h-8 rounded-lg flex items-center justify-center text-base transition-all"
          :class="isStreaming ? 'bg-indigo-500 text-white animate-pulse' : 'bg-indigo-100 text-indigo-600'"
        >
          🧠
        </div>

        <!-- 标题 -->
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold text-slate-700">思考过程</span>
          <span
            class="text-xs px-2 py-0.5 rounded-full font-medium"
            :class="isStreaming ? 'bg-indigo-500 text-white' : 'bg-slate-200 text-slate-600'"
          >
            {{ statusText }}
          </span>
        </div>
      </div>

      <!-- 展开/折叠图标 -->
      <div
        class="w-6 h-6 rounded-full bg-slate-200 flex items-center justify-center transition-transform"
        :class="{ 'rotate-180': isExpanded }"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>

    <!-- 预览：折叠时显示 -->
    <div
      v-if="!isExpanded && thinking"
      class="thinking-preview px-4 pb-3 text-xs text-slate-500 leading-relaxed line-clamp-2 relative"
    >
      {{ getPreviewText(thinking) }}
      <div class="absolute bottom-0 left-0 right-0 h-6 bg-gradient-to-t from-slate-50/80 to-transparent pointer-events-none"></div>
    </div>

    <!-- 完整内容：展开时显示 -->
    <transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="max-h-0 opacity-0"
      enter-to-class="max-h-[65vh] opacity-100"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="max-h-[65vh] opacity-100"
      leave-to-class="max-h-0 opacity-0"
    >
      <div v-if="isExpanded" id="thinking-content-body" class="thinking-content border-t border-slate-200">
        <div
          ref="contentRef"
          class="thinking-content-inner px-4 py-4 text-xs text-slate-500 max-h-[60vh] overflow-y-auto"
        >
          <div v-if="!thinking && isStreaming" class="flex items-center gap-2 text-slate-400 italic animate-pulse">
             <span>正在梳理思路...</span>
          </div>
          <MarkdownRenderer v-else :content="thinking" class="thinking-markdown prose-sm" />
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.thinking-block {
  backdrop-filter: blur(8px);
}

/* Firefox scrollbar support */
.thinking-content-inner {
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.3) transparent;
}

/* Webkit (Chrome/Edge/Safari) scrollbar */
.thinking-content-inner::-webkit-scrollbar {
  width: 4px;
}

.thinking-content-inner::-webkit-scrollbar-track {
  background: transparent;
}

.thinking-content-inner::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.3);
  border-radius: 2px;
}

.thinking-content-inner::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.5);
}

/* 流式状态脉冲动画 */
@keyframes pulse-glow {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(99, 102, 241, 0);
  }
}

.thinking-header:hover {
  background: linear-gradient(to right, rgba(241, 245, 249, 0.5), transparent);
}

:deep(.thinking-markdown strong) {
  color: inherit;
}
</style>
