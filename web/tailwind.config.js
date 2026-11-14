/** Tailwind chỉ là lớp ánh xạ: mọi giá trị màu và chữ lấy từ src/tokens.css.
 *  Thang trung tính `slate` và các màu ngữ nghĩa trỏ tới biến CSS nên tự đổi theo chế độ sáng/tối. */

const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
const scale = (name, shades) => Object.fromEntries(shades.map((s) => [s, v(`${name}-${s}`)]));

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    fontFamily: {
      sans: ["var(--font-sans)"],
      mono: ["var(--font-mono)"],
    },
    // Thang chữ (tỉ lệ ~1.15). Thân 14px để đọc được trên máy chiếu; số đo lớn dùng 3xl–4xl.
    // Không dùng cỡ tùy ý `text-[..px]`.
    fontSize: {
      "2xs": ["12px", { lineHeight: "16px" }],
      xs: ["13px", { lineHeight: "18px" }],
      sm: ["14px", { lineHeight: "22px" }],
      base: ["15px", { lineHeight: "24px" }],
      md: ["16px", { lineHeight: "24px" }],
      lg: ["18px", { lineHeight: "26px", letterSpacing: "-0.01em" }],
      xl: ["22px", { lineHeight: "28px", letterSpacing: "-0.015em" }],
      "2xl": ["28px", { lineHeight: "34px", letterSpacing: "-0.02em" }],
      "3xl": ["36px", { lineHeight: "40px", letterSpacing: "-0.03em" }],
      "4xl": ["48px", { lineHeight: "50px", letterSpacing: "-0.035em" }],
    },
    borderRadius: {
      none: "0",
      sm: "3px",
      DEFAULT: "4px",
      md: "6px",
      lg: "10px",
      xl: "12px",
      full: "9999px",
    },
    extend: {
      colors: {
        ground: v("ground"),
        surface: v("surface"),
        "accent-ink": v("accent-ink"),
        muted: v("text-muted"),
        slate: scale("n", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
        brand: scale("brand", [50, 100, 500, 600, 700]),
        attack: scale("attack", [50, 100, 200, 500, 600, 700]),
        defense: scale("defense", [50, 100, 200, 500, 600, 700]),
        refusal: scale("refusal", [50, 100, 200, 500, 600, 700]),
        payload: scale("payload", [50, 100, 200, 500, 600, 700]),
        canary: scale("canary", [50, 100, 200, 500, 600, 700]),
        amber: scale("amber", [50, 200, 400, 600, 700, 800]),
      },
      transitionTimingFunction: {
        DEFAULT: "var(--ease-out)",
      },
      boxShadow: {
        pop: "var(--shadow-pop)",
      },
      transitionDuration: {
        DEFAULT: "140ms",
      },
      keyframes: {
        dash: { to: { strokeDashoffset: "-28" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        shimmer: "shimmer 1.4s infinite",
      },
    },
  },
  plugins: [],
};
