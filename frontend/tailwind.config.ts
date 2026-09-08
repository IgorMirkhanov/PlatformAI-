import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: {
          DEFAULT: "var(--canvas)",
          raised: "var(--canvas-raised)",
          overlay: "var(--canvas-overlay)",
          border: "var(--canvas-border)",
          muted: "var(--canvas-muted)",
          fg: "var(--canvas-fg)",
        },
        surface: {
          DEFAULT: "var(--canvas)",
          raised: "var(--canvas-raised)",
          overlay: "var(--canvas-overlay)",
          border: "var(--canvas-border)",
        },
        accent: {
          DEFAULT: "#6366f1",
          hover: "#818cf8",
          muted: "#4338ca",
          glow: "#7c3aed",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"],
      },
      boxShadow: {
        glow: "0 0 32px rgba(99, 102, 241, 0.18)",
        "glow-purple": "0 0 40px rgba(124, 58, 237, 0.22)",
        node: "0 8px 32px rgba(0, 0, 0, 0.55)",
        soft: "var(--shadow-soft)",
      },
      backgroundImage: {
        "luxury-gradient":
          "linear-gradient(135deg, rgba(99,102,241,0.12) 0%, rgba(124,58,237,0.08) 50%, transparent 100%)",
      },
    },
  },
  plugins: [],
};

export default config;
