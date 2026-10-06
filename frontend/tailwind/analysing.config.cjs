// Theme copied from the design's own inline config (analysing.html), plus the two plugins the Tailwind CDN loaded.
module.exports = {
  "theme": {
    "extend": {
      "colors": {
        "canvas": "#0a0b10",
        "cardBg": "rgba(23, 25, 34, 0.72)",
        "cardBorder": "rgba(255, 255, 255, 0.08)",
        "mutedIcon": "#717684",
        "pendingBorder": "#424652",
        "activeBlue": "#3b82f6",
        "scanGlow": "#e2e8f0"
      },
      "fontFamily": {
        "sans": [
          "Inter",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif"
        ]
      }
    }
  },
  "content": [
    "./analysing.html",
    "./js/api.js",
    "./js/ui.js",
    "./js/analysing.js"
  ]
};
module.exports.plugins = [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')];
