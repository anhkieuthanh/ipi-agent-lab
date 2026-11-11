import { keepPreviousData, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, ListTree, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { OutcomeBar, OutcomeLegend, Rate } from "@/components/Analysis";
import { Button, Card, Empty, ErrorBox, Kbd, Loading, Mono, OutcomeBadge, PageHeader, Segmented, Status, Tooltip } from "@/components/ui";
import { api, type Params } from "@/lib/api";
import { BLOCKED_LABEL, CHANNEL_LABEL, GOAL_LABEL, TECHNIQUE_LABEL, int, presetLabel, when } from "@/lib/format";
import { KindIcon } from "@/lib/icons";
import { useScope } from "@/lib/scope";

const PAGE = 40;

/** Ô chọn gọn trên thanh lọc: nhãn nằm trong lựa chọn đầu, đang lọc thì viền đậm. */
function FilterSelect({
  label,
  value,
  onChange,
  options,
  className,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={clsx("input text-xs", value && "border-slate-400 font-medium text-slate-900", className)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.value ? o.label : `${label}: tất cả`}
        </option>
      ))}
    </select>
  );
}

export function RunsPage() {
  const { params } = useScope();
  const navigate = useNavigate();
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
    ...(drill.channel.length > 1 ? [{ key: "channel", label: `Kênh ${drill.channel.join(" + ")}` }] : []),
    ...(drill.blocked_by ? [{ key: "blocked_by", label: `Chặn bởi ${BLOCKED_LABEL[drill.blocked_by] ?? drill.blocked_by}` }] : []),
  ];
  const requestedPage = Number(sp.get("page") ?? 1);
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage - 1 : 0;
  const [search, setSearch] = useState(q);
  useEffect(() => {
    const t = setTimeout(() => setSearch(q), 300);
    return () => clearTimeout(t);
  }, [q]);

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
  const anyFilter = !!(q || runKind || outcome || drill.channel.length || drill.technique || drill.goal || drill.target || drill.blocked_by);

  const query = useQuery({
    queryKey: ["runs", params, search, runKind, outcome, page, drill],
    refetchInterval: 15_000,
    enabled: view === "run",
    placeholderData: keepPreviousData,
    queryFn: () =>
      api.runs({
        ...params,
        q: search || undefined,
        run_kind: runKind || undefined,
        outcome: outcome || undefined,
        channel: drill.channel.length ? drill.channel : undefined,
        technique: drill.technique || undefined,
        goal: drill.goal || undefined,
        target: drill.target || undefined,
        blocked_by: drill.blocked_by || undefined,
        limit: PAGE,
        offset: page * PAGE,
      }),
  });

  const data = query.data;
  const pages = data ? Math.ceil(data.total / PAGE) : 0;
  const busy = query.isFetching || q !== search;
  const detailHref = (id: string) => `/runs/${id}${sp.toString() ? `?${sp}` : ""}`;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Lượt chạy"
        description="Mỗi dòng là một lượt agent xử lý câu hỏi. Mở một run để xem từng bước, payload và canary được tô màu, tool agent đã gọi."
        actions={
          <Segmented
            label="Cách xem"
            value={view}
            onChange={(v) => updateFilters({ view: v === "run" ? "" : v }, false)}
            options={[{ value: "run", label: "Từng run" }, { value: "payload", label: "Theo payload" }]}
          />
        }
      />

      <div className="flex flex-wrap items-center gap-2" role="search" aria-label="Lọc lượt chạy">
        <div className="relative min-w-0 flex-1 basis-[240px] sm:max-w-[320px]">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            aria-label="Tìm run, payload hoặc tác vụ"
            className="input w-full pl-8 text-xs"
            placeholder="Tìm run, payload, tác vụ…"
            value={q}
            onChange={(e) => updateFilters({ q: e.target.value })}
          />
        </div>
        <FilterSelect
          label="Loại run"
          value={runKind}
          onChange={(v) => updateFilters({ run_kind: v, outcome: "" })}
          options={[{ value: "", label: "" }, { value: "attack", label: "Tấn công" }, { value: "benign", label: "Lành tính" }]}
        />
        <FilterSelect
          label="Kết quả"
          value={outcome}
          onChange={(v) => updateFilters({ outcome: v })}
          options={[
            { value: "", label: "" },
            { value: "success", label: "Tấn công thành công" },
            { value: "blocked", label: "Bị chặn" },
            { value: "failed", label: "Tấn công không đạt" },
            { value: "fail", label: "Không đạt (lành tính)" },
            { value: "pass", label: "Đạt (lành tính)" },
          ].filter((o) => !runKind || !o.value || o.value === "blocked" || (runKind === "attack" ? ["success", "failed"].includes(o.value) : ["pass", "fail"].includes(o.value)))}
        />
        {(!runKind || runKind === "attack") && (
          <>
            <FilterSelect
              label="Kênh"
              value={drill.channel.length === 1 ? drill.channel[0] : drill.channel.length ? "__multi" : ""}
              onChange={(v) => updateFilters({ channel: v === "__multi" ? drill.channel.join(",") : v })}
              options={[
                { value: "", label: "" },
                ...(drill.channel.length > 1 ? [{ value: "__multi", label: drill.channel.join(" + ") }] : []),
                ...Object.entries(CHANNEL_LABEL).map(([k, l]) => ({ value: k, label: `${k} · ${l}` })),
              ]}
            />
            <FilterSelect
              label="Kỹ thuật"
              value={drill.technique}
              onChange={(v) => updateFilters({ technique: v })}
              options={[{ value: "", label: "" }, ...Object.entries(TECHNIQUE_LABEL).map(([k, l]) => ({ value: k, label: `${k} · ${l}` }))]}
            />
            <FilterSelect
              label="Mục tiêu"
              value={drill.goal}
              onChange={(v) => updateFilters({ goal: v })}
              options={[{ value: "", label: "" }, ...Object.entries(GOAL_LABEL).map(([k, l]) => ({ value: k, label: `${k} · ${l}` }))]}
            />
          </>
        )}
        <FilterSelect
          label="Model"
          value={drill.target}
          onChange={(v) => updateFilters({ target: v })}
          options={[{ value: "", label: "" }, { value: "A1", label: "A1" }, { value: "A2", label: "A2" }, { value: "A3", label: "A3" }]}
        />
        {drillChips.map((c) => (
          <button
            key={c.key}
            onClick={() => dropDrill(c.key)}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-slate-400 px-2 text-xs font-medium text-slate-900 hover:bg-slate-100"
            aria-label={`Bỏ bộ lọc: ${c.label}`}
          >
            {c.label} <X size={12} className="text-slate-400" />
          </button>
        ))}
        {anyFilter && (
          <Button size="sm" variant="ghost" onClick={clearFilters}>
            Xóa bộ lọc
          </Button>
        )}
      </div>

      {view === "payload" && <PayloadView params={params} drill={drill} search={search} />}
      {view === "run" && query.error && <ErrorBox error={query.error} />}
      {view === "run" && (
        <Card className="overflow-hidden">
          <div className="flex h-10 items-center justify-between gap-3 border-b border-slate-200 px-4 text-xs text-slate-500" role="status">
            <span>
              {data ? <><span className="num font-medium text-slate-700">{int(data.total)}</span> run khớp bộ lọc</> : "Đang tải…"}
              {data && busy ? " · đang cập nhật…" : ""}
            </span>
            {data && data.total > 0 && (
              <span className="num hidden sm:inline">
                {int(page * PAGE + 1)}–{int(Math.min((page + 1) * PAGE, data.total))}
              </span>
            )}
          </div>
          {query.isLoading ? (
            <Loading rows={10} />
          ) : data && data.items.length === 0 ? (
            <Empty
              title="Không có run nào khớp"
              icon={<ListTree size={20} />}
              action={anyFilter ? <Button size="sm" onClick={clearFilters}>Xóa bộ lọc</Button> : undefined}
            >
              Thử thay đổi bộ lọc hoặc chọn lô khác ở thanh phạm vi.
            </Empty>
          ) : data ? (
            <>
              <div className="max-h-[calc(100vh-260px)] min-h-[320px] overflow-auto">
                <table className={clsx("table-base", busy && "opacity-70 transition-opacity")} aria-busy={busy}>
                  <caption className="sr-only">Danh sách run trong phạm vi đã chọn</caption>
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Nội dung</th>
                      <th>Model</th>
                      <th>Phòng thủ</th>
                      <th>Kết quả</th>
                      <th className="text-right">Bước</th>
                      <th className="text-right">Thời điểm</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((r) => (
                      <tr
                        key={r.run_id}
                        className="cursor-pointer"
                        onClick={(e) => {
                          if ((e.target as HTMLElement).closest("a,button")) return;
                          navigate(detailHref(r.run_id));
                        }}
                      >
                        <td className="whitespace-nowrap">
                          <Link
                            to={detailHref(r.run_id)}
                            aria-label={`Mở run ${r.run_id}`}
                            className="font-mono text-xs font-medium text-slate-900 hover:text-brand-600 hover:underline"
                          >
                            {r.run_id.slice(0, 12)}
                          </Link>
                          <div className="mt-0.5 flex items-center gap-1 text-2xs text-slate-400">
                            <KindIcon kind={r.run_kind} size={11} />
                            {r.run_kind === "attack" ? "Tấn công" : "Lành tính"}
                          </div>
                        </td>
                        <td className="max-w-[520px]">
                          {r.run_kind === "attack" ? (
                            <div className="flex flex-wrap items-center gap-x-1.5 text-sm text-slate-800">
                              <span className="font-medium">{r.goal}</span>
                              <span className="text-slate-500">{r.goal ? GOAL_LABEL[r.goal] : ""}</span>
                              <span className="text-slate-300">·</span>
                              <span className="text-xs text-slate-500">
                                {r.channel ? CHANNEL_LABEL[r.channel] ?? r.channel : ""} · {r.technique} · <Mono>{r.payload_id}</Mono>
                              </span>
                            </div>
                          ) : (
                            <Mono className="text-slate-700">{r.benign_query_id}</Mono>
                          )}
                          {r.user_query && (
                            <Tooltip content={r.user_query}>
                              <div className="mt-0.5 truncate text-xs text-slate-400">{r.user_query}</div>
                            </Tooltip>
                          )}
                        </td>
                        <td className="whitespace-nowrap font-mono text-xs text-slate-700">{r.target_id}</td>
                        <td className="whitespace-nowrap text-xs text-slate-600">{presetLabel(r.preset)}</td>
                        <td>{r.parse_error ? <Status tone="warn">Lỗi hạ tầng</Status> : <OutcomeBadge outcome={r.outcome} blockedBy={r.blocked_by} />}</td>
                        <td className="num text-right text-slate-600">{int(r.n_steps)}</td>
                        <td className="num whitespace-nowrap text-right text-xs text-slate-500">{when(r.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-2 text-xs text-slate-500">
                <span className="num">
                  Trang {page + 1} / {Math.max(pages, 1)}
                </span>
                <div className="flex items-center gap-1">
                  <Button size="sm" variant="ghost" aria-label="Trang trước" disabled={page === 0 || query.isPlaceholderData} onClick={() => updateFilters({ page: String(page) }, false)} icon={<ChevronLeft size={14} />}>
                    Trước
                  </Button>
                  <Button size="sm" variant="ghost" aria-label="Trang sau" disabled={page + 1 >= pages || query.isPlaceholderData} onClick={() => updateFilters({ page: String(page + 2) }, false)}>
                    Sau <ChevronRight size={14} />
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </Card>
      )}
      <p className="hidden text-2xs text-slate-400 md:block">
        Mẹo: <Kbd>⌘</Kbd> <Kbd>K</Kbd> rồi dán mã run 32 ký tự để mở thẳng run đó.
      </p>
    </div>
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
        ...params,
        q: search || undefined,
        channel: drill.channel.length ? drill.channel : undefined,
        technique: drill.technique || undefined,
        goal: drill.goal || undefined,
        target: drill.target || undefined,
      }),
  });
  if (q.isLoading) return <Card><Loading rows={10} /></Card>;
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
    <Card className="overflow-hidden">
      <div className="flex h-10 items-center border-b border-slate-200 px-4 text-xs text-slate-500" role="status">
        <span className="num font-medium text-slate-700">{int(d.total)}</span>&nbsp;payload · xếp theo số lần tấn công thành công
        {d.total > d.items.length ? ` · hiện ${d.items.length} đầu` : ""}
      </div>
      {d.items.length === 0 ? (
        <Empty title="Không có payload nào khớp" icon={<ListTree size={20} />}>
          Thử bỏ bớt bộ lọc.
        </Empty>
      ) : (
        <>
          <div className="max-h-[calc(100vh-260px)] min-h-[320px] overflow-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Payload</th>
                  <th>Kênh · kỹ thuật · mục tiêu</th>
                  <th>Tỉ lệ thành công</th>
                  {d.targets.map((t) => (
                    <th key={t} className="text-right">{t}</th>
                  ))}
                  <th className="w-40">Kết cục</th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((r) => (
                  <tr key={r.payload_id}>
                    <td className="whitespace-nowrap">
                      <Link to={toRuns(r.payload_id)} className="font-mono text-xs font-medium text-slate-900 hover:text-brand-600 hover:underline">
                        {r.payload_id}
                      </Link>
                    </td>
                    <td className="text-xs text-slate-600">
                      {r.channels.join(", ")} · {r.technique} · {r.goal} {r.goal ? GOAL_LABEL[r.goal] : ""}
                    </td>
                    <td><Rate r={r.asr} /></td>
                    {d.targets.map((t) => {
                      const v = r.by_target[t];
                      return (
                        <td key={t} className="text-right">
                          {v ? (
                            <Link
                              to={toRuns(r.payload_id, t)}
                              title={`${v.x}/${v.n} run thành công`}
                              className={clsx(
                                "num inline-block min-w-12 rounded px-1.5 py-0.5 text-xs hover:underline",
                                v.x > 0 ? "bg-attack-50 font-medium text-attack-700" : "text-slate-400",
                              )}
                            >
                              {v.x}/{v.n}
                            </Link>
                          ) : (
                            <span className="text-slate-300">—</span>
                          )}
                        </td>
                      );
                    })}
                    <td><OutcomeBar o={r.outcomes} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-slate-200 px-4 py-2.5">
            <OutcomeLegend />
          </div>
        </>
      )}
    </Card>
  );
}
