import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity,
  Crosshair,
  FlaskConical,
  Gauge,
  Layers,
  ListTree,
  Settings2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { api } from "@/lib/api";
import { SCOPE_LABEL, type ScopeKind, useScope } from "@/lib/scope";

const NAV: { group: string; items: { to: string; label: string; icon: ReactNode; scoped?: boolean }[] }[] = [
  {
    group: "Giám sát",
    items: [
      { to: "/", label: "Tổng quan", icon: <Gauge size={17} />, scoped: true },
      { to: "/batches", label: "Lô thực nghiệm", icon: <Layers size={17} /> },
    ],
  },
  {
    group: "Phân tích",
    items: [
      { to: "/attack", label: "Tấn công", icon: <Crosshair size={17} />, scoped: true },
      { to: "/defense", label: "Phòng thủ", icon: <ShieldCheck size={17} />, scoped: true },
      { to: "/runs", label: "Điều tra run", icon: <ListTree size={17} />, scoped: true },
    ],
  },
  {
    group: "Thực hành",
    items: [{ to: "/lab", label: "Phòng thí nghiệm", icon: <FlaskConical size={17} /> }],
  },
  {
    group: "Hệ thống",
    items: [{ to: "/config", label: "Cấu hình", icon: <Settings2 size={17} /> }],
  },
];

const TITLES: Record<string, string> = {
  "/": "Tổng quan",
  "/batches": "Lô thực nghiệm",
  "/attack": "Phân tích tấn công",
  "/defense": "Phân tích phòng thủ",
  "/runs": "Điều tra run",
  "/lab": "Phòng thí nghiệm tấn công",
  "/config": "Cấu hình",
};

function Sidebar() {
  const { search } = useScope();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });
  return (
    <aside className="fixed inset-y-0 left-0 z-20 flex w-[248px] flex-col bg-ink-950 text-slate-300">
      <div className="flex h-16 items-center gap-3 border-b border-white/5 px-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 shadow-lg shadow-brand-900/40">
          <ShieldCheck size={19} className="text-white" />
        </div>
        <div className="leading-tight">
          <div className="text-[14.5px] font-semibold text-white">IPI Guard</div>
          <div className="text-[11.5px] text-slate-400">Console đánh giá agent</div>
        </div>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5">
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="px-3 pb-2 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-slate-500">
              {g.group}
            </div>
            <div className="space-y-0.5">
              {g.items.map((it) => (
                <NavLink
                  key={it.to}
                  to={{ pathname: it.to, search: it.scoped ? search : "" }}
                  end={it.to === "/"}
                  className={({ isActive }) =>
                    clsx(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium transition",
                      isActive
                        ? "bg-white/10 text-white shadow-inner"
                        : "text-slate-400 hover:bg-white/5 hover:text-slate-100",
                    )
                  }
                >
                  {it.icon}
                  {it.label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-white/5 px-5 py-4 text-[11.5px] text-slate-500">
        <div className="flex items-center justify-between">
          <span>Bộ model</span>
          <span className="font-mono text-slate-300">{meta.data?.model_tag ?? "—"}</span>
        </div>
        <div className="mt-1 flex items-center justify-between">
          <span>Bộ payload</span>
          <span className="font-mono text-slate-300">{meta.data?.attack_tag ?? "—"}</span>
        </div>
        <div className="mt-1 flex items-center justify-between">
          <span>Commit</span>
          <span className="max-w-[120px] truncate font-mono text-slate-300" title={meta.data?.lab_commit ?? ""}>
            {meta.data?.lab_commit?.split("-g").pop() ?? "—"}
          </span>
        </div>
      </div>
    </aside>
  );
}

function ScopePicker() {
  const { kind, batch, setScope } = useScope();
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => api.batches() });
  const list = (batches.data ?? []).filter((b) => kind === "all" || b.kind === kind);
  return (
    <div className="flex items-center gap-2">
      <span className="text-[12.5px] text-slate-500">Phạm vi</span>
      <select
        className="input h-8 text-[13px]"
        value={kind}
        onChange={(e) => setScope({ kind: e.target.value as ScopeKind })}
      >
        {(Object.keys(SCOPE_LABEL) as ScopeKind[]).map((k) => (
          <option key={k} value={k}>
            {SCOPE_LABEL[k]}
          </option>
        ))}
      </select>
      <select
        className="input h-8 max-w-[260px] text-[13px]"
        value={batch}
        onChange={(e) => setScope({ batch: e.target.value })}
      >
        <option value="">Tất cả lô ({list.length})</option>
        {list.map((b) => (
          <option key={b.batch_id} value={b.batch_id}>
            {b.batch_id}
          </option>
        ))}
      </select>
    </div>
  );
}

function Topbar() {
  const loc = useLocation();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });
  const root = "/" + (loc.pathname.split("/")[1] ?? "");
  const title = TITLES[root] ?? "IPI Guard";
  const scoped = ["/", "/attack", "/defense", "/runs"].includes(root) && !loc.pathname.startsWith("/runs/");
  return (
    <header className="sticky top-0 z-10 flex h-16 items-center justify-between gap-4 border-b border-slate-200 bg-white/85 px-8 backdrop-blur">
      <div className="flex items-center gap-2 text-[13px] text-slate-500">
        <span>IPI Guard</span>
        <span className="text-slate-300">/</span>
        <span className="font-medium text-slate-900">{title}</span>
      </div>
      <div className="flex items-center gap-4">
        {scoped && <ScopePicker />}
        <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-[12px]">
          {meta.data?.live_demo ? (
            <>
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-defense-500 opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-defense-500" />
              </span>
              <span className="font-medium text-slate-700">Chạy trực tiếp</span>
            </>
          ) : (
            <>
              <Activity size={13} className="text-slate-400" />
              <span className="text-slate-500">Chỉ xem</span>
            </>
          )}
        </div>
        <div className="hidden items-center gap-1.5 text-[12px] text-slate-500 xl:flex">
          <Sparkles size={13} />
          Prompt <span className="font-mono text-slate-700">{meta.data?.prompt_active ?? "—"}</span>
        </div>
      </div>
    </header>
  );
}

export function Layout() {
  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className="pl-[248px]">
        <Topbar />
        <main className="mx-auto max-w-[1440px] px-8 py-7">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
