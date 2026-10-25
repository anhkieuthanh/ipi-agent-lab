/** Design system của IPI Guard Console — màu ngữ nghĩa dùng thống nhất trên mọi trang:
 *  attack (đỏ) = tấn công thành công · defense (xanh lá) = phòng thủ chặn ·
 *  refusal (tím) = model tự từ chối · payload (cam) · canary (xanh dương). */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Be Vietnam Pro"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        ink: { 950: "#0b1020", 900: "#111831", 800: "#1a2342", 700: "#26305a", 600: "#3a4577" },
        brand: { 50: "#eef4ff", 100: "#dae6ff", 500: "#3b6cf6", 600: "#2a55e0", 700: "#2145b8" },
        attack: { 50: "#fef2f2", 100: "#fee2e2", 500: "#e5484d", 600: "#d0353a", 700: "#a8262b" },
        defense: { 50: "#ecfdf3", 100: "#d1fadf", 500: "#16a34a", 600: "#15803d", 700: "#166534" },
        refusal: { 50: "#f5f3ff", 100: "#ede9fe", 500: "#8b5cf6", 600: "#7c3aed", 700: "#6d28d9" },
        payload: { 50: "#fff7ed", 100: "#ffedd5", 500: "#f97316", 600: "#ea580c" },
        canary: { 50: "#eff6ff", 100: "#dbeafe", 500: "#3b82f6", 600: "#2563eb" },
      },
      keyframes: {
        dash: { to: { strokeDashoffset: "-28" } },
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)",
        pop: "0 12px 32px -8px rgba(16,24,40,.18)",
      },
    },
  },
  plugins: [],
};
