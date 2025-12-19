<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

const props = defineProps<{
  content: string
}>()

const md = new MarkdownIt({
  html: false,  // 禁用 HTML 防止 XSS
  linkify: true,
  typographer: true,
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return '<pre class="hljs"><code>' +
               hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
               '</code></pre>'
      } catch (__) {}
    }
    return '<pre class="hljs"><code>' + md.utils.escapeHtml(str) + '</code></pre>'
  }
})

const html = computed(() => {
  return md.render(props.content || '')
})
</script>

<template>
  <div class="prose prose-slate max-w-none" v-html="html"></div>
</template>

<style scoped>
.prose {
  color: inherit;
}

.prose pre {
  @apply bg-slate-800 text-slate-100 rounded-lg p-4 overflow-x-auto my-3;
}

.prose code {
  @apply text-sm font-mono;
}

.prose :not(pre) > code {
  @apply bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-sm;
}

.prose p {
  @apply my-2;
}

.prose ul, .prose ol {
  @apply my-2 pl-6;
}

.prose ul {
  @apply list-disc;
}

.prose ol {
  @apply list-decimal;
}

.prose li {
  @apply my-1;
}

.prose strong {
  @apply font-bold text-slate-900;
}

.prose h1, .prose h2, .prose h3, .prose h4 {
  @apply font-bold mt-4 mb-2;
}

.prose h1 {
  @apply text-xl;
}

.prose h2 {
  @apply text-lg;
}

.prose h3 {
  @apply text-base;
}

.prose blockquote {
  @apply border-l-4 border-slate-300 pl-4 italic text-slate-600 my-2;
}

.prose a {
  @apply text-blue-600 hover:underline;
}

.prose hr {
  @apply border-slate-300 my-4;
}

.prose table {
  @apply w-full border-collapse my-2;
}

.prose th, .prose td {
  @apply border border-slate-300 px-3 py-2;
}

.prose th {
  @apply bg-slate-100 font-bold;
}
</style>
