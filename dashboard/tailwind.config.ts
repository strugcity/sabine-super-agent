import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Role colors
        'role-architect': '#9333ea',    // Purple
        'role-backend': '#3b82f6',      // Blue
        'role-frontend': '#22c55e',     // Green
        'role-data': '#f59e0b',         // Amber
        'role-pm': '#ec4899',           // Pink
        'role-qa': '#06b6d4',           // Cyan
        // Event type colors
        'event-started': '#22c55e',
        'event-completed': '#10b981',
        'event-failed': '#ef4444',
        'event-thought': '#8b5cf6',
        'event-tool': '#3b82f6',
        'event-handshake': '#f59e0b',
        // Background
        'gantry-dark': '#0a0a0f',
        'gantry-card': '#111118',
        'gantry-border': '#1e1e2e',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-in': 'slideIn 0.3s ease-out',
      },
      keyframes: {
        slideIn: {
          '0%': { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
export default config
