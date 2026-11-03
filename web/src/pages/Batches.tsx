import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Layers } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Badge, Card, Empty, ErrorBox, Loading, PageHeader, RateBar, Segmented } from "@/components/ui";
import { api, type Batch } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, KIND_LABEL, int, kilo, pct, presetLabel, usd, when } from "@/lib/format";
import { KindIcon } from "@/lib/icons";

type Filter = "all" | Batch["kind"];

function Result({ b }: { b: Batch }) {
  if (b.n_attack) {
    const p = b.n_success / b.n_attack;
    return (
      <div className="w-36">
        <div className="mb-1 flex justify-between text-[12.5px]">
          <span className="text-slate-500">ASR</span>
          <span className="num font-medium text-slate-800">
            {pct(p, 0)} · {b.n_success}/{b.n_attack}
          </span>
        </div>
        <RateBar p={p} tone="attack" />
      </div>
    );
  }
  const p = b.n_benign ? b.n_pass / b.n_benign : null;
  return (
    <div className="w-36">
      <div className="mb-1 flex justify-between text-[12.5px]">
        <span className="text-slate-500">USR</span>
        <span className="num font-medium text-slate-800">
          {pct(p, 0)} · {b.n_pass}/{b.n_benign}
        </span>
      </div>
      <RateBar p={p} tone="brand" />
    </div>
  );
}

export function BatchesPage() {
  const [sp, setSp] = useSearchParams();
  const filter = (["all", "experiment", "dryrun", "demo"].includes(sp.get("type") ?? "") ? sp.get("type") : "all") as Filter;
  const [search, setSearch] = useState("");
  const setFilter = (value: Filter) => { const n = new URLSearchParams(sp); if (value === "all") n.delete("type"); else n.set("type", value); setSp(n, { replace: true }); };
  const q = useQuery({ queryKey: ["batches"], refetchInterval: 15_000, queryFn: () => api.batches() });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const all = q.data!;
  const count = (k: Filter) => (k === "all" ? all.length : all.filter((b) => b.kind === k).length);
  const rows = all.filter((b) => (filter === "all" || b.kind === filter) && `${b.batch_id} ${b.targets.join(" ")}`.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <>
      <PageHeader
        title="Lô thực nghiệm"
        info="Mỗi lô là một lần chạy có kiểm soát: cùng harness, bộ model đã pin, chi phí canh theo dự toán. Chạy thử và demo tách riêng, không vào số liệu chính."
        actions={
          <Segmented
            value={filter}
            onChange={setFilter}
            options={(["all", "experiment", "dryrun", "demo"] as Filter[]).map((k) => ({
              value: k,
              label: k === "all" ? "Tất cả" : KIND_LABEL[k],
              count: count(k),
            }))}
          />
        }
      />
      <div className="batch-search-bar"><label><span>Tìm lô hoặc model</span><input className="input" type="search" placeholder="Nhập mã lô, A1, A2…" value={search} onChange={(e) => setSearch(e.target.value)} /></label><span role="status">{int(rows.length)} lô</span></div>
      <Card>
        {rows.length === 0 ? (
          <Empty title="Không có lô phù hợp" icon={<Layers size={20} />} action={search ? <button className="filter-clear" onClick={() => setSearch("")}>Xóa tìm kiếm</button> : undefined}>Thử tìm bằng mã lô hoặc đổi bộ lọc.</Empty>
        ) : (
          <div className="max-w-full overflow-x-auto"><table className="table-base">
            <thead>
              <tr>
                <th>Lô</th>
                <th>Loại</th>
                <th>Nội dung</th>
                <th>Model · phòng thủ</th>
                <th className="text-right">Run</th>
                <th>Kết quả</th>
                <th className="text-right">Token · chi phí</th>
                <th className="text-right">Thời điểm</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.batch_id} className="group hover:bg-slate-50/70">
                  <td className="max-w-[260px]">
                    <Link to={{ pathname: "/runs", search: `?batch=${encodeURIComponent(b.batch_id)}&scope=${b.kind}` }} title={b.batch_id} className="block truncate font-mono text-[12px] font-medium text-brand-600 hover:underline">{b.batch_id}</Link>
                    <div title={b.store} className="mt-0.5 max-w-[240px] truncate text-[12px] text-slate-500">{b.store}</div>
                  </td>
                  <td>
                    <Badge tone={b.kind === "experiment" ? "brand" : b.kind === "demo" ? "payload" : "neutral"}>
                      <KindIcon kind={b.kind} />
                      {KIND_LABEL[b.kind]}
                    </Badge>
                  </td>
                  <td className="text-[13px] text-slate-600">
                    {b.scenario ? (
                      <>
                        <div className="font-medium text-slate-700">
                          {b.scenario.goal} · {GOAL_LABEL[b.scenario.goal]}
                        </div>
                        <div className="text-[12px] text-slate-500">
                          {CHANNEL_LABEL[b.scenario.channel] ?? b.scenario.channel} · {b.scenario.technique} ·{" "}
                          {b.scenario.carrier_task_id}
                        </div>
                      </>
                    ) : b.run_kinds.includes("attack") ? (
                      <>
                        <div className="font-medium text-slate-700">
                          Tấn công{b.manifest?.block ? ` · khối ${b.manifest.block}` : ""}
                        </div>
                        <div className="text-[12px] text-slate-500">{b.channels.join(", ") || "—"}</div>
                      </>
                    ) : (
                      <>
                        <div className="font-medium text-slate-700">Bench hữu dụng</div>
                        <div className="text-[12px] text-slate-500">
                          {b.manifest?.task ? `${b.manifest.task} · ` : ""}câu lành tính
                        </div>
                      </>
                    )}
                  </td>
                  <td className="text-[13px]">
                    <div className="text-slate-700">{b.targets.join(", ")}</div>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {b.presets.map((p) => (
                        <Badge key={p} tone={p === "off" ? "neutral" : "defense"} className="!text-[11px]">
                          {presetLabel(p)}
                        </Badge>
                      ))}
                    </div>
                  </td>
                  <td className="num text-right">
                    {int(b.n_runs)}
                    {b.n_parse_error > 0 && (
                      <div className="text-[11.5px] text-amber-600">{b.n_parse_error} lỗi</div>
                    )}
                  </td>
                  <td>
                    <Result b={b} />
                  </td>
                  <td className="num text-right text-[13px]">
                    <div className="text-slate-700">{kilo(b.tokens)}</div>
                    <div className="text-[12px] text-slate-500">{usd(b.manifest?.spent_usd)}</div>
                  </td>
                  <td className="text-right text-[13px] text-slate-500">{when(b.created_at)}</td>
                  <td className="w-8 pr-4">
                    <Link
                      to={{ pathname: "/runs", search: `?batch=${encodeURIComponent(b.batch_id)}&scope=${b.kind}` }}
                      aria-label={`Xem run của lô ${b.batch_id}`} className="flex h-9 w-9 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                      title="Xem các run"
                    >
                      <ChevronRight size={16} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </Card>
    </>
  );
}
