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
        background: "#020617", // Slate 950 (OLED Deep)
        surface: "#0F172A",    // Slate 900
        panel: "#1E293B",      // Slate 800 (Card/Panel bg)
        primary: "#38BDF8",    // Sky 400 (Active/Focus)
        secondary: "#94A3B8",  // Slate 400 (Muted Text)
        accent: "#0EA5E9",     // Sky 500
        success: "#10B981",    // Emerald 500
        warning: "#F59E0B",    // Amber 500
        error: "#EF4444",      // Red 500
        text: "#F8FAFC",       // Slate 50 (High Contrast)
        muted: "#64748B",      // Slate 500
        border: "#334155",     // Slate 700
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['Fira Code', 'monospace'],
      }
    },
  },
  plugins: [],
}
