import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Search } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, Segmented } from "@/components/ui";
import { api, type Batch } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, KIND_LABEL, int, kilo, pct, presetLabel, usd, when } from "@/lib/format";

type Filter = "all" | Batch["kind"];

/** Một dòng: chỉ số (ASR với lô tấn công, USR với lô lành tính), tỉ lệ, tử số/mẫu số.
 * Lô không có mẫu thì ghi "Chưa đo", không hiện 0%. */
function Result({ b }: { b: Batch }) {
  const attack = b.n_attack > 0;
  const n = attack ? b.n_attack : b.n_benign;
  const k = attack ? b.n_success : b.n_pass;
  const p = n ? k / n : null;
  return (
    <span className="num inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="w-8 font-mono text-2xs text-slate-400" title={attack ? "Tỉ lệ tấn công thành công" : "Tỉ lệ câu lành tính đạt"}>
        {attack ? "ASR" : "USR"}
      </span>
      {p === null ? (
        <span className="text-slate-400">Chưa đo</span>
      ) : (
        <>
          <span className={attack && p > 0 ? "font-medium text-attack-600" : "font-medium text-slate-900"}>{pct(p, 0)}</span>
          <span className="text-xs text-slate-400">{k}/{n}</span>
        </>
      )}
    </span>
  );
}

function Scenario({ b }: { b: Batch }) {
  let title: string;
  let sub: string;
  if (b.scenario) {
    title = `${b.scenario.goal} · ${GOAL_LABEL[b.scenario.goal]}`;
    sub = `${CHANNEL_LABEL[b.scenario.channel] ?? b.scenario.channel} · ${b.scenario.technique} · ${b.scenario.carrier_task_id}`;
  } else if (b.run_kinds.includes("attack")) {
    title = `Tấn công${b.manifest?.block ? ` · khối ${b.manifest.block}` : ""}`;
    sub = b.channels.join(", ") || "—";
  } else {
    title = "Bench hữu dụng";
    sub = `${b.manifest?.task ? `${b.manifest.task} · ` : ""}câu lành tính`;
  }
  return (
    <span className="block max-w-[280px] truncate whitespace-nowrap text-slate-800" title={`${title} — ${sub}`}>
      {title}
    </span>
  );
}

export function BatchesPage() {
  const [sp, setSp] = useSearchParams();
  const filter = (["all", "experiment", "dryrun", "demo"].includes(sp.get("type") ?? "") ? sp.get("type") : "all") as Filter;
  const [search, setSearch] = useState("");
  const setFilter = (value: Filter) => {
    const n = new URLSearchParams(sp);
    if (value === "all") n.delete("type");
    else n.set("type", value);
    setSp(n, { replace: true });
  };
  const q = useQuery({ queryKey: ["batches"], refetchInterval: 15_000, queryFn: () => api.batches() });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const all = q.data!;
  const count = (k: Filter) => (k === "all" ? all.length : all.filter((b) => b.kind === k).length);
  const rows = all.filter(
    (b) =>
      (filter === "all" || b.kind === filter) &&
      `${b.batch_id} ${b.targets.join(" ")}`.toLowerCase().includes(search.trim().toLowerCase()),
  );

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
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="relative block w-full max-w-xs">
            <span className="sr-only">Tìm lô hoặc model</span>
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden="true" />
            <input
              className="input w-full pl-8"
              type="search"
              placeholder="Nhập mã lô, A1, A2…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <span role="status" className="num text-xs text-slate-500">
            {int(rows.length)} lô
          </span>
        </div>
        <Card className="overflow-hidden">
          {rows.length === 0 ? (
            <Empty
              title="Không có lô phù hợp"
              action={
                search ? (
                  <Button size="sm" onClick={() => setSearch("")}>
                    Xóa tìm kiếm
                  </Button>
                ) : undefined
              }
            >
              Thử tìm bằng mã lô hoặc đổi bộ lọc.
            </Empty>
          ) : (
            <div className="max-w-full overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Lô</th>
                    <th>Loại</th>
                    <th>Nội dung</th>
                    <th>Model</th>
                    <th>Phòng thủ</th>
                    <th className="text-right">Run</th>
                    <th>Kết quả</th>
                    <th className="text-right">Token</th>
                    <th className="text-right">Chi phí</th>
                    <th className="text-right">Thời điểm</th>
                    <th>
                      <span className="sr-only">Mở</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((b) => {
                    const to = { pathname: "/runs", search: `?batch=${encodeURIComponent(b.batch_id)}&scope=${b.kind}` };
                    return (
                      <tr key={b.batch_id}>
                        <td className="max-w-[260px]">
                          <Link to={to} title={`${b.batch_id}\n${b.store}`} className="block truncate font-mono text-xs font-medium text-slate-900 hover:text-brand-600 hover:underline">
                            {b.batch_id}
                          </Link>
                        </td>
                        <td>
                          <Badge tone={b.kind === "experiment" ? "brand" : b.kind === "demo" ? "payload" : "neutral"}>{KIND_LABEL[b.kind]}</Badge>
                        </td>
                        <td>
                          <Scenario b={b} />
                        </td>
                        <td className="whitespace-nowrap font-mono text-xs text-slate-700">{b.targets.join(", ")}</td>
                        <td>
                          <div className="flex flex-wrap gap-1">
                            {b.presets.map((p) => (
                              <Badge key={p} tone={p === "off" ? "neutral" : "defense"}>
                                {presetLabel(p)}
                              </Badge>
                            ))}
                          </div>
                        </td>
                        <td className="num text-right">
                          {int(b.n_runs)}
                          {b.n_parse_error > 0 && <div className="whitespace-nowrap text-xs text-amber-700">{b.n_parse_error} lỗi</div>}
                        </td>
                        <td>
                          <Result b={b} />
                        </td>
                        <td className="num text-right text-slate-700">{kilo(b.tokens)}</td>
                        <td className="num whitespace-nowrap text-right text-slate-700">{usd(b.manifest?.spent_usd)}</td>
                        <td className="num whitespace-nowrap text-right text-slate-500">{when(b.created_at)}</td>
                        <td className="w-8">
                          <Link
                            to={to}
                            aria-label={`Xem run của lô ${b.batch_id}`}
                            title="Xem các run"
                            className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                          >
                            <ChevronRight size={16} />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
