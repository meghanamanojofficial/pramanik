// Theme copied from the design's own inline config (signin.html), plus the two plugins the Tailwind CDN loaded.
module.exports = {
  "theme": {
    "extend": {
      "fontFamily": {
        "sans": [
          "Inter",
          "sans-serif"
        ]
      },
      "colors": {
        "obsidian": "#090a0f",
        "cardBg": "#1b1d24",
        "inputBg": "#21242d",
        "btnPrimary": "#b0b5c0",
        "btnSecondary": "#242731",
        "brandRed": "#ea4e58"
      }
    }
  },
  "content": [
    "./signin.html",
    "./js/api.js",
    "./js/ui.js",
    "./js/signin.js"
  ]
};
module.exports.plugins = [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')];
