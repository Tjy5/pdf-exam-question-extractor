<script setup lang="ts">
import Navbar from '@/components/layout/Navbar.vue'
</script>

<template>
  <div class="flex flex-col bg-slate-50 text-slate-800 font-sans h-screen relative overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-700">
    <Navbar />
    <!-- Background Decoration -->
    <router-view />
  </div>
</template>
