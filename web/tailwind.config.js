/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        surface: "#0f141a",
        panel: "#161d26",
        edge: "#232c38",
        muted: "#8a97a8",
        brand: "#4f9cf0",
      },
    },
  },
  plugins: [],
};
