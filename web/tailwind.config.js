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
    // Thang chữ năm bậc cho giao diện + ba bậc tiêu đề. Không dùng cỡ tùy ý `text-[..px]`.
    fontSize: {
      "2xs": ["11px", { lineHeight: "16px" }],
      xs: ["12px", { lineHeight: "16px" }],
      sm: ["13px", { lineHeight: "20px" }],
      base: ["14px", { lineHeight: "20px" }],
      md: ["15px", { lineHeight: "22px" }],
      lg: ["16px", { lineHeight: "24px" }],
      xl: ["20px", { lineHeight: "28px", letterSpacing: "-0.012em" }],
      "2xl": ["24px", { lineHeight: "32px", letterSpacing: "-0.016em" }],
      "3xl": ["28px", { lineHeight: "34px", letterSpacing: "-0.02em" }],
    },
    borderRadius: {
      none: "0",
      sm: "3px",
      DEFAULT: "4px",
      md: "6px",
      lg: "8px",
      xl: "10px",
      full: "9999px",
    },
    extend: {
      colors: {
        surface: v("surface"),
        slate: scale("n", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
        brand: scale("brand", [50, 100, 500, 600, 700]),
        attack: scale("attack", [50, 100, 500, 600, 700]),
        defense: scale("defense", [50, 100, 500, 600, 700]),
        refusal: scale("refusal", [50, 100, 500, 600, 700]),
        payload: scale("payload", [50, 100, 200, 500, 600]),
        canary: scale("canary", [50, 100, 500, 600]),
        amber: scale("amber", [50, 200, 400, 600, 700, 800]),
      },
      boxShadow: {
        pop: "var(--shadow-pop)",
      },
      transitionDuration: {
        DEFAULT: "120ms",
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
