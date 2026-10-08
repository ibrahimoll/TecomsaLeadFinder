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
      borderRadius: { sm: "6px", DEFAULT: "8px", md: "8px", lg: "12px", xl: "16px" },
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "Segoe UI", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Poppins", "var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      fontSize: { "2xs": ["11px", "16px"] },
      boxShadow: {
        xs: "0 1px 2px rgb(var(--fg) / 0.04)",
        card: "0 1px 2px rgb(var(--fg) / 0.04), 0 1px 1px rgb(var(--fg) / 0.02)",
        "card-hover": "0 2px 8px -2px rgb(var(--fg) / 0.08)",
        panel: "0 1px 3px rgb(var(--fg) / 0.06), 0 1px 2px rgb(var(--fg) / 0.04)",
      },
      transitionDuration: { DEFAULT: "120ms" },
      keyframes: {
        "pop-in": { from: { opacity: "0", transform: "translateY(-4px) scale(0.98)" }, to: { opacity: "1", transform: "none" } },
        "slide-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        "page-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
        "grow-x": { from: { transform: "scaleX(0)" }, to: { transform: "scaleX(1)" } },
        float: { "0%, 100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-4px)" } },
        "toast-in": { from: { opacity: "0", transform: "translateY(12px) scale(0.97)" }, to: { opacity: "1", transform: "none" } },
        "row-flash": { "0%": { backgroundColor: "rgb(var(--accent) / 0.16)" }, "100%": { backgroundColor: "transparent" } },
        "content-in": { from: { opacity: "0", filter: "blur(3px)" }, to: { opacity: "1", filter: "blur(0)" } },
        "slide-in-top": {
          "0%": { opacity: "0", transform: "translateY(-10px)", backgroundColor: "rgb(var(--accent) / 0.10)" },
          "60%": { opacity: "1", transform: "none", backgroundColor: "rgb(var(--accent) / 0.10)" },
          "100%": { backgroundColor: "transparent" },
        },
      },
      animation: {
        "pop-in": "pop-in 120ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "slide-up": "slide-up 160ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "page-in": "page-in 220ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "grow-x": "grow-x 450ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        float: "float 4s ease-in-out infinite",
        "toast-in": "toast-in 260ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "row-flash": "row-flash 1.6s ease-out",
        "content-in": "content-in 320ms ease-out both",
        "slide-in-top": "slide-in-top 1.4s cubic-bezier(0.2, 0.8, 0.2, 1) both",
      },
    },
  },
  plugins: [],
};

export default config;
