<template>
  <div class="wrong-notebook">
    <header class="notebook-header">
      <h1>错题本</h1>
      <div class="header-actions">
        <button class="btn-upload" @click="showUploader = true">
          <span class="icon">+</span>
          上传错题
        </button>
      </div>
    </header>

    <!-- Filter Bar -->
    <div class="filter-bar">
      <select v-model="filterSubject" @change="applyFilters">
        <option value="">全部学科</option>
        <option value="数学">数学</option>
        <option value="物理">物理</option>
        <option value="化学">化学</option>
        <option value="生物">生物</option>
        <option value="英语">英语</option>
        <option value="语文">语文</option>
        <option value="其他">其他</option>
      </select>

      <select v-model="filterMastery" @change="applyFilters">
        <option :value="undefined">全部状态</option>
        <option :value="0">待复习</option>
        <option :value="1">复习中</option>
        <option :value="2">已掌握</option>
      </select>

      <input
        v-model="searchQuery"
        type="text"
        placeholder="搜索题目..."
        class="search-input"
        @input="debouncedSearch"
      />
    </div>

    <!-- Loading State -->
    <div v-if="store.loading" class="loading-state">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="store.isEmpty" class="empty-state">
      <div class="empty-icon">📚</div>
      <h3>还没有错题</h3>
      <p>点击上方"上传错题"按钮添加第一道错题</p>
    </div>

    <!-- Wrong Items Grid -->
    <div v-else class="items-grid">
      <div
        v-for="item in store.items"
        :key="item.id"
        class="wrong-item-card"
        @click="viewItem(item)"
      >
        <div class="card-header">
          <span class="subject-badge" :class="item.subject">{{ item.subject || '未分类' }}</span>
          <span class="mastery-badge" :class="getMasteryClass(item.mastery_level)">
            {{ getMasteryText(item.mastery_level) }}
          </span>
        </div>

        <div class="card-content">
          <div v-if="item.original_image" class="card-image">
            <img :src="'data:image/jpeg;base64,' + item.original_image.slice(0, 100) + '...'" alt="错题图片" />
          </div>
          <div class="card-text">
            <p class="question-preview">{{ truncateText(item.ai_question_text, 100) }}</p>
          </div>
        </div>

        <div class="card-footer">
          <span class="date">{{ formatDate(item.updated_at) }}</span>
          <div class="card-actions" @click.stop>
            <button class="btn-icon" @click="updateMastery(item, 2)" title="标记已掌握">✓</button>
            <button class="btn-icon delete" @click="confirmDelete(item)" title="删除">×</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="store.total > store.pageSize" class="pagination">
      <button :disabled="store.page <= 1" @click="store.setPage(store.page - 1)">上一页</button>
      <span>第 {{ store.page }} 页 / 共 {{ Math.ceil(store.total / store.pageSize) }} 页</span>
      <button :disabled="!store.hasMore" @click="store.setPage(store.page + 1)">下一页</button>
    </div>

    <!-- Upload Modal -->
    <div v-if="showUploader" class="modal-overlay" @click.self="closeUploader">
      <div class="modal-content upload-modal">
        <div class="modal-header">
          <h2>上传错题</h2>
          <button class="btn-close" @click="closeUploader">×</button>
        </div>

        <!-- Step 1: Upload Image -->
        <div v-if="uploadStep === 1" class="upload-step">
          <div
            class="upload-zone"
            :class="{ 'drag-over': isDragOver }"
            @drop.prevent="handleDrop"
            @dragover.prevent="isDragOver = true"
            @dragleave="isDragOver = false"
            @click="triggerFileInput"
          >
            <input ref="fileInput" type="file" accept="image/*" hidden @change="handleFileSelect" />
            <div v-if="!uploadPreview" class="upload-placeholder">
              <div class="upload-icon">📷</div>
              <p>点击或拖拽上传错题图片</p>
              <span class="hint">支持 JPG、PNG，建议大小 &lt; 5MB</span>
            </div>
            <div v-else class="preview-container">
              <img :src="uploadPreview" alt="预览" />
              <button class="btn-reupload" @click.stop="clearUpload">重新上传</button>
            </div>
          </div>

          <div class="upload-options">
            <label>
              学科提示（可选）：
              <select v-model="uploadSubject">
                <option value="">自动识别</option>
                <option value="数学">数学</option>
                <option value="物理">物理</option>
                <option value="化学">化学</option>
                <option value="生物">生物</option>
                <option value="英语">英语</option>
                <option value="语文">语文</option>
              </select>
            </label>
          </div>

          <button
            class="btn-primary"
            :disabled="!uploadPreview || store.analyzing"
            @click="startAnalyze"
          >
            {{ store.analyzing ? '分析中...' : '开始 AI 分析' }}
          </button>
        </div>

        <!-- Step 2: Edit AI Result -->
        <div v-else-if="uploadStep === 2" class="edit-step">
          <div class="edit-layout">
            <div class="edit-image">
              <img :src="uploadPreview" alt="原图" />
            </div>
            <div class="edit-form">
              <div class="form-group">
                <label>题目</label>
                <textarea v-model="editForm.questionText" rows="4"></textarea>
              </div>
              <div class="form-group">
                <label>答案</label>
                <textarea v-model="editForm.answerText" rows="2"></textarea>
              </div>
              <div class="form-group">
                <label>解析</label>
                <textarea v-model="editForm.analysis" rows="4"></textarea>
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>学科</label>
                  <select v-model="editForm.subject">
                    <option value="数学">数学</option>
                    <option value="物理">物理</option>
                    <option value="化学">化学</option>
                    <option value="生物">生物</option>
                    <option value="英语">英语</option>
                    <option value="语文">语文</option>
                    <option value="其他">其他</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>来源</label>
                  <input v-model="editForm.sourceName" placeholder="如：期中考试" />
                </div>
              </div>
            </div>
          </div>

          <div class="edit-actions">
            <button class="btn-secondary" @click="uploadStep = 1">返回</button>
            <button class="btn-primary" :disabled="saving" @click="saveItem">
              {{ saving ? '保存中...' : '保存到错题本' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Item Detail Modal -->
    <div v-if="selectedItem" class="modal-overlay" @click.self="selectedItem = null">
      <div class="modal-content detail-modal">
        <div class="modal-header">
          <h2>错题详情</h2>
          <button class="btn-close" @click="selectedItem = null">×</button>
        </div>
        <div class="detail-content">
          <div v-if="selectedItem.original_image" class="detail-image">
            <img :src="'data:image/jpeg;base64,' + selectedItem.original_image" alt="错题图片" />
          </div>
          <div class="detail-info">
            <div class="info-section">
              <h3>题目</h3>
              <div class="markdown-content" v-html="renderMarkdown(selectedItem.ai_question_text)"></div>
            </div>
            <div class="info-section">
              <h3>答案</h3>
              <div class="markdown-content" v-html="renderMarkdown(selectedItem.ai_answer_text)"></div>
            </div>
            <div class="info-section">
              <h3>解析</h3>
              <div class="markdown-content" v-html="renderMarkdown(selectedItem.ai_analysis)"></div>
            </div>
          </div>
        </div>
        <div class="detail-actions">
          <select
            :value="selectedItem.mastery_level"
            @change="updateItemMastery(selectedItem, Number(($event.target as HTMLSelectElement).value))"
          >
            <option :value="0">待复习</option>
            <option :value="1">复习中</option>
            <option :value="2">已掌握</option>
          </select>
          <button class="btn-danger" @click="confirmDelete(selectedItem)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useWrongNotebookStore, type WrongItem } from '@/stores/useWrongNotebookStore'
import { useUserStore } from '@/stores/useUserStore'

const store = useWrongNotebookStore()
const userStore = useUserStore()

// Filter state
const filterSubject = ref('')
const filterMastery = ref<number | undefined>(undefined)
const searchQuery = ref('')
let searchTimeout: ReturnType<typeof setTimeout> | null = null

// Upload state
const showUploader = ref(false)
const uploadStep = ref(1)
const uploadPreview = ref<string | null>(null)
const uploadBase64 = ref('')
const uploadMimeType = ref('image/jpeg')
const uploadSubject = ref('')
const isDragOver = ref(false)
const fileInput = ref<HTMLInputElement>()
const saving = ref(false)

// Edit form
const editForm = ref({
  questionText: '',
  answerText: '',
  analysis: '',
  subject: '数学',
  sourceName: ''
})

// Detail view
const selectedItem = ref<WrongItem | null>(null)

onMounted(async () => {
  await userStore.initUser()
  await store.loadItems()
})

function applyFilters() {
  store.setFilters({
    subject: filterSubject.value || undefined,
    masteryLevel: filterMastery.value
  })
}

function debouncedSearch() {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    store.setFilters({ search: searchQuery.value || undefined })
  }, 300)
}

function triggerFileInput() {
  fileInput.value?.click()
}

async function handleFileSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) await processFile(file)
}

async function handleDrop(e: DragEvent) {
  isDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file?.type.startsWith('image/')) {
    await processFile(file)
  }
}

async function processFile(file: File) {
  // Compress if needed
  const maxSize = 1024 * 1024 // 1MB
  let processedFile = file

  if (file.size > maxSize) {
    // Simple compression via canvas
    const img = await createImageFromFile(file)
    const canvas = document.createElement('canvas')
    const maxDim = 2000
    let { width, height } = img
    if (width > maxDim || height > maxDim) {
      const ratio = Math.min(maxDim / width, maxDim / height)
      width *= ratio
      height *= ratio
    }
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')!
    ctx.drawImage(img, 0, 0, width, height)
    const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
    uploadPreview.value = dataUrl
    uploadBase64.value = dataUrl.split(',')[1]
    uploadMimeType.value = 'image/jpeg'
  } else {
    const reader = new FileReader()
    reader.onload = (e) => {
      const result = e.target?.result as string
      uploadPreview.value = result
      uploadBase64.value = result.split(',')[1]
      uploadMimeType.value = file.type
    }
    reader.readAsDataURL(file)
  }
}

function createImageFromFile(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.src = URL.createObjectURL(file)
  })
}

function clearUpload() {
  uploadPreview.value = null
  uploadBase64.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

async function startAnalyze() {
  try {
    const result = await store.analyzeImage(uploadBase64.value, uploadMimeType.value, uploadSubject.value || undefined)
    editForm.value = {
      questionText: result.question_text || '',
      answerText: result.answer_text || '',
      analysis: result.analysis || '',
      subject: result.subject || '数学',
      sourceName: ''
    }
    uploadStep.value = 2
  } catch (err) {
    alert('分析失败：' + (err instanceof Error ? err.message : '未知错误'))
  }
}

async function saveItem() {
  saving.value = true
  try {
    await store.createItem({
      sourceType: 'upload',
      originalImage: uploadBase64.value,
      aiQuestionText: editForm.value.questionText,
      aiAnswerText: editForm.value.answerText,
      aiAnalysis: editForm.value.analysis,
      subject: editForm.value.subject,
      sourceName: editForm.value.sourceName
    })
    closeUploader()
    await store.loadItems()
  } catch (err) {
    alert('保存失败：' + (err instanceof Error ? err.message : '未知错误'))
  } finally {
    saving.value = false
  }
}

function closeUploader() {
  showUploader.value = false
  uploadStep.value = 1
  clearUpload()
  editForm.value = { questionText: '', answerText: '', analysis: '', subject: '数学', sourceName: '' }
}

function viewItem(item: WrongItem) {
  selectedItem.value = item
}

async function updateMastery(item: WrongItem, level: number) {
  await store.updateItem(item.id, { masteryLevel: level })
}

async function updateItemMastery(item: WrongItem, level: number) {
  await store.updateItem(item.id, { masteryLevel: level })
  item.mastery_level = level
}

async function confirmDelete(item: WrongItem) {
  if (confirm('确定要删除这道错题吗？')) {
    await store.deleteItem(item.id)
    if (selectedItem.value?.id === item.id) {
      selectedItem.value = null
    }
  }
}

function getMasteryClass(level: number) {
  return ['pending', 'reviewing', 'mastered'][level] || 'pending'
}

function getMasteryText(level: number) {
  return ['待复习', '复习中', '已掌握'][level] || '待复习'
}

function truncateText(text: string | undefined, maxLen: number) {
  if (!text) return '暂无内容'
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text
}

function formatDate(dateStr: string) {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN')
}

function renderMarkdown(text: string | undefined) {
  if (!text) return '<p>暂无内容</p>'
  // Simple markdown rendering (in production, use a proper library)
  return text
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\$(.*?)\$/g, '<span class="math">$1</span>')
}
</script>

<style scoped>
.wrong-notebook {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}

.notebook-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.notebook-header h1 {
  font-size: 24px;
  font-weight: 600;
  color: #1a1a1a;
}

.btn-upload {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.btn-upload:hover {
  background: #2563eb;
}

.btn-upload .icon {
  font-size: 18px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.filter-bar select,
.search-input {
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 14px;
  background: white;
}

.search-input {
  flex: 1;
  min-width: 200px;
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px;
  color: #6b7280;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #e5e7eb;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.wrong-item-card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.2s;
}

.wrong-item-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}

.subject-badge {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  background: #e5e7eb;
}

.mastery-badge {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.mastery-badge.pending { background: #fef3c7; color: #92400e; }
.mastery-badge.reviewing { background: #dbeafe; color: #1e40af; }
.mastery-badge.mastered { background: #d1fae5; color: #065f46; }

.card-content {
  margin-bottom: 12px;
}

.question-preview {
  font-size: 14px;
  color: #374151;
  line-height: 1.5;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #9ca3af;
}

.card-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 4px;
  background: #f3f4f6;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-icon:hover { background: #e5e7eb; }
.btn-icon.delete:hover { background: #fee2e2; color: #dc2626; }

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 32px;
}

.pagination button {
  padding: 8px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: white;
  cursor: pointer;
}

.pagination button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-content {
  background: white;
  border-radius: 16px;
  max-width: 900px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h2 {
  font-size: 18px;
  font-weight: 600;
}

.btn-close {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  background: #f3f4f6;
  font-size: 20px;
  cursor: pointer;
}

.upload-step,
.edit-step {
  padding: 24px;
}

.upload-zone {
  border: 2px dashed #d1d5db;
  border-radius: 12px;
  padding: 40px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.upload-zone:hover,
.upload-zone.drag-over {
  border-color: #3b82f6;
  background: #eff6ff;
}

.upload-placeholder {
  color: #6b7280;
}

.upload-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.hint {
  font-size: 12px;
  color: #9ca3af;
}

.preview-container {
  position: relative;
}

.preview-container img {
  max-width: 100%;
  max-height: 300px;
  border-radius: 8px;
}

.btn-reupload {
  position: absolute;
  bottom: 12px;
  right: 12px;
  padding: 6px 12px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.upload-options {
  margin: 20px 0;
}

.upload-options select {
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  margin-left: 8px;
}

.btn-primary {
  width: 100%;
  padding: 12px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover:not(:disabled) { background: #2563eb; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.edit-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.edit-image img {
  width: 100%;
  border-radius: 8px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 14px;
  font-weight: 500;
  color: #374151;
}

.form-group textarea,
.form-group input,
.form-group select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 14px;
}

.form-group textarea {
  resize: vertical;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid #e5e7eb;
  margin-top: 20px;
}

.btn-secondary {
  padding: 10px 20px;
  background: #f3f4f6;
  color: #374151;
  border: none;
  border-radius: 8px;
  cursor: pointer;
}

.btn-secondary:hover { background: #e5e7eb; }

.btn-danger {
  padding: 10px 20px;
  background: #fee2e2;
  color: #dc2626;
  border: none;
  border-radius: 8px;
  cursor: pointer;
}

.btn-danger:hover { background: #fecaca; }

.detail-content {
  padding: 24px;
}

.detail-image {
  margin-bottom: 20px;
}

.detail-image img {
  max-width: 100%;
  border-radius: 8px;
}

.info-section {
  margin-bottom: 20px;
}

.info-section h3 {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 8px;
}

.markdown-content {
  font-size: 14px;
  line-height: 1.6;
  color: #4b5563;
}

.detail-actions {
  display: flex;
  justify-content: space-between;
  padding: 16px 24px;
  border-top: 1px solid #e5e7eb;
}

.detail-actions select {
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

@media (max-width: 768px) {
  .edit-layout {
    grid-template-columns: 1fr;
  }

  .form-row {
    grid-template-columns: 1fr;
  }

  .items-grid {
    grid-template-columns: 1fr;
  }
}
</style>
