import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowUpRight, ChevronDown, Monitor, PanelTop, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { api } from "@/lib/api";
import { SCOPE_LABEL, type ScopeKind, useScope } from "@/lib/scope";

const GROUPS = [
  { label: "Tổng quan", paths: ["/"], items: [] },
  { label: "Thực nghiệm", paths: ["/batches", "/lab"], items: [{ to: "/batches", label: "Lô thực nghiệm" }, { to: "/lab", label: "Phòng thí nghiệm" }] },
  { label: "Phân tích", paths: ["/attack", "/defense", "/runs"], items: [{ to: "/attack", label: "Tấn công" }, { to: "/defense", label: "Phòng thủ" }, { to: "/runs", label: "Điều tra run" }] },
  { label: "Hệ thống", paths: ["/system", "/config", "/process"], items: [{ to: "/system", label: "Sơ đồ hệ thống" }, { to: "/config", label: "Cấu hình" }, { to: "/process", label: "Quy trình" }] },
];
const SCOPED = ["/", "/attack", "/defense", "/runs"];

function ScopePicker() {
  const { kind, batch, setScope } = useScope();
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => api.batches(), refetchInterval: 15_000 });
  const list = (batches.data ?? []).filter((b) => kind === "all" || b.kind === kind);
  return (
    <div className="scope-picker">
      <span className="context-label">Phạm vi dữ liệu</span>
      <select aria-label="Loại phạm vi" className="input" value={kind} onChange={(e) => setScope({ kind: e.target.value as ScopeKind })}>
        {(Object.keys(SCOPE_LABEL) as ScopeKind[]).map((k) => <option key={k} value={k}>{SCOPE_LABEL[k]}</option>)}
      </select>
      <select aria-label="Lô dữ liệu" className="input scope-batch" value={batch} onChange={(e) => setScope({ batch: e.target.value })} disabled={batches.isLoading || !!batches.error}>
        <option value="">{batches.isLoading ? "Đang tải lô…" : batches.error ? "Không tải được lô" : `Tất cả lô (${list.length})`}</option>
        {list.map((b) => <option key={b.batch_id} value={b.batch_id}>{b.batch_id}</option>)}
      </select>
    </div>
  );
}

export function Layout() {
  const loc = useLocation();
  const { kind, batch, setScope } = useScope();
  const root = "/" + (loc.pathname.split("/")[1] ?? "");
  const group = GROUPS.find((g) => g.paths.includes(root)) ?? GROUPS[0];
  const scoped = SCOPED.includes(root) && !loc.pathname.startsWith("/runs/");
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });
  const [presenting, setPresenting] = useState(() => sessionStorage.getItem("ipi-presentation") === "true");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);
  useEffect(() => { sessionStorage.setItem("ipi-presentation", String(presenting)); }, [presenting]);
  useEffect(() => {
    const exit = (e: KeyboardEvent) => { if (e.key === "Escape") setPresenting(false); };
    window.addEventListener("keydown", exit);
    return () => window.removeEventListener("keydown", exit);
  }, []);
  const navScope = new URLSearchParams();
  navScope.set("scope", kind);
  if (batch) navScope.set("batch", batch);
  const href = (to: string) => ({ pathname: to, search: navScope.toString() });
  async function refresh() {
    setRefreshing(true); setRefreshError(false);
    try {
      await qc.refetchQueries({ type: "active" }, { throwOnError: true });
      setUpdated(new Date());
    } catch { setRefreshError(true); }
    finally { setRefreshing(false); }
  }
  return (
    <div className={clsx("app-shell", presenting && "presentation-mode")}>
      <a href="#main-content" className="skip-link">Đến nội dung chính</a>
      <header className="app-header">
        <Link to={href("/")} className="wordmark" aria-label="IPI Guard — Tổng quan">
          <ShieldCheck size={23} strokeWidth={1.6} />
          <span>IPI Guard<span className="wordmark-caption">Agent Security Lab</span></span>
        </Link>
        {!presenting && <nav className="primary-nav" aria-label="Điều hướng chính">
          {GROUPS.map((g) => <Link key={g.label} to={href(g.paths[0])} className={clsx("primary-link", group === g && "is-active")} aria-current={group === g ? "page" : undefined}>{g.label}</Link>)}
        </nav>}
        <button className="presentation-toggle" onClick={() => setPresenting(!presenting)} aria-pressed={presenting}>
          {presenting ? <PanelTop size={16} /> : <Monitor size={16} />}
          {presenting ? "Về làm việc" : "Trình bày"}
        </button>
      </header>

      {!presenting && group.items.length > 0 && <nav className="secondary-nav" aria-label={group.label}>
        {group.items.map((it) => <NavLink key={it.to} to={href(it.to)} className={({ isActive }) => clsx("secondary-link", isActive && "is-active")}>{it.label}</NavLink>)}
      </nav>}

      <div className="workspace-context">
        {presenting ? <div className="presentation-context"><span className="context-label">Đánh giá an toàn AI Agent</span><span>{scoped ? batch || SCOPE_LABEL[kind] : loc.pathname.startsWith("/runs/") ? "Chi tiết run" : group.label}</span></div> : scoped ? <ScopePicker /> : <span className="context-label">{group.label} <ChevronDown size={12} /></span>}
        <div className="workspace-status">
          <span className="connection-state"><span className={clsx("status-dot", meta.error && "is-error")} />{meta.error ? "Mất kết nối" : meta.isLoading ? "Đang kết nối" : meta.data?.live_demo ? "Cho phép chạy trực tiếp" : "Chỉ xem"}</span>
          {!presenting && <button className="refresh-button" disabled={refreshing} onClick={refresh} aria-label="Làm mới dữ liệu"><RefreshCw size={14} className={refreshing ? "animate-spin" : ""} /></button>}
          {!presenting && <span className="update-status" role="status">{refreshError ? "Cập nhật thất bại" : refreshing ? "Đang cập nhật…" : updated ? `Làm mới ${updated.toLocaleTimeString("vi-VN")}` : "Giám sát · 15 giây/lần"}</span>}
        </div>
      </div>

      {batch && scoped && !presenting && <div className="selected-scope"><span>Lô đang xem</span><code>{batch}</code><button onClick={() => setScope({ batch: "" })}>Bỏ chọn lô</button></div>}
      <main id="main-content" tabIndex={-1} className="workspace-main"><Outlet /></main>
      <footer className="app-footer">
        <span>IPI Guard <span className="footer-divider">/</span> Đánh giá an toàn agent RAG + MCP</span>
        {!presenting && <Link to="/config" className="footer-config">{meta.data?.model_tag ?? "Bộ model"} <span className="footer-divider">·</span> {meta.data?.attack_tag ?? "Bộ payload"}<ArrowUpRight size={12} /></Link>}
        {presenting && <span>Nhấn Esc để trở về làm việc</span>}
      </footer>
    </div>
  );
}
