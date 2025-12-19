<script setup lang="ts">
</script>

<template>
  <div class="bg-slate-50 text-slate-800 font-sans min-h-screen relative overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-700">
    <!-- Background Decoration -->
    <div class="fixed top-0 left-0 w-full h-full overflow-hidden -z-10 pointer-events-none">
      <div class="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-indigo-200/30 rounded-full mix-blend-multiply filter blur-3xl opacity-70 animate-float"></div>
      <div class="absolute top-[20%] right-[-10%] w-[35%] h-[35%] bg-violet-200/30 rounded-full mix-blend-multiply filter blur-3xl opacity-70 animate-float" style="animation-delay: 2s;"></div>
      <div class="absolute bottom-[-10%] left-[20%] w-[40%] h-[40%] bg-blue-200/30 rounded-full mix-blend-multiply filter blur-3xl opacity-70 animate-float" style="animation-delay: 4s;"></div>
    </div>

    <router-view />
  </div>
</template>
