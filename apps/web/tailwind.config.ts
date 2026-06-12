import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{astro,html,js,jsx,md,mdx,ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "#17212b",
        muted: "#607080",
        paper: "#f7f5ef",
        panel: "#fffdfa",
        line: "#d7d1c4",
        deterministic: "#1f7a68",
        llm: "#7b4ab0",
        uncertainty: "#8f4a12",
        provenance: "#2866a5",
        danger: "#b23b3b"
      },
      boxShadow: {
        soft: "0 16px 50px rgba(23, 33, 43, 0.08)"
      }
    }
  },
  plugins: []
};

export default config;
