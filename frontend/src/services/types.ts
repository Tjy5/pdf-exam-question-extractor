/**
 * TypeScript type definitions for the ExamPaper API
 */

export type TaskMode = 'auto' | 'manual'

export type TaskStatus = 'idle' | 'uploading' | 'processing' | 'paused' | 'completed' | 'error'

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export interface Step {
  index: number
  name: string
  title: string
  desc: string
  icon: string
  status: StepStatus
  error: string | null
  artifact_count: number
  progress: number | null
  progress_text: string | null
}

export interface LogEntry {
  id: string
  time: string
  message: string
  type: 'default' | 'info' | 'success' | 'error'
}

export interface ImageResult {
  src: string
  name: string
  path: string
}

// API Response Types

export interface UploadResponse {
  task_id: string
  filename: string
  mode: TaskMode
  steps: Array<{
    index: number
    name: string
    status: StepStatus
    artifact_count?: number
  }>
}

export interface StatusResponse {
  task_id: string
  status: string
  mode: TaskMode
  current_step: number
  steps: Array<{
    index: number
    name: string
    status: StepStatus
    error?: string
    artifact_count?: number
    progress?: number
    progress_text?: string
  }>
  logs: LogEntry[]
  total_logs: number
  error?: string
}

export interface ResultsResponse {
  task_id: string
  images: Array<{
    filename: string
    name: string
    path: string
  }>
}

export interface StepResultsResponse {
  task_id: string
  step: {
    index: number
    name: string
    status: StepStatus
    artifact_count: number
    artifacts: string[]
  }
}

// SSE Event Types

export interface SSEStepEvent {
  task_id: string
  steps: Array<{
    index: number
    status: StepStatus
    error?: string
    artifact_count?: number
    progress?: number
    progress_text?: string
  }>
}

export interface SSELogEvent {
  id: string
  time: string
  message: string
  type: 'default' | 'info' | 'success' | 'error'
}
