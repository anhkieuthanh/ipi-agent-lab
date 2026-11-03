import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ListTree, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Badge, Card, Empty, ErrorBox, Loading, Mono, OutcomeBadge, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, int, presetLabel, when } from "@/lib/format";
import { KindIcon } from "@/lib/icons";
import { useScope } from "@/lib/scope";

const PAGE = 40;

export function RunsPage() {
  const { params } = useScope();
  const [sp, setSp] = useSearchParams();
  const q = sp.get("q") ?? "";
  const runKind = ["attack", "benign"].includes(sp.get("run_kind") ?? "") ? sp.get("run_kind")! : "";
  const outcome = sp.get("outcome") ?? "";
  const requestedPage = Number(sp.get("page") ?? 1);
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage - 1 : 0;
  const [search, setSearch] = useState(q);
  useEffect(() => { const t = setTimeout(() => setSearch(q), 300); return () => clearTimeout(t); }, [q]);
  function updateFilters(next: Record<string, string>, resetPage = true) {
    const n = new URLSearchParams(sp);
    if (resetPage) n.delete("page");
    Object.entries(next).forEach(([key, value]) => value ? n.set(key, value) : n.delete(key));
    setSp(n, { replace: resetPage });
  }
  function clearFilters() { updateFilters({ q: "", run_kind: "", outcome: "" }); }

  const query = useQuery({
    queryKey: ["runs", params, search, runKind, outcome, page], refetchInterval: 15_000,
    placeholderData: keepPreviousData,
    queryFn: () =>
      api.runs({ ...params, q: search || undefined, run_kind: runKind || undefined, outcome: outcome || undefined, limit: PAGE, offset: page * PAGE }),
  });

  const data = query.data;
  const pages = data ? Math.ceil(data.total / PAGE) : 0;

  return (
    <>
      <PageHeader
        title="Điều tra run"
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
          {(q || runKind || outcome) && <button className="filter-clear" onClick={clearFilters}>Xóa bộ lọc</button>}
        </div>
      </Card>

      {query.isLoading && <Loading />}
      {query.error && <ErrorBox error={query.error} />}
      {data && (
        <Card>
          <div className="result-summary" role="status">{int(data.total)} run khớp bộ lọc{query.isFetching || q !== search ? " · đang cập nhật…" : ""}</div>
          {data.items.length === 0 ? (
            <Empty title="Không có run nào khớp" icon={<ListTree size={20} />} action={(q || runKind || outcome) ? <button className="filter-clear" onClick={clearFilters}>Xóa bộ lọc</button> : undefined}>Thử thay đổi bộ lọc hoặc chọn lô khác ở thanh phạm vi.</Empty>
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
