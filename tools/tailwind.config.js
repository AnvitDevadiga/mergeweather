/** Tailwind config for the HTML report. Rebuild CSS with: make css */
module.exports = {
  darkMode: "class",
  content: ["./src/mergeweather/html_report.py", "./src/mergeweather/assets/report.js"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
};
