import { keepPreviousData, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ListTree, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { OutcomeBar, OutcomeLegend, Rate } from "@/components/Analysis";
import { Badge, Card, Empty, ErrorBox, Loading, Mono, OutcomeBadge, PageHeader, Segmented, Select } from "@/components/ui";
import { api, type Params } from "@/lib/api";
import { BLOCKED_LABEL, CHANNEL_LABEL, GOAL_LABEL, TECHNIQUE_LABEL, int, presetLabel, when } from "@/lib/format";
import { KindIcon } from "@/lib/icons";
import { useScope } from "@/lib/scope";

const PAGE = 40;

export function RunsPage() {
  const { params } = useScope();
  const [sp, setSp] = useSearchParams();
  const q = sp.get("q") ?? "";
  const runKind = ["attack", "benign"].includes(sp.get("run_kind") ?? "") ? sp.get("run_kind")! : "";
  const outcome = sp.get("outcome") ?? "";
  const view: "run" | "payload" = sp.get("view") === "payload" ? "payload" : "run";
  // Lọc sẵn khi đi từ trang Tấn công (bấm vào một ô / kỹ thuật / model).
  const drill = {
    channel: sp.getAll("channel"),
    technique: sp.get("technique") ?? "",
    goal: sp.get("goal") ?? "",
    target: sp.get("target") ?? "",
    blocked_by: sp.get("blocked_by") ?? "",
  };
  const drillChips = [
    ...drill.channel.map((c) => ({ key: "channel", label: `${c} · ${CHANNEL_LABEL[c] ?? c}` })),
    ...(drill.technique ? [{ key: "technique", label: drill.technique }] : []),
    ...(drill.goal ? [{ key: "goal", label: `${drill.goal} · ${GOAL_LABEL[drill.goal] ?? ""}` }] : []),
    ...(drill.target ? [{ key: "target", label: `Model ${drill.target}` }] : []),
    ...(drill.blocked_by ? [{ key: "blocked_by", label: `Chặn bởi ${BLOCKED_LABEL[drill.blocked_by] ?? drill.blocked_by}` }] : []),
  ];
  const requestedPage = Number(sp.get("page") ?? 1);
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage - 1 : 0;
  const [search, setSearch] = useState(q);
  useEffect(() => { const t = setTimeout(() => setSearch(q), 300); return () => clearTimeout(t); }, [q]);
  function updateFilters(next: Record<string, string>, resetPage = true) {
    const n = new URLSearchParams(sp);
    if (resetPage) n.delete("page");
    Object.entries(next).forEach(([key, value]) => {
      n.delete(key);
      if (!value) return;
      if (key === "channel") value.split(",").forEach((v) => n.append(key, v));
      else n.set(key, value);
    });
    setSp(n, { replace: resetPage });
  }
  function clearFilters() {
    const n = new URLSearchParams(sp);
    ["q", "run_kind", "outcome", "page", "channel", "technique", "goal", "target", "blocked_by"].forEach((k) => n.delete(k));
    setSp(n, { replace: true });
  }
  function dropDrill(key: string) {
    const n = new URLSearchParams(sp);
    n.delete(key);
    n.delete("page");
    setSp(n, { replace: true });
  }
  const anyFilter = !!(q || runKind || outcome || drillChips.length);

  const query = useQuery({
    queryKey: ["runs", params, search, runKind, outcome, page, drill], refetchInterval: 15_000,
    enabled: view === "run",
    placeholderData: keepPreviousData,
    queryFn: () =>
      api.runs({
        ...params, q: search || undefined, run_kind: runKind || undefined, outcome: outcome || undefined,
        channel: drill.channel.length ? drill.channel : undefined, technique: drill.technique || undefined,
        goal: drill.goal || undefined, target: drill.target || undefined, blocked_by: drill.blocked_by || undefined,
        limit: PAGE, offset: page * PAGE,
      }),
  });

  const data = query.data;
  const pages = data ? Math.ceil(data.total / PAGE) : 0;

  return (
    <>
      <PageHeader
        title="Lượt chạy"
        info="Bấm một run để xem từng bước, payload và canary tô màu, tool agent đã gọi."
      />

      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3 px-5 py-4">
          <label className="flex min-w-[260px] flex-1 flex-col gap-1">
            <span className="label">Tìm run / payload / tác vụ</span>
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className="input w-full pl-9"
                placeholder="VD: P-T2-G1, CT-05, demo-2026…"
                value={q}
                onChange={(e) => {
                  updateFilters({ q: e.target.value });
                }}
              />
            </div>
          </label>
          <Select
            label="Loại run"
            value={runKind}
            onChange={(v) => {
              updateFilters({ run_kind: v, outcome: "" });
            }}
            options={[
              { value: "", label: "Tất cả" },
              { value: "attack", label: "Tấn công" },
              { value: "benign", label: "Lành tính" },
            ]}
            className="w-40"
          />
          <Select
            label="Kết quả"
            value={outcome}
            onChange={(v) => {
              updateFilters({ outcome: v });
            }}
            options={[
              { value: "", label: "Tất cả" },
              { value: "success", label: "Tấn công thành công" },
              { value: "blocked", label: "Bị chặn" },
              { value: "failed", label: "Tấn công không đạt" },
              { value: "fail", label: "Không đạt (lành tính)" },
              { value: "pass", label: "Đạt (lành tính)" },
            ].filter((o) => !runKind || !o.value || o.value === "blocked" || (runKind === "attack" ? ["success", "failed"].includes(o.value) : ["pass", "fail"].includes(o.value)))}
            className="w-52"
          />
          {(!runKind || runKind === "attack") && (
            <>
              <Select
                label="Kênh"
                value={drill.channel.length === 1 ? drill.channel[0] : drill.channel.length ? "__multi" : ""}
                onChange={(v) => updateFilters({ channel: v === "__multi" ? drill.channel.join(",") : v })}
                options={[
                  { value: "", label: "Tất cả" },
                  ...(drill.channel.length > 1 ? [{ value: "__multi", label: drill.channel.join(" + ") }] : []),
                  ...Object.entries(CHANNEL_LABEL).map(([k, l]) => ({ value: k, label: `${k} · ${l}` })),
                ]}
                className="w-48"
              />
              <Select
                label="Kỹ thuật"
                value={drill.technique}
                onChange={(v) => updateFilters({ technique: v })}
                options={[{ value: "", label: "Tất cả" }, ...Object.entries(TECHNIQUE_LABEL).map(([k, l]) => ({ value: k, label: `${k} · ${l}` }))]}
                className="w-52"
              />
              <Select
                label="Mục tiêu"
                value={drill.goal}
                onChange={(v) => updateFilters({ goal: v })}
                options={[{ value: "", label: "Tất cả" }, ...Object.entries(GOAL_LABEL).map(([k, l]) => ({ value: k, label: `${k} · ${l}` }))]}
                className="w-48"
              />
            </>
          )}
          <Select
            label="Model"
            value={drill.target}
            onChange={(v) => updateFilters({ target: v })}
            options={[{ value: "", label: "Tất cả" }, { value: "A1", label: "A1" }, { value: "A2", label: "A2" }, { value: "A3", label: "A3" }]}
            className="w-28"
          />
          {anyFilter && <button className="filter-clear" onClick={clearFilters}>Xóa bộ lọc</button>}
          <div className="ml-auto">
            <span className="label mb-1 block">Cách xem</span>
            <Segmented
              value={view}
              onChange={(v) => updateFilters({ view: v === "run" ? "" : v }, false)}
              options={[{ value: "run", label: "Từng run" }, { value: "payload", label: "Theo payload" }]}
            />
          </div>
        </div>
        {drillChips.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-5 py-3 text-[12.5px]">
            <span className="text-slate-500">Lọc thêm:</span>
            {drillChips.map((c, i) => (
              <button
                key={`${c.key}-${i}`}
                onClick={() => dropDrill(c.key)}
                className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-slate-700 hover:bg-slate-200"
                title="Bỏ bộ lọc này"
              >
                {c.label} <span aria-hidden className="text-slate-400">×</span>
              </button>
            ))}
          </div>
        )}
      </Card>

      {view === "payload" && <PayloadView params={params} drill={drill} search={search} />}
      {view === "run" && query.isLoading && <Loading />}
      {view === "run" && query.error && <ErrorBox error={query.error} />}
      {view === "run" && data && (
        <Card>
          <div className="result-summary" role="status">{int(data.total)} run khớp bộ lọc{query.isFetching || q !== search ? " · đang cập nhật…" : ""}</div>
          {data.items.length === 0 ? (
            <Empty title="Không có run nào khớp" icon={<ListTree size={20} />} action={anyFilter ? <button className="filter-clear" onClick={clearFilters}>Xóa bộ lọc</button> : undefined}>Thử thay đổi bộ lọc hoặc chọn lô khác ở thanh phạm vi.</Empty>
          ) : (
            <>
              <div className="max-w-full overflow-x-auto"><table className="table-base" aria-busy={query.isFetching || q !== search}><caption className="sr-only">Danh sách run trong phạm vi đã chọn</caption>
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Loại</th>
                    <th>Nội dung</th>
                    <th>Model · phòng thủ</th>
                    <th>Kết quả</th>
                    <th className="text-right">Bước</th>
                    <th className="text-right">Thời điểm</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={r.run_id} className="hover:bg-slate-50/70">
                      <td>
                        <Link
                          to={`/runs/${r.run_id}${sp.toString() ? `?${sp}` : ""}`}
                          title={r.run_id} aria-label={`Mở run ${r.run_id}`} className="inline-flex min-h-9 items-center font-mono text-[12.5px] font-medium text-brand-600 hover:underline"
                        >
                          {r.run_id.slice(0, 12)}
                        </Link>
                      </td>
                      <td>
                        <Badge tone={r.run_kind === "attack" ? "attack" : "brand"}>
                          <KindIcon kind={r.run_kind} />
                          {r.run_kind === "attack" ? "Tấn công" : "Lành tính"}
                        </Badge>
                      </td>
                      <td className="text-[13px] text-slate-600">
                        {r.run_kind === "attack" ? (
                          <>
                            <div className="font-medium text-slate-700">
                              {r.goal} · {r.goal ? GOAL_LABEL[r.goal] : ""}
                            </div>
                            <div className="text-[12px] text-slate-500">
                              {r.channel ? CHANNEL_LABEL[r.channel] ?? r.channel : ""} · {r.technique} · {r.payload_id}
                            </div>
                          </>
                        ) : (
                          <Mono>{r.benign_query_id}</Mono>
                        )}
                        {r.user_query && (
                          <div className="mt-0.5 max-w-[420px] truncate text-[12px] italic text-slate-400" title={r.user_query}>
                            “{r.user_query}”
                          </div>
                        )}
                      </td>
                      <td className="text-[13px]">
                        <div className="text-slate-700">{r.target_id}</div>
                        <div className="text-[12px] text-slate-500">{presetLabel(r.preset)}</div>
                      </td>
                      <td>
                        {r.parse_error ? (
                          <Badge tone="warn">Lỗi hạ tầng</Badge>
                        ) : (
                          <OutcomeBadge outcome={r.outcome} blockedBy={r.blocked_by} />
                        )}
                      </td>
                      <td className="num text-right text-slate-600">{int(r.n_steps)}</td>
                      <td className="text-right text-[13px] text-slate-500">{when(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-3 text-[13px] text-slate-500">
                <span>
                  {int(data.total)} run · trang {page + 1}/{Math.max(pages, 1)}
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={page === 0 || query.isPlaceholderData}
                    onClick={() => updateFilters({ page: String(page) }, false)}
                    className="min-h-10 rounded-md px-3 py-1 ring-1 ring-inset ring-slate-300 disabled:opacity-40"
                  >
                    Trước
                  </button>
                  <button
                    disabled={page + 1 >= pages || query.isPlaceholderData}
                    onClick={() => updateFilters({ page: String(page + 2) }, false)}
                    className="min-h-10 rounded-md px-3 py-1 ring-1 ring-inset ring-slate-300 disabled:opacity-40"
                  >
                    Sau
                  </button>
                </div>
              </div>
            </>
          )}
        </Card>
      )}
    </>
  );
}

type Drill = { channel: string[]; technique: string; goal: string; target: string; blocked_by: string };

/** Run tấn công gom theo payload: cùng một payload thắng ở model nào. */
function PayloadView({ params, drill, search }: { params: Params; drill: Drill; search: string }) {
  const [sp] = useSearchParams();
  const q = useQuery({
    queryKey: ["runs-by-payload", params, drill, search],
    placeholderData: keepPreviousData,
    queryFn: () =>
      api.runsByPayload({
        ...params, q: search || undefined,
        channel: drill.channel.length ? drill.channel : undefined, technique: drill.technique || undefined,
        goal: drill.goal || undefined, target: drill.target || undefined,
      }),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const toRuns = (pid: string, target?: string) => {
    const n = new URLSearchParams(sp);
    n.delete("view");
    n.delete("page");
    n.set("run_kind", "attack");
    n.set("q", pid);
    if (target) n.set("target", target);
    return `/runs?${n}`;
  };
  return (
    <Card>
      <div className="result-summary" role="status">
        {int(d.total)} payload · xếp theo số lần tấn công thành công{d.total > d.items.length ? ` · hiện ${d.items.length} đầu` : ""}
      </div>
      {d.items.length === 0 ? (
        <Empty title="Không có payload nào khớp" icon={<ListTree size={20} />}>Thử bỏ bớt bộ lọc.</Empty>
      ) : (
        <>
          <div className="max-w-full overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Payload</th>
                  <th>Kênh · kỹ thuật · mục tiêu</th>
                  <th className="w-52">Tỉ lệ thành công</th>
                  {d.targets.map((t) => <th key={t} className="text-center">{t}</th>)}
                  <th className="w-40">Kết cục</th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((r) => (
                  <tr key={r.payload_id} className="hover:bg-slate-50/70">
                    <td>
                      <Link to={toRuns(r.payload_id)} className="font-mono text-[12.5px] font-medium text-brand-600 hover:underline">
                        {r.payload_id}
                      </Link>
                    </td>
                    <td className="text-[12.5px] text-slate-600">
                      {r.channels.join(", ")} · {r.technique} · {r.goal} {r.goal ? GOAL_LABEL[r.goal] : ""}
                    </td>
                    <td><Rate r={r.asr} /></td>
                    {d.targets.map((t) => {
                      const v = r.by_target[t];
                      return (
                        <td key={t} className="text-center">
                          {v ? (
                            <Link
                              to={toRuns(r.payload_id, t)}
                              title={`${v.x}/${v.n}`}
                              className={clsx("num inline-block min-w-12 rounded px-1.5 py-0.5 text-[12.5px]",
                                v.x > 0 ? "bg-attack-50 font-semibold text-attack-700" : "text-slate-400")}
                            >
                              {v.x}/{v.n}
                            </Link>
                          ) : <span className="text-slate-300">—</span>}
                        </td>
                      );
                    })}
                    <td><OutcomeBar o={r.outcomes} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-slate-100 px-5 py-3"><OutcomeLegend /></div>
        </>
      )}
    </Card>
  );
}
