/** Design tokens matched to the FinLit Ventures x ProduScope deck. Rebuild CSS with: npm run build:css */
module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/app.js"],
  theme: {
    extend: {
      colors: {
        paper: "#F0EEE9",   // deck background
        ink: "#2B2B2B",     // deck charcoal
        muted: "#66625C",
        line: "#DCD7CE",
        faint: "#E7E3DB",
        taupe: "#9C968C",   // deck grey bars
        brand: { DEFAULT: "#C9411F", bright: "#DD4B2B", 700: "#A9351A", soft: "#FBE6DE", tint: "#F6D3C6" },
        moss: { DEFAULT: "#2F7552", soft: "#E3F1E8" },
        amber: { DEFAULT: "#8A5A00", soft: "#FBEFD2" },  // caution: mustard, distinct from brand orange
        cost: { DEFAULT: "#A33A2C", soft: "#F8E5E1" },
      },
      fontFamily: {
        sans: ['"Inter"', "system-ui", "-apple-system", "Segoe UI", "Roboto", "Arial", "sans-serif"],
        display: ['"Inter Tight"', '"Inter"', "Helvetica Neue", "Arial", "sans-serif"],
      },
      maxWidth: { page: "76rem" },
    },
  },
  plugins: [],
};
