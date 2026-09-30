import type { Config } from "tailwindcss";

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: { DEFAULT: token("surface"), muted: token("surface-muted"), hover: token("surface-hover") },
        border: { DEFAULT: token("border"), strong: token("border-strong") },
        fg: { DEFAULT: token("fg"), muted: token("fg-muted"), subtle: token("fg-subtle") },
        accent: { DEFAULT: token("accent"), hover: token("accent-hover"), soft: token("accent-soft") },
        success: { DEFAULT: token("success"), soft: token("success-soft") },
        warning: { DEFAULT: token("warning"), soft: token("warning-soft") },
        danger: { DEFAULT: token("danger"), soft: token("danger-soft") },
        info: { DEFAULT: token("info"), soft: token("info-soft") },
      },
      borderRadius: { sm: "4px", DEFAULT: "6px", md: "6px", lg: "8px" },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "ui-sans-serif", "system-ui", "-apple-system", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      fontSize: { "2xs": ["11px", "16px"] },
      transitionDuration: { DEFAULT: "120ms" },
    },
  },
  plugins: [],
};

export default config;
