<script setup lang="ts">
import { ref } from 'vue'
import ExamList from '@/components/exams/ExamList.vue'

</script>

<template>
  <div class="container mx-auto px-4 py-8 max-w-6xl">
     <div class="mb-6">
        <h1 class="text-3xl font-extrabold text-slate-900 mb-2">
            <span class="mr-2">💬</span> AI 答疑中心
        </h1>
        <p class="text-slate-500 text-lg">选择一份试卷开始智能答疑对话</p>
     </div>
     
     <ExamList />
  </div>
</template>
