/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: "var(--bg-main)",
        panel: "var(--bg-panel)",
        surface: "var(--bg-surface)",

        primary: {
          DEFAULT: "var(--primary)",
          glow: "var(--primary-glow)",
        },
        secondary: "var(--secondary)",

        text: {
          DEFAULT: "var(--text-main)",
          muted: "var(--text-muted)",
        },

        border: "var(--border-light)",
        active: "var(--border-active)",

        success: "var(--accent-success)",
        warning: "var(--accent-warning)",
        error: "var(--accent-error)",
        info: "var(--accent-info)",
      },
      fontFamily: {
        sans: "var(--font-sans)",
        mono: "var(--font-mono)",
      }
    },
  },
  plugins: [],
}
