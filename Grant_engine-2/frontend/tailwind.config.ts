import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        sidebar: {
          bg: "#0f172a",
          hover: "#1e293b",
          active: "#1d4ed8",
          text: "#94a3b8",
          textActive: "#f1f5f9",
        },
      },
    },
  },
  plugins: [],
};

export default config;
