import type { Config } from "tailwindcss";

// Semantic tokens map to CSS variables defined in globals.css (space-separated RGB
// channels, so Tailwind's `/<alpha-value>` still works). Components reference these
// tokens — never raw hex (see DESIGN.md §2).
const withAlpha = (v: string) => `rgb(var(${v}) / <alpha-value>)`;

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: withAlpha("--surface"),
        panel: withAlpha("--panel"),
        card: withAlpha("--card"),
        ink: withAlpha("--ink"),
        muted: withAlpha("--muted"),
        faint: withAlpha("--faint"),
        line: {
          DEFAULT: withAlpha("--line"),
          strong: withAlpha("--line-strong"),
        },
        accent: {
          DEFAULT: withAlpha("--accent"),
          strong: withAlpha("--accent-strong"),
          soft: withAlpha("--accent-soft"),
        },
        ok: { fg: withAlpha("--ok-fg"), bg: withAlpha("--ok-bg") },
        warn: { fg: withAlpha("--warn-fg"), bg: withAlpha("--warn-bg") },
        bad: { fg: withAlpha("--bad-fg"), bg: withAlpha("--bad-bg") },
        cat: {
          earnings: withAlpha("--cat-earnings"),
          policy: withAlpha("--cat-policy"),
          ma: withAlpha("--cat-ma"),
          rumor: withAlpha("--cat-rumor"),
          sector: withAlpha("--cat-sector"),
          other: withAlpha("--cat-other"),
        },
      },
      // Local-first (V1): a system sans stack — no runtime/external font fetch. On a
      // Mac this resolves to San Francisco, on Windows to Segoe UI, etc.
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "PingFang SC",
          "Hiragino Sans GB",
          "Microsoft YaHei",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SF Mono",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
      },
      boxShadow: {
        // dark elevation = layered material (inset highlight lives in .card)
        card: "0 1px 2px rgb(0 0 0 / 0.3)",
        cardHover: "0 8px 32px rgb(0 0 0 / 0.5)",
      },
      borderRadius: { xl: "0.75rem" },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: { "fade-in": "fade-in 0.24s ease-out both" },
    },
  },
  plugins: [],
};

export default config;
