import type { Config } from "tailwindcss";

// "Glacier" palette driven by CSS custom properties (see src/index.css) so
// light/dark theming (Step 7 requirement) is a variable swap, not a
// class-per-component rewrite. Each color uses the `hsl(var(--x) /
// <alpha-value>)` form so Tailwind's opacity modifiers (`bg-surface/60`)
// work — required for the glassmorphic panels throughout the UI.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        surface: "hsl(var(--surface) / <alpha-value>)",
        border: "hsl(var(--border) / <alpha-value>)",
        primary: {
          DEFAULT: "hsl(var(--primary) / <alpha-value>)",
          foreground: "hsl(var(--primary-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted) / <alpha-value>)",
          foreground: "hsl(var(--muted-foreground) / <alpha-value>)",
        },
        destructive: "hsl(var(--destructive) / <alpha-value>)",
        success: "hsl(var(--success) / <alpha-value>)",
        warning: "hsl(var(--warning) / <alpha-value>)",
        glow: "hsl(var(--glow) / <alpha-value>)",
      },
      borderRadius: {
        DEFAULT: "0.375rem",
      },
      boxShadow: {
        glow: "0 0 24px -4px hsl(var(--glow) / 0.55)",
        "glow-lg": "0 0 48px -8px hsl(var(--glow) / 0.5)",
        glass: "0 8px 32px -8px hsl(var(--foreground) / 0.18)",
      },
      keyframes: {
        "fade-slide-up": {
          "0%": { opacity: "0", transform: "translateY(10px) scale(0.98)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        "glow-pulse": {
          "0%, 100%": { opacity: "0.55" },
          "50%": { opacity: "1" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-4px)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
        // Three dots that rise in sequence while the model is generating.
        "dot-bounce": {
          "0%, 60%, 100%": { transform: "translateY(0)", opacity: "0.45" },
          "30%": { transform: "translateY(-4px)", opacity: "1" },
        },
      },
      animation: {
        "fade-slide-up": "fade-slide-up 0.45s cubic-bezier(0.16,1,0.3,1) both",
        "glow-pulse": "glow-pulse 2.6s ease-in-out infinite",
        float: "float 6s ease-in-out infinite",
        shimmer: "shimmer 2.5s linear infinite",
        "dot-bounce": "dot-bounce 1.3s ease-in-out infinite",
      },
      backdropBlur: {
        xs: "2px",
      },
    },
  },
  plugins: [],
} satisfies Config;
