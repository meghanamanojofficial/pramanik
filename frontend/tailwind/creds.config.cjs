// Theme copied from the design's own inline config (creds.html), plus the two plugins the Tailwind CDN loaded.
module.exports = {
  "theme": {
    "extend": {
      "colors": {
        "obsidian": "#090a0f",
        "cardBg": "#13151f",
        "inputBg": "#1d1f2b",
        "accentSlate": "#8e96ba"
      },
      "fontFamily": {
        "sans": [
          "Inter",
          "system-ui",
          "-apple-system",
          "sans-serif"
        ]
      }
    }
  },
  "content": [
    "./creds.html",
    "./js/api.js",
    "./js/ui.js",
    "./js/creds.js"
  ]
};
module.exports.plugins = [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')];
