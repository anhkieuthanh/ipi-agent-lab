// Khối dùng chung của các trang phân tích (Tấn công, Phòng thủ): phạm vi số liệu, tỉ lệ kèm khoảng tin
// cậy, thanh kết cục, đường dẫn sang Lượt chạy đã lọc sẵn.

import clsx from "clsx";

import { Callout, InfoDot, Tooltip } from "@/components/ui";
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

/** Màu theo ngữ nghĩa chung của console; nghĩa luôn đi kèm nhãn ở chú giải và tooltip. */
const OUTCOME_SEG: { key: keyof Outcomes; label: string; cls: string }[] = [
  { key: "success", label: "Tấn công thành công", cls: "bg-attack-500" },
  { key: "defense", label: "Phòng thủ chặn", cls: "bg-defense-500" },
  { key: "model_refusal", label: "Model từ chối", cls: "bg-refusal-500" },
  { key: "harness", label: "Harness chặn", cls: "bg-slate-500" },
  { key: "failed", label: "Không đạt (không ai chặn)", cls: "bg-slate-300" },
  { key: "excluded", label: "Lỗi hạ tầng (loại khỏi mẫu số)", cls: "bg-amber-400" },
];

export function OutcomeBar({ o, className }: { o: Outcomes; className?: string }) {
  const total = OUTCOME_SEG.reduce((acc, s) => acc + (o[s.key] ?? 0), 0);
  if (!total) return null;
  const present = OUTCOME_SEG.filter((s) => o[s.key]);
  const summary = present.map((s) => `${s.label}: ${o[s.key]}`).join(" · ");
  return (
    <Tooltip
      content={
        <ul className="space-y-0.5">
          {present.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span className={clsx("h-2 w-2 shrink-0 rounded-sm", s.cls)} aria-hidden="true" />
              <span className="flex-1">{s.label}</span>
              <span className="num pl-3">{o[s.key]}</span>
            </li>
          ))}
        </ul>
      }
    >
      <div role="img" aria-label={summary} className={clsx("flex h-1.5 w-full min-w-24 gap-px overflow-hidden rounded-sm bg-slate-100", className)}>
        {present.map((s) => (
          <div key={s.key} className={s.cls} style={{ width: `${(o[s.key] / total) * 100}%` }} />
        ))}
      </div>
    </Tooltip>
  );
}

export function OutcomeLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
      {OUTCOME_SEG.map((s) => (
        <span key={s.key} className="inline-flex items-center gap-1.5">
          <span className={clsx("h-2 w-2 shrink-0 rounded-sm", s.cls)} aria-hidden="true" />
          {s.label}
        </span>
      ))}
    </div>
  );
}

/** Tỉ lệ luôn đi kèm mẫu số và khoảng tin cậy. `p` rỗng hiện "—", không bao giờ thành 0%. */
export function Rate({ r, strong = false, good = false }: { r: CiRate; strong?: boolean; good?: boolean }) {
  return (
    <span className="whitespace-nowrap">
      <span
        className={clsx(
          "num",
          strong ? "text-md font-semibold" : "font-medium",
          r.p === null ? "text-slate-400" : good ? "text-slate-800" : r.p > 0 ? "text-attack-600" : "text-slate-700",
        )}
      >
        {pct(r.p)}
      </span>
      <span className="num ml-1.5 text-xs text-slate-500">
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
  const facts = (
    <>
      <span className="num">{int(s.n_batches)}</span> lô · run tấn công theo vai trò lô: <span className="num">{roles || "—"}</span>
      {" · "}
      <span className="num">{nHarness}</span> phiên bản harness (commit)
      {variants.length > 0 && <> · biến thể prompt dò được: {variants.join(", ")}</>}
      {" · "}model: <span className="num">{Object.entries(s.targets).map(([k, n]) => `${k} ${int(n)}`).join(", ")}</span>
      {" · "}phòng thủ: {Object.keys(s.presets).map(presetLabel).join(", ")}
    </>
  );
  if (!mixed)
    return (
      <p className="text-xs leading-[18px] text-slate-500">
        <span className="font-medium text-slate-700">Phạm vi số liệu</span>
        {" — "}
        {facts}
      </p>
    );
  return (
    <Callout
      tone="warn"
      title={
        <span className="inline-flex flex-wrap items-center gap-1.5">
          Số liệu đang gộp nhiều điều kiện khác nhau — đọc như xu hướng, chưa phải kết quả chính thức
          <InfoDot>
            Tập so sánh được = cùng khối thí nghiệm, cùng phiên bản harness và biến thể prompt. Chọn một lô ở thanh phạm vi để xem
            một điều kiện duy nhất.
          </InfoDot>
        </span>
      }
    >
      <div className="text-xs leading-[18px]">{facts}</div>
    </Callout>
  );
}
