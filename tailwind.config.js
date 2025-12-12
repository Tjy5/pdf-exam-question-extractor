/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./web_interface/templates/**/*.html",
    "./web_interface/static/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#6366f1',    // Indigo 500
        secondary: '#8b5cf6',  // Violet 500
        success: '#10b981',    // Emerald 500
        surface: '#ffffff',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float': 'float 6s ease-in-out infinite',
        'fade-in-up': 'fadeInUp 0.5s ease-out',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        fadeInUp: {
          '0%': {
            opacity: '0',
            transform: 'translateY(10px)'
          },
          '100%': {
            opacity: '1',
            transform: 'translateY(0)'
          }
        }
      }
    }
  },
  plugins: [],
}
