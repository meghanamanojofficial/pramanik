// Theme copied from the design's own inline config (maindash.html), plus the two plugins the Tailwind CDN loaded.
module.exports = {
  "darkMode": "class",
  "theme": {
    "extend": {
      "colors": {
        "on-secondary-container": "#81c0bc",
        "on-error-container": "#ffdad6",
        "secondary-fixed": "#aeeee9",
        "primary": "#b9c8de",
        "on-primary-fixed-variant": "#39485a",
        "on-secondary-fixed": "#00201e",
        "on-tertiary-container": "#780000",
        "surface-bright": "#38393e",
        "surface-variant": "#343439",
        "surface-container": "#1f1f24",
        "secondary-fixed-dim": "#93d2cd",
        "outline": "#8e9197",
        "tertiary-container": "#ff7966",
        "on-tertiary": "#690000",
        "tertiary-fixed-dim": "#ffb4a8",
        "tertiary-fixed": "#ffdad4",
        "secondary-container": "#00504c",
        "on-surface": "#e3e2e8",
        "surface-container-low": "#1a1b20",
        "inverse-on-surface": "#2f3035",
        "inverse-surface": "#e3e2e8",
        "on-surface-variant": "#c4c6cd",
        "on-background": "#e3e2e8",
        "on-primary-fixed": "#0d1c2d",
        "error-container": "#93000a",
        "on-primary": "#233143",
        "on-primary-container": "#2b394b",
        "surface-container-lowest": "#0d0e12",
        "secondary": "#93d2cd",
        "on-secondary-fixed-variant": "#00504c",
        "error": "#ffb4ab",
        "background": "#121317",
        "surface-container-highest": "#343439",
        "on-secondary": "#003735",
        "inverse-primary": "#516072",
        "primary-fixed": "#d4e4fa",
        "on-tertiary-fixed-variant": "#930100",
        "surface-tint": "#b9c8de",
        "on-error": "#690005",
        "surface": "#121317",
        "primary-fixed-dim": "#b9c8de",
        "outline-variant": "#44474c",
        "tertiary": "#ffb4a8",
        "primary-container": "#94a3b8",
        "surface-dim": "#121317",
        "surface-container-high": "#292a2e",
        "on-tertiary-fixed": "#410000",
        "obsidian": {
          "600": "#323647",
          "700": "#232632",
          "750": "#1c1e27",
          "800": "#171920",
          "850": "#121317",
          "900": "#0d0e12",
          "950": "#090a0d"
        }
      },
      "fontFamily": {
        "sans": [
          "Inter",
          "sans-serif"
        ],
        "mono": [
          "JetBrains Mono",
          "monospace"
        ]
      }
    }
  },
  "content": [
    "./maindash.html",
    "./js/api.js",
    "./js/ui.js",
    "./js/maindash.js"
  ]
};
module.exports.plugins = [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')];
