// Khối dùng chung của các trang phân tích (Tấn công, Phòng thủ): phạm vi số liệu, tỉ lệ kèm khoảng tin
// cậy, thanh kết cục, đường dẫn sang Lượt chạy đã lọc sẵn.

import clsx from "clsx";
import { AlertTriangle, Info } from "lucide-react";

import { Callout } from "@/components/ui";
import type { CiRate, Outcomes, ScopeProfile } from "@/lib/api";
import { ROLE_LABEL, ci, int, pct, presetLabel } from "@/lib/format";
import { useScope } from "@/lib/scope";

/** Đường dẫn sang Lượt chạy, giữ phạm vi đang xem và lọc sẵn theo ô vừa bấm. */
export function useRunsLink() {
  const { search } = useScope();
  return (filters: Record<string, string | string[] | undefined>) => {
    const sp = new URLSearchParams(search);
    sp.delete("page");
    sp.set("run_kind", "attack");
    for (const [k, v] of Object.entries(filters)) {
      if (v === undefined) continue;
      (Array.isArray(v) ? v : [v]).forEach((x) => sp.append(k, x));
    }
    return `/runs?${sp}`;
  };
}

const OUTCOME_SEG: { key: keyof Outcomes; label: string; cls: string }[] = [
  { key: "success", label: "Tấn công thành công", cls: "bg-attack-500" },
  { key: "defense", label: "Phòng thủ chặn", cls: "bg-defense-500" },
  { key: "model_refusal", label: "Model từ chối", cls: "bg-amber-400" },
  { key: "harness", label: "Harness chặn", cls: "bg-slate-500" },
  { key: "failed", label: "Không đạt (không ai chặn)", cls: "bg-slate-200" },
  { key: "excluded", label: "Lỗi hạ tầng (loại khỏi mẫu số)", cls: "bg-[repeating-linear-gradient(45deg,#e2e8f0_0_3px,#fff_3px_6px)]" },
];

export function OutcomeBar({ o, className }: { o: Outcomes; className?: string }) {
  const total = OUTCOME_SEG.reduce((acc, s) => acc + (o[s.key] ?? 0), 0);
  if (!total) return null;
  const title = OUTCOME_SEG.filter((s) => o[s.key]).map((s) => `${s.label}: ${o[s.key]}`).join(" · ");
  return (
    <div className={clsx("flex h-2 w-full overflow-hidden rounded-full bg-slate-100", className)} title={title}>
      {OUTCOME_SEG.map((s) =>
        o[s.key] ? <div key={s.key} className={s.cls} style={{ width: `${(o[s.key] / total) * 100}%` }} /> : null,
      )}
    </div>
  );
}

export function OutcomeLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-slate-500">
      {OUTCOME_SEG.map((s) => (
        <span key={s.key} className="inline-flex items-center gap-1.5">
          <span className={clsx("h-2.5 w-2.5 rounded-sm", s.cls)} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

export function Rate({ r, strong = false, good = false }: { r: CiRate; strong?: boolean; good?: boolean }) {
  return (
    <span className="whitespace-nowrap">
      <span className={clsx("num", strong ? "text-[15px] font-semibold" : "font-medium", good ? "text-slate-800" : (r.p ?? 0) > 0 ? "text-attack-600" : "text-slate-700")}>
        {pct(r.p)}
      </span>
      <span className="num ml-1.5 text-[11.5px] text-slate-400">
        {r.x}/{r.n}
        {r.n > 0 && ` · ${ci(r.lo, r.hi)}`}
      </span>
    </span>
  );
}

export function ScopeNote({ s }: { s: ScopeProfile }) {
  const roles = Object.entries(s.roles).map(([k, n]) => `${ROLE_LABEL[k] ?? k} ${int(n)}`).join(" · ");
  const nHarness = Object.keys(s.harness_versions).length;
  const variants = Object.keys(s.prompt_variants).filter((v) => v !== "∅");
  const mixed = s.mixed.length > 0;
  return (
    <Callout
      tone={mixed ? "warn" : "brand"}
      icon={mixed ? <AlertTriangle size={16} /> : <Info size={16} />}
      title={mixed ? "Số liệu đang gộp nhiều điều kiện khác nhau — đọc như xu hướng, chưa phải kết quả chính thức" : "Phạm vi số liệu"}
    >
      <div className="space-y-0.5 text-[12.5px]">
        <div>
          {int(s.n_batches)} lô · run tấn công theo vai trò lô: {roles || "—"}
        </div>
        <div>
          {nHarness} phiên bản harness (commit)
          {variants.length > 0 && <> · biến thể prompt dò được: {variants.join(", ")}</>}
          {" · "}model: {Object.entries(s.targets).map(([k, n]) => `${k} ${int(n)}`).join(", ")}
          {" · "}phòng thủ: {Object.keys(s.presets).map(presetLabel).join(", ")}
        </div>
        {mixed && (
          <div className="pt-1 text-[12px] opacity-90">
            Tập so sánh được = cùng khối thí nghiệm, cùng phiên bản harness và biến thể prompt. Chọn một lô ở thanh phạm vi để xem
            một điều kiện duy nhất.
          </div>
        )}
      </div>
    </Callout>
  );
}
