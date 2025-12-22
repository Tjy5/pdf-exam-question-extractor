<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { computed } from 'vue'
import { LAST_CHAT_ROUTE_KEY } from '@/router'

const route = useRoute()

const CHAT_ROUTE_PATTERN = /^\/exam\/\d+\/chat(?:\?|$)/

function readLastChatRoute(): string | null {
  try {
    if (typeof window === 'undefined') return null
    const raw = window.localStorage.getItem(LAST_CHAT_ROUTE_KEY)
    if (!raw) return null
    const value = raw.trim()
    if (!value || value === '/' || value === '/chat') return null
    if (!CHAT_ROUTE_PATTERN.test(value)) return null
    return value
  } catch {
    return null
  }
}

const aiChatTarget = computed(() => {
  // Recompute on route change so navigation reflects the latest stored chat.
  void route.fullPath
  return readLastChatRoute() || '/chat'
})

const navItems = computed(() => ([
  { name: '首页', path: '/', icon: '🏠' },
  { name: '试卷处理', path: '/dashboard', icon: '📝' },
  { name: 'AI 答疑', path: aiChatTarget.value, icon: '💬' },
  { name: '我的题库', path: '/exams', icon: '🗂️' },
  { name: '错题本', path: '/wrong-notebook', icon: '📖' },
]))

const isActive = (path: string) => {
  if (path === '/') return route.path === '/'
  if (path.includes('/chat')) {
    return route.name === 'ChatLanding' || route.name === 'ExamChat'
  }
  return route.path.startsWith(path)
}
</script>

<template>
  <nav class="sticky top-0 z-50 w-full bg-white/80 backdrop-blur-xl border-b border-slate-200/60 transition-all duration-300">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between h-16">
        <!-- Logo / Brand -->
        <div class="flex-shrink-0 flex items-center gap-2 cursor-pointer" @click="$router.push('/')">
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white font-bold shadow-md shadow-indigo-200">
            AI
          </div>
          <span class="font-bold text-xl tracking-tight text-slate-800">
            智能试卷<span class="text-indigo-600">答疑</span>
          </span>
        </div>

        <!-- Desktop Navigation -->
        <div class="hidden md:block">
          <div class="ml-10 flex items-baseline space-x-2">
            <RouterLink
              v-for="item in navItems"
              :key="item.name"
              :to="item.path"
              class="group relative px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ease-in-out flex items-center gap-2"
              :class="[
                isActive(item.path)
                  ? 'text-indigo-600 bg-indigo-50/80 shadow-sm shadow-indigo-100/50'
                  : 'text-slate-600 hover:text-indigo-600 hover:bg-slate-50'
              ]"
            >
              <span>{{ item.icon }}</span>
              {{ item.name }}
              
              <!-- Active Indicator -->
              <span
                v-if="isActive(item.path)"
                class="absolute bottom-1.5 left-1/2 -translate-x-1/2 w-1 h-1 bg-indigo-600 rounded-full"
              ></span>
            </RouterLink>
          </div>
        </div>

        <!-- Mobile menu button (placeholder) -->
        <div class="md:hidden flex items-center">
            <!-- Simple hamburger if needed, but for now focusing on desktop as per user implies -->
        </div>
      </div>
    </div>
  </nav>
</template>

<style scoped>
/* Optional: Add custom active styles or animations */
</style>
