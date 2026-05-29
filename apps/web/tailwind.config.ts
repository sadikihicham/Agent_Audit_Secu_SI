import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        guardian: {
          bg: "#0b0f14",
        },
      },
    },
  },
  plugins: [],
};

export default config;
