import { createRouter, createWebHistory } from 'vue-router'

const LAST_VISITED_KEY = 'newvl:lastVisitedRoute'
export const LAST_CHAT_ROUTE_KEY = 'newvl:lastChatRoute'

function readLastVisitedRoute(): string | null {
  try {
    if (typeof window === 'undefined') return null
    const raw = window.localStorage.getItem(LAST_VISITED_KEY)
    if (!raw) return null
    const value = raw.trim()
    if (!value || value === '/' || !value.startsWith('/')) return null
    return value
  } catch {
    return null
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'Home',
      component: () => import('@/views/HomeView.vue')
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('@/views/DashboardView.vue')
    },
    {
      path: '/exams',
      name: 'ExamList',
      component: () => import('@/views/ExamListView.vue')
    },
    {
      path: '/chat',
      name: 'ChatLanding',
      component: () => import('@/views/chat/ChatLandingView.vue')
    },
    {
      path: '/exam/:examId/chat',
      name: 'ExamChat',
      component: () => import('@/views/ChatView.vue'),
      props: route => ({ examId: String(route.params.examId) })
    },
    {
      path: '/exam/:examId/review',
      name: 'ExamReview',
      component: () => import('@/views/ReviewView.vue')
    },
    {
      path: '/wrong-notebook',
      name: 'WrongNotebook',
      component: () => import('@/views/WrongNotebook.vue')
    }
  ]
})

router.afterEach((to) => {
  try {
    if (typeof window === 'undefined') return
    if (to.path === '/') return

    // For chat route, strip sid/sessionId so we don't persist a potentially stale session.
    let persisted = to.fullPath
    if (to.name === 'ExamChat') {
      const q = typeof to.query.q === 'string' ? to.query.q : undefined
      const params = new URLSearchParams()
      if (q) params.set('q', q)
      const qs = params.toString()
      persisted = qs ? `${to.path}?${qs}` : to.path
    }

    window.localStorage.setItem(LAST_VISITED_KEY, persisted)
    if (to.name === 'ExamChat') {
      window.localStorage.setItem(LAST_CHAT_ROUTE_KEY, persisted)
    }
  } catch {
    // ignore storage failures (private mode / quota / etc.)
  }
})

export default router
