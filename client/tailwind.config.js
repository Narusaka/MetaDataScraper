/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0F172A", // Slate 900
        surface: "#1E293B",    // Slate 800
        primary: "#8B5CF6",    // Violet 500
        secondary: "#06B6D4",  // Cyan 500
        accent: "#F43F5E",     // Rose 500
        text: "#F8FAFC",       // Slate 50
        muted: "#94A3B8",      // Slate 400
      }
    },
  },
  plugins: [],
}
