import { createRouter, createWebHistory } from 'vue-router'

const LAST_VISITED_KEY = 'newvl:lastVisitedRoute'

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
      name: 'Root',
      redirect: () => readLastVisitedRoute() || '/dashboard'
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('@/views/DashboardView.vue')
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('@/views/ChatView.vue')
    },
    {
      path: '/exam/:examId/chat',
      name: 'ExamChat',
      component: () => import('@/views/ChatView.vue'),
      props: true
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
  } catch {
    // ignore storage failures (private mode / quota / etc.)
  }
})

export default router
