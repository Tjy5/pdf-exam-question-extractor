import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUserStore = defineStore('user', () => {
  // 从 localStorage 获取或生成 user_id
  const userId = ref<string>(localStorage.getItem('user_id') || '')

  if (!userId.value) {
    // 生成唯一 user_id
    userId.value = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    localStorage.setItem('user_id', userId.value)
  }

  function setUserId(id: string) {
    userId.value = id
    localStorage.setItem('user_id', id)
  }

  return {
    userId,
    setUserId
  }
})
