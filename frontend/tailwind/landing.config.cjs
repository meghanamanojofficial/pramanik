// Theme copied from the design's own inline config (landing page from Stitch).
module.exports = {
  "darkMode": "class",
  "theme": {
    "extend": {
      "colors": {
        "surface-variant": "#343439",
        "on-primary-fixed": "#0d1c2d",
        "surface-container-high": "#292a2e",
        "on-tertiary-container": "#780000",
        "surface-dim": "#121317",
        "error-container": "#93000a",
        "surface-tint": "#b9c8de",
        "on-primary-container": "#2b394b",
        "surface-container-low": "#1a1b20",
        "inverse-surface": "#e3e2e8",
        "tertiary": "#ffb4a8",
        "primary": "#b9c8de",
        "surface-container": "#1f1f24",
        "on-secondary": "#003735",
        "background": "#121317",
        "inverse-on-surface": "#2f3035",
        "inverse-primary": "#516072",
        "on-secondary-fixed-variant": "#00504c",
        "outline-variant": "#44474c",
        "secondary": "#93d2cd",
        "tertiary-fixed-dim": "#ffb4a8",
        "on-primary": "#233143",
        "surface": "#121317",
        "secondary-fixed": "#aeeee9",
        "tertiary-container": "#ff7966",
        "on-tertiary": "#690000",
        "primary-fixed-dim": "#b9c8de",
        "tertiary-fixed": "#ffdad4",
        "on-secondary-fixed": "#00201e",
        "error": "#ffb4ab",
        "secondary-container": "#00504c",
        "on-secondary-container": "#81c0bc",
        "on-primary-fixed-variant": "#39485a",
        "on-error-container": "#ffdad6",
        "primary-container": "#94a3b8",
        "surface-container-highest": "#343439",
        "on-surface": "#e3e2e8",
        "on-background": "#e3e2e8",
        "on-error": "#690005",
        "on-tertiary-fixed-variant": "#930100",
        "surface-bright": "#38393e",
        "on-surface-variant": "#c4c6cd",
        "primary-fixed": "#d4e4fa",
        "outline": "#8e9197",
        "surface-container-lowest": "#0d0e12",
        "secondary-fixed-dim": "#93d2cd",
        "on-tertiary-fixed": "#410000"
      },
      "borderRadius": {
        "DEFAULT": "0.25rem",
        "lg": "0.5rem",
        "xl": "0.75rem",
        "full": "9999px"
      },
      "spacing": {
        "space-sm": "0.5rem",
        "space-md": "1rem",
        "space-lg": "1.5rem",
        "space-xl": "2.5rem",
        "margin": "2rem",
        "gutter": "1.5rem",
        "space-xs": "0.25rem"
      },
      "fontFamily": {
        "headline-lg": [
          "Inter"
        ],
        "body-sm": [
          "Inter"
        ],
        "body-lg": [
          "Inter"
        ],
        "headline-md": [
          "Inter"
        ],
        "label-caps": [
          "Inter"
        ],
        "code-sm": [
          "JetBrains Mono"
        ],
        "label-sm": [
          "Inter"
        ],
        "headline-xl": [
          "Inter"
        ],
        "display-brand": [
          "Inter"
        ],
        "body-md": [
          "Inter"
        ]
      },
      "fontSize": {
        "headline-lg": [
          "22px",
          {
            "lineHeight": "30px",
            "letterSpacing": "-0.01em",
            "fontWeight": "700"
          }
        ],
        "body-sm": [
          "13px",
          {
            "lineHeight": "18px",
            "fontWeight": "400"
          }
        ],
        "body-lg": [
          "16px",
          {
            "lineHeight": "24px",
            "fontWeight": "400"
          }
        ],
        "headline-md": [
          "18px",
          {
            "lineHeight": "26px",
            "letterSpacing": "-0.01em",
            "fontWeight": "600"
          }
        ],
        "label-caps": [
          "11px",
          {
            "lineHeight": "14px",
            "letterSpacing": "0.08em",
            "fontWeight": "700"
          }
        ],
        "code-sm": [
          "12px",
          {
            "lineHeight": "16px",
            "fontWeight": "500"
          }
        ],
        "label-sm": [
          "12px",
          {
            "lineHeight": "16px",
            "fontWeight": "500"
          }
        ],
        "headline-xl": [
          "28px",
          {
            "lineHeight": "36px",
            "letterSpacing": "-0.02em",
            "fontWeight": "700"
          }
        ],
        "display-brand": [
          "32px",
          {
            "lineHeight": "40px",
            "letterSpacing": "0.35em",
            "fontWeight": "900"
          }
        ],
        "body-md": [
          "14px",
          {
            "lineHeight": "20px",
            "fontWeight": "400"
          }
        ]
      }
    }
  },
  "content": [
    "./landing.html",
    "./js/landing.js"
  ]
};
