import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useUserStore } from './useUserStore'
import { useExamStore, type Question } from './useExamStore'

export type QuestionStatus = 'unanswered' | 'pending' | 'wrong' | 'correct' | 'noStandard'

export interface WrongQuestionRecord {
  question_no: number
  user_answer: string
  correct_answer: string
  status: string
  marked_at: string
}

export interface MarkWrongResult {
  wrong_questions: number[]
  correct_questions: number[]
  total: number
}

export const useWrongStore = defineStore('wrong', () => {
  const userStore = useUserStore()
  const examStore = useExamStore()

  const answersByNo = ref<Record<number, string>>({})
  const statusByNo = ref<Record<number, QuestionStatus>>({})
  const correctAnswersByNo = ref<Record<number, string>>({})
  const wrongQuestions = ref<WrongQuestionRecord[]>([])

  const loading = ref(false)
  const submitting = ref(false)
  const error = ref<string | null>(null)

  const dirtyAnswers = ref<Set<number>>(new Set())
  let submitTimeout: ReturnType<typeof setTimeout> | null = null

  const progress = computed(() => {
    const total = Object.keys(statusByNo.value).length
    const answered = Object.values(statusByNo.value).filter(s => s !== 'unanswered').length
    const wrong = Object.values(statusByNo.value).filter(s => s === 'wrong').length
    const correct = Object.values(statusByNo.value).filter(s => s === 'correct').length

    return { total, answered, wrong, correct, percentage: total ? Math.round((answered / total) * 100) : 0 }
  })

  async function initReview(examId: number) {
    loading.value = true
    error.value = null

    try {
      await Promise.all([
        examStore.fetchExamDetail(examId),
        fetchWrongQuestions(examId)
      ])

      const questions = examStore.currentExam?.questions || []

      questions.forEach(q => {
        if (!statusByNo.value[q.question_no]) {
          statusByNo.value[q.question_no] = q.has_answer ? 'unanswered' : 'noStandard'
        }
      })
    } catch (err: unknown) {
      error.value = err instanceof Error ? err.message : 'Failed to initialize review'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function fetchWrongQuestions(examId: number) {
    if (!userStore.userId) return

    try {
      const res = await fetch(`/api/users/${userStore.userId}/exams/${examId}/wrong-questions`)
      if (!res.ok) {
        if (res.status === 404) {
          wrongQuestions.value = []
          return
        }
        throw new Error(`HTTP ${res.status}: ${res.statusText}`)
      }

      const data: WrongQuestionRecord[] = await res.json()
      wrongQuestions.value = data

      data.forEach(item => {
        answersByNo.value[item.question_no] = item.user_answer
        correctAnswersByNo.value[item.question_no] = item.correct_answer
        statusByNo.value[item.question_no] = item.status === 'wrong' ? 'wrong' : 'correct'
      })
    } catch (err: unknown) {
      console.error('Fetch wrong questions error:', err)
      throw err
    }
  }

  function setAnswer(examId: number, questionNo: number, answer: string) {
    if (!answer) {
      delete answersByNo.value[questionNo]
      statusByNo.value[questionNo] = 'unanswered'
      dirtyAnswers.value.delete(questionNo)
      return
    }

    answersByNo.value[questionNo] = answer.toUpperCase()
    statusByNo.value[questionNo] = 'pending'
    dirtyAnswers.value.add(questionNo)

    if (submitTimeout) clearTimeout(submitTimeout)
    submitTimeout = setTimeout(() => {
      submitAnswers(examId)
    }, 500)
  }

  async function submitAnswers(examId: number) {
    if (dirtyAnswers.value.size === 0 || !userStore.userId) return
    if (submitting.value) return

    const batch = Array.from(dirtyAnswers.value)
    const payload: Record<string, string> = {}

    batch.forEach(qNo => {
      const answer = answersByNo.value[qNo]
      const status = statusByNo.value[qNo]
      if (answer && status !== 'noStandard') {
        payload[qNo.toString()] = answer
      }
    })

    if (Object.keys(payload).length === 0) {
      batch.forEach(qNo => dirtyAnswers.value.delete(qNo))
      return
    }

    const submittedQuestions = Object.keys(payload).map(Number)
    submittedQuestions.forEach(qNo => {
      statusByNo.value[qNo] = 'pending'
    })

    submitting.value = true

    try {
      const res = await fetch(`/api/users/${userStore.userId}/exams/${examId}/wrong-questions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: payload })
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const result: MarkWrongResult = await res.json()

      result.wrong_questions.forEach(qNo => {
        statusByNo.value[qNo] = 'wrong'
      })

      result.correct_questions.forEach(qNo => {
        statusByNo.value[qNo] = 'correct'
      })

      batch.forEach(qNo => dirtyAnswers.value.delete(qNo))

      await fetchWrongQuestions(examId)
    } catch (err: unknown) {
      console.error('Submit answers error:', err)
      batch.forEach(qNo => {
        const prevStatus = statusByNo.value[qNo]
        if (prevStatus === 'pending') {
          statusByNo.value[qNo] = 'unanswered'
        }
      })
      error.value = err instanceof Error ? err.message : 'Failed to submit answers'
    } finally {
      submitting.value = false
    }
  }

  function clearReview() {
    answersByNo.value = {}
    statusByNo.value = {}
    correctAnswersByNo.value = {}
    wrongQuestions.value = []
    dirtyAnswers.value.clear()
    error.value = null
    if (submitTimeout) {
      clearTimeout(submitTimeout)
      submitTimeout = null
    }
  }

  return {
    answersByNo,
    statusByNo,
    correctAnswersByNo,
    wrongQuestions,
    loading,
    submitting,
    error,
    progress,
    initReview,
    fetchWrongQuestions,
    setAnswer,
    submitAnswers,
    clearReview
  }
})
