import type { Config } from "tailwindcss";

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        sidebar: token("sidebar"),
        surface: { DEFAULT: token("surface"), muted: token("surface-muted"), hover: token("surface-hover") },
        border: { DEFAULT: token("border"), strong: token("border-strong") },
        fg: { DEFAULT: token("fg"), muted: token("fg-muted"), subtle: token("fg-subtle") },
        ink: { DEFAULT: token("ink"), hover: token("ink-hover") },
        accent: { DEFAULT: token("accent"), hover: token("accent-hover"), soft: token("accent-soft") },
        success: { DEFAULT: token("success"), soft: token("success-soft") },
        warning: { DEFAULT: token("warning"), soft: token("warning-soft") },
        danger: { DEFAULT: token("danger"), soft: token("danger-soft") },
        info: { DEFAULT: token("info"), soft: token("info-soft") },
      },
      borderRadius: { sm: "4px", DEFAULT: "6px", md: "6px", lg: "8px" },
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "Segoe UI", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      fontSize: { "2xs": ["11px", "16px"] },
      transitionDuration: { DEFAULT: "120ms" },
      keyframes: {
        "pop-in": { from: { opacity: "0", transform: "translateY(-4px) scale(0.98)" }, to: { opacity: "1", transform: "none" } },
        "slide-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: {
        "pop-in": "pop-in 120ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "slide-up": "slide-up 160ms cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
