// Theme copied from the design's own inline config (result.html), plus the two plugins the Tailwind CDN loaded.
module.exports = {
  "darkMode": "class",
  "theme": {
    "extend": {
      "colors": {
        "obsidian": {
          "600": "#2c303e",
          "700": "#222530",
          "750": "#1a1d26",
          "800": "#161820",
          "850": "#12141a",
          "900": "#0e1015",
          "950": "#090a0d"
        }
      },
      "fontFamily": {
        "sans": [
          "Inter",
          "system-ui",
          "-apple-system",
          "sans-serif"
        ],
        "mono": [
          "JetBrains Mono",
          "ui-monospace",
          "monospace"
        ]
      }
    }
  },
  "content": [
    "./result.html",
    "./js/api.js",
    "./js/ui.js",
    "./js/result.js"
  ]
};
module.exports.plugins = [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')];
