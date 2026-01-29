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

        // Compatibility Mappings
        card: "var(--bg-panel)",
        "card-foreground": "var(--text-main)",
        popover: "var(--bg-panel)",
        "popover-foreground": "var(--text-main)",
        muted: "var(--bg-surface)",
        "muted-foreground": "var(--text-muted)",
        accent: "var(--bg-surface)",
        "accent-foreground": "var(--text-main)",
        foreground: "var(--text-main)",

        primary: {
          DEFAULT: "var(--primary)",
          glow: "var(--primary-glow)",
          foreground: "#000000",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "#ffffff"
        },
        destructive: {
          DEFAULT: "var(--accent-error)",
          foreground: "#ffffff"
        },

        text: {
          DEFAULT: "var(--text-main)",
          muted: "var(--text-muted)",
          dim: "var(--text-dim)",
        },

        border: "var(--border-light)",
        active: "var(--border-active)",
        input: "var(--border-light)",
        ring: "var(--primary)",

        success: "var(--accent-success)",
        warning: "var(--accent-warning)",
        error: "var(--accent-error)",
        info: "var(--accent-info)",
        "ios-green": "var(--ios-green)",
      },
      fontFamily: {
        display: "var(--font-display)",
        sans: "var(--font-sans)",
        mono: "var(--font-mono)",
      }
    },
  },
  plugins: [],
}
