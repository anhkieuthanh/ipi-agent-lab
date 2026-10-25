import { useQuery } from "@tanstack/react-query";
import { ListTree, Search } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Badge, Card, Empty, ErrorBox, Loading, Mono, OutcomeBadge, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, int, presetLabel, when } from "@/lib/format";
import { useScope } from "@/lib/scope";

const PAGE = 40;

export function RunsPage() {
  const { params, batch } = useScope();
  const [sp] = useSearchParams();
  const [q, setQ] = useState("");
  const [runKind, setRunKind] = useState<"" | "attack" | "benign">("");
  const [outcome, setOutcome] = useState("");
  const [page, setPage] = useState(0);

  const query = useQuery({
    queryKey: ["runs", params, q, runKind, outcome, page],
    queryFn: () =>
      api.runs({ ...params, q: q || undefined, run_kind: runKind || undefined, outcome: outcome || undefined, limit: PAGE, offset: page * PAGE }),
  });

  const data = query.data;
  const pages = data ? Math.ceil(data.total / PAGE) : 0;

  return (
    <>
      <PageHeader
        title="Điều tra run"
        description={batch ? <>Các run của lô <Mono>{batch}</Mono>.</> : "Mọi run trong phạm vi đang chọn. Bấm một run để xem từng bước, payload và canary được tô màu, tool agent đã gọi."}
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
                  setQ(e.target.value);
                  setPage(0);
                }}
              />
            </div>
          </label>
          <Select
            label="Loại run"
            value={runKind}
            onChange={(v) => {
              setRunKind(v);
              setPage(0);
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
              setOutcome(v);
              setPage(0);
            }}
            options={[
              { value: "", label: "Tất cả" },
              { value: "success", label: "Tấn công thành công" },
              { value: "blocked", label: "Bị chặn" },
              { value: "failed", label: "Không đạt" },
              { value: "pass", label: "Đạt (lành tính)" },
            ]}
            className="w-52"
          />
        </div>
      </Card>

      {query.isLoading && <Loading />}
      {query.error && <ErrorBox error={query.error} />}
      {data && (
        <Card>
          {data.items.length === 0 ? (
            <Empty title="Không có run nào khớp" icon={<ListTree size={20} />} />
          ) : (
            <>
              <table className="table-base">
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
                    <tr key={r.run_id} className="cursor-pointer hover:bg-slate-50/70">
                      <td>
                        <Link
                          to={`/runs/${r.run_id}${sp.toString() ? `?${sp}` : ""}`}
                          className="font-mono text-[12.5px] font-medium text-slate-800 hover:text-brand-600"
                        >
                          {r.run_id.slice(0, 12)}
                        </Link>
                      </td>
                      <td>
                        <Badge tone={r.run_kind === "attack" ? "attack" : "brand"}>
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
              </table>
              <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-[13px] text-slate-500">
                <span>
                  {int(data.total)} run · trang {page + 1}/{Math.max(pages, 1)}
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={page === 0}
                    onClick={() => setPage(page - 1)}
                    className="rounded-md px-3 py-1 ring-1 ring-inset ring-slate-300 disabled:opacity-40"
                  >
                    Trước
                  </button>
                  <button
                    disabled={page + 1 >= pages}
                    onClick={() => setPage(page + 1)}
                    className="rounded-md px-3 py-1 ring-1 ring-inset ring-slate-300 disabled:opacity-40"
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
