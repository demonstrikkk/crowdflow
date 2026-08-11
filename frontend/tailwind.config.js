/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Legacy Material tokens remapped to the night-ops palette so
        // builder views inherit the command-instrument look.
        "on-primary-container": "#9aa2ab",
        "on-secondary-container": "#9aa2ab",
        "inverse-on-surface": "#11151a",
        "outline": "#3a4149",
        "primary": "#e7eaed",
        "on-surface": "#e7eaed",
        "outline-variant": "#22272e",
        "on-background": "#e7eaed",
        "error": "#ff5c55",
        "on-secondary": "#0a0c0e",
        "surface-tint": "#3a4149",
        "background": "#0a0c0e",
        "primary-container": "#e7eaed",
        "on-primary-fixed-variant": "#9aa2ab",
        "secondary-fixed": "#22272e",
        "on-secondary-fixed": "#e7eaed",
        "primary-fixed-dim": "#3a4149",
        "surface-container-high": "#1c2126",
        "surface-variant": "#171b20",
        "error-container": "#371514",
        "on-tertiary": "#0a0c0e",
        "inverse-primary": "#9aa2ab",
        "on-tertiary-container": "#ffb4ae",
        "surface-bright": "#1c2126",
        "on-error": "#0a0c0e",
        "on-primary-fixed": "#0a0c0e",
        "tertiary-container": "#331312",
        "surface-dim": "#0d0f12",
        "on-surface-variant": "#9aa2ab",
        "secondary": "#9aa2ab",
        "secondary-container": "#171b20",
        "on-error-container": "#ffb4ae",
        "primary-fixed": "#e7eaed",
        "surface-container-low": "#121519",
        "surface": "#121519",
        "tertiary-fixed-dim": "#ffb4ae",
        "on-primary": "#0a0c0e",
        "surface-container-lowest": "#0d0f12",
        "on-tertiary-fixed-variant": "#ffb4ae",
        "tertiary-fixed": "#331312",
        "surface-container": "#171b20",
        "tertiary": "#ff5c55",
        "on-tertiary-fixed": "#371514",
        "surface-container-highest": "#22282e",
        "on-secondary-fixed-variant": "#9aa2ab",
        "secondary-fixed-dim": "#3a4149",
        "inverse-surface": "#e7eaed"
      },
      borderRadius: {
        "DEFAULT": "0px",
        "lg": "0px",
        "xl": "0px",
        "full": "0px"
      },
      // Container widths for `max-w-*` come from Tailwind's `--container-*`
      // namespace (defaults: md 28rem, xl 36rem, 2xl 42rem, ...). Do NOT
      // define custom `spacing` keys named md/xl/2xl/etc here — they shadow
      // the container namespace and collapse `max-w-*` utilities to px values.
      fontFamily: {
        sans: ["Syne", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
        "display-xl": ["Syne", "sans-serif"],
        "label-caps": ["JetBrains Mono", "monospace"],
        "body-sm": ["JetBrains Mono", "monospace"],
        "headline-lg": ["Syne", "sans-serif"],
        "title-md": ["JetBrains Mono", "monospace"],
        "body-lg": ["JetBrains Mono", "monospace"],
        "headline-lg-mobile": ["Syne", "sans-serif"],
        "display-2xl": ["Syne", "sans-serif"],
        code: ["JetBrains Mono", "monospace"]
      },
    },
  },
  plugins: [],
}
