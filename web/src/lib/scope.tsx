// Phạm vi dữ liệu dùng chung cho mọi trang phân tích, giữ trên URL (?scope=…&batch=…) để chia sẻ
// được đường dẫn. Mặc định chỉ lô thực nghiệm — lô chạy thử và demo không lẫn vào số liệu chính.

import { useSearchParams } from "react-router-dom";

import type { Params } from "./api";

export type ScopeKind = "experiment" | "dryrun" | "demo" | "all";

export const SCOPE_LABEL: Record<ScopeKind, string> = {
  experiment: "Lô thực nghiệm",
  dryrun: "Lô chạy thử",
  demo: "Lượt demo",
  all: "Mọi lô",
};

export function useScope() {
  const [sp, setSp] = useSearchParams();
  const kind = (sp.get("scope") as ScopeKind) || "experiment";
  const batch = sp.get("batch") || "";

  const params: Params = batch
    ? { batch: [batch] }
    : { kind: kind === "all" ? ["experiment", "dryrun", "demo"] : [kind] };

  function setScope(next: { kind?: ScopeKind; batch?: string }) {
    const n = new URLSearchParams(sp);
    if (next.kind !== undefined) {
      n.set("scope", next.kind);
      n.delete("batch");
    }
    if (next.batch !== undefined) {
      if (next.batch) n.set("batch", next.batch);
      else n.delete("batch");
    }
    setSp(n, { replace: true });
  }

  return { kind, batch, params, setScope, search: sp.toString() };
}
