/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: {
          900: "#0b0f1c",
          800: "#101626",
          700: "#141c31",
          600: "#1d2742",
          500: "#28324f",
        },
        ink: {
          100: "#f5f7ff",
          200: "#d7ddf1",
          300: "#aeb8d6",
          400: "#8995b8",
        },
        accent: {
          500: "#5b6bff",
          600: "#4958f0",
          700: "#3b45c7",
        },
        glow: {
          cyan: "#5cf4ff",
          violet: "#8d7bff",
          magenta: "#ff63c3",
        },
      },
      borderRadius: {
        xl: "1.25rem",
        "2xl": "1.75rem",
      },
      boxShadow: {
        panel: "0 30px 80px rgba(0, 0, 0, 0.45)",
        soft: "0 12px 40px rgba(0, 0, 0, 0.35)",
        glow: "0 0 40px rgba(91, 107, 255, 0.35)",
      },
      fontFamily: {
        display: ["\"Space Grotesk\"", "sans-serif"],
        body: ["\"IBM Plex Sans\"", "sans-serif"],
      },
      backgroundImage: {
        "radial-slate":
          "radial-gradient(circle at top, rgba(91, 107, 255, 0.2), transparent 55%), radial-gradient(circle at 20% 30%, rgba(92, 244, 255, 0.18), transparent 45%), radial-gradient(circle at 80% 20%, rgba(255, 99, 195, 0.15), transparent 55%)",
        "panel-glass":
          "linear-gradient(135deg, rgba(24, 30, 50, 0.85), rgba(16, 22, 38, 0.9))",
      },
      keyframes: {
        fadeInUp: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseGlow: {
          "0%, 100%": { opacity: "0.4" },
          "50%": { opacity: "0.8" },
        },
      },
      animation: {
        "fade-in-up": "fadeInUp 0.6s ease-out forwards",
        "pulse-glow": "pulseGlow 3s ease-in-out infinite",
      },
    },
  },
  plugins: [],
}
