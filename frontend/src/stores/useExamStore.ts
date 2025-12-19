import { ref } from 'vue'
import { defineStore } from 'pinia'

export interface Exam {
  id: number
  exam_dir_name: string
  display_name: string | null
  question_count: number
  has_answers: number
  created_at: string
  processed_at: string | null
}

export interface Question {
  question_no: number
  question_type: string
  display_label: string  // Friendly display name like "第1题" or "资料分析第一大题"
  image_url: string
  has_answer: boolean
}

export interface ExamDetail {
  exam: Exam
  questions: Question[]
}

export const useExamStore = defineStore('exam', () => {
  const exams = ref<Exam[]>([])
  const currentExam = ref<ExamDetail | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 获取所有试卷列表
  async function fetchExams() {
    loading.value = true
    error.value = null
    try {
      const response = await fetch('/api/exams')
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      exams.value = await response.json()
    } catch (err: any) {
      error.value = err.message || '获取试卷列表失败'
      console.error('Failed to fetch exams:', err)
    } finally {
      loading.value = false
    }
  }

  // 获取试卷详情
  async function fetchExamDetail(examId: number) {
    loading.value = true
    error.value = null
    try {
      const response = await fetch(`/api/exams/${examId}`)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      currentExam.value = await response.json()
      return currentExam.value
    } catch (err: any) {
      error.value = err.message || '获取试卷详情失败'
      console.error('Failed to fetch exam detail:', err)
      return null
    } finally {
      loading.value = false
    }
  }

  // 导入答案
  async function importAnswers(examId: number, file: File, source: string = 'manual') {
    loading.value = true
    error.value = null
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('source', source)

      const response = await fetch(`/api/exams/${examId}/answers:import`, {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || `HTTP ${response.status}`)
      }

      const result = await response.json()

      // 更新本地状态中的 has_answers 标记
      const exam = exams.value.find(e => e.id === examId)
      if (exam && result.imported > 0) {
        exam.has_answers = 1
      }

      return result
    } catch (err: any) {
      error.value = err.message || '导入答案失败'
      console.error('Failed to import answers:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    exams,
    currentExam,
    loading,
    error,
    fetchExams,
    fetchExamDetail,
    importAnswers
  }
})
