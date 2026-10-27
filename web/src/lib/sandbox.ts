// Model thử ngoài bộ đo đã lưu trên trang Cấu hình, dùng ở Phòng thí nghiệm. Lưu trong trình duyệt
// của người xem (tiện ích cá nhân, không phải cấu hình lab): server không ghi gì vào config/ hay .env.
// Mỗi lượt demo gửi kèm model này, API kiểm lại theo khối `sandbox` của config/models.yaml.

import { useEffect, useState } from "react";

import type { SandboxModel } from "./api";

/** target_id của model thử — trùng `SANDBOX_ID` ở src/agent/llm_client.py. */
export const SANDBOX_ID = "sandbox";

const KEY = "ipi.sandbox-model";
const EVENT = "ipi:sandbox-model";

function read(): SandboxModel | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SandboxModel) : null;
  } catch {
    return null;
  }
}

export function useSandboxModel(): [SandboxModel | null, (m: SandboxModel | null) => void] {
  const [model, setModel] = useState<SandboxModel | null>(read);
  useEffect(() => {
    const sync = () => setModel(read());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  function save(m: SandboxModel | null) {
    try {
      if (m) localStorage.setItem(KEY, JSON.stringify(m));
      else localStorage.removeItem(KEY);
    } catch {
      // Trình duyệt chặn lưu trữ: vẫn dùng được trong phiên hiện tại.
    }
    setModel(m);
    window.dispatchEvent(new Event(EVENT));
  }

  return [model, save];
}
