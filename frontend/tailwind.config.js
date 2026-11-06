/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#101820',
          900: '#14202a',
          850: '#172733',
          800: '#1d303d',
        },
        finance: {
          canvas: '#f5f7f8',
          panel: '#ffffff',
          line: '#d9e1e7',
          text: '#17202a',
          muted: '#667482',
          green: '#168a4a',
          red: '#c43d3d',
          amber: '#c98916',
          blue: '#2563eb',
        },
      },
      boxShadow: {
        soft: '0 18px 50px rgba(15, 23, 42, 0.08)',
        panel: '0 1px 2px rgba(15, 23, 42, 0.04), 0 10px 30px rgba(15, 23, 42, 0.06)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
        display: ['Fraunces', 'Source Serif Pro', 'Georgia', 'serif'],
      },
    },
  },
  plugins: [],
}
