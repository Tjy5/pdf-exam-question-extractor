/**
 * API client for ExamPaper backend
 */

import axios, { type AxiosInstance, type AxiosResponse } from 'axios'
import type {
  UploadResponse,
  StatusResponse,
  ResultsResponse,
  StepResultsResponse,
  TaskMode,
} from './types'

const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor for logging
client.interceptors.request.use(
  (config) => {
    console.debug(`[API] ${config.method?.toUpperCase()} ${config.url}`)
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor for error handling
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || 'Unknown error'
    console.error(`[API Error] ${message}`)
    return Promise.reject(new Error(message))
  }
)

export const api = {
  /**
   * Upload a PDF file and create a task
   */
  upload(file: File, mode: TaskMode = 'auto'): Promise<AxiosResponse<UploadResponse>> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('mode', mode)

    return client.post<UploadResponse>('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000, // 2 minutes for upload
    })
  },

  /**
   * Start processing a task (auto mode)
   */
  startProcess(taskId: string): Promise<AxiosResponse<{ message: string }>> {
    return client.post('/process', { task_id: taskId })
  },

  /**
   * Start a step (manual mode)
   * @param runToEnd If true, run from this step to the end. If false, run only this step.
   */
  startStep(taskId: string, stepIndex: number, runToEnd: boolean = false): Promise<AxiosResponse<{ message: string }>> {
    return client.post(`/tasks/${taskId}/steps/${stepIndex}/start`, null, {
      params: { run_to_end: runToEnd }
    })
  },

  /**
   * Get task status with incremental logs
   */
  getStatus(taskId: string, cursor: number = 0): Promise<AxiosResponse<StatusResponse>> {
    return client.get<StatusResponse>(`/status/${taskId}`, {
      params: { since: cursor },
    })
  },

  /**
   * Get step results/artifacts
   */
  getStepResults(taskId: string, stepIndex: number): Promise<AxiosResponse<StepResultsResponse>> {
    return client.get<StepResultsResponse>(`/tasks/${taskId}/steps/${stepIndex}/results`)
  },

  /**
   * Get final results (images)
   */
  getResults(taskId: string): Promise<AxiosResponse<ResultsResponse>> {
    return client.get<ResultsResponse>(`/results/${taskId}`)
  },

  /**
   * Restart task from a specific step
   */
  restartFromStep(taskId: string, stepIndex: number): Promise<AxiosResponse<{ message: string; steps: any[] }>> {
    return client.post(`/tasks/${taskId}/restart/${stepIndex}`)
  },

  /**
   * Get download URL for all results
   */
  getDownloadUrl(taskId: string): string {
    return `/api/download/${taskId}`
  },

  /**
   * Get image URL
   */
  getImageUrl(taskId: string, filename: string): string {
    return `/api/image/${taskId}/${filename}`
  },

  /**
   * Create SSE connection URL with optional last event ID for replay
   */
  getStreamUrl(taskId: string, lastEventId?: string | number | null): string {
    const base = `/api/stream/${taskId}`
    if (lastEventId != null && lastEventId !== '') {
      return `${base}?last_event_id=${lastEventId}`
    }
    return base
  },

  /**
   * List available local exam directories
   */
  listLocalExamDirectories(): Promise<AxiosResponse<{ directories: string[] }>> {
    return client.get('/exams/local/directories')
  },

  /**
   * Import a local exam directory
   */
  importLocalExam(data: {
    exam_dir_name: string
    display_name?: string
    dry_run?: boolean
    overwrite?: boolean
  }): Promise<AxiosResponse<any>> {
    return client.post('/exams/local:import', data)
  },
}

export default api
