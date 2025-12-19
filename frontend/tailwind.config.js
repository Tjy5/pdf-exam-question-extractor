/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      animation: {
        'float': 'float 6s ease-in-out infinite',
        'fade-in-up': 'fadeInUp 0.3s ease-out',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-20px)' },
        },
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animationDelay: {
        '100': '100ms',
        '200': '200ms',
      },
    },
  },
  plugins: [
    function ({ addUtilities }) {
      addUtilities({
        '.delay-100': {
          'animation-delay': '100ms',
        },
        '.delay-200': {
          'animation-delay': '200ms',
        },
      })
    },
  ],
}
