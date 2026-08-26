/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: '#3B6CF4',
        teal: {
          DEFAULT: '#3B6CF4',
          dark: '#4F7DFF',
          darker: '#2F59D0',
        },
        gold: {
          light: '#FDF8F3',
          DEFAULT: '#D4AF37',
          dark: '#B8941F',
          darker: '#9A7A1A',
        },
        charcoal: {
          light: '#2A2A2A',
          DEFAULT: '#1A1A1A',
          dark: '#0F0F0F',
        },
        ink: '#E7EAF0',
        mute: '#8B93A7',
        paper: '#0B0F1A',
        line: '#232B3D',
        critical: '#EF4444',
        high: '#F59E0B',
        medium: '#F59E0B',
        safe: '#22C55E',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'Segoe UI', 'sans-serif'],
        display: ['Sora', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['Fira Code', 'ui-monospace', 'SF Mono', 'monospace'],
      },
      boxShadow: {
        card: 'none',
        lift: '0 8px 24px rgba(0,0,0,0.24)',
        nav: 'none',
      },
    },
  },
  plugins: [],
}
