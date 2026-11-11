// Chế độ sáng/tối. Lựa chọn lưu ở localStorage; "system" đi theo hệ điều hành.
// index.html áp `data-theme` trước khi React chạy để không nháy màu.

import { useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const KEY = "ipi-theme";

function stored(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function resolve(choice: ThemeChoice): "light" | "dark" {
  if (choice !== "system") return choice;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(stored);
  const [resolved, setResolved] = useState<"light" | "dark">(() => resolve(stored()));

  useEffect(() => {
    const apply = () => {
      const r = resolve(choice);
      document.documentElement.dataset.theme = r;
      setResolved(r);
    };
    apply();
    try {
      if (choice === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, choice);
    } catch {
      /* không lưu được thì vẫn đổi cho phiên này */
    }
    if (choice !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [choice]);

  return { choice, resolved, setChoice, toggle: () => setChoice(resolved === "dark" ? "light" : "dark") };
}
