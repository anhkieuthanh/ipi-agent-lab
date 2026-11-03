import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowUpRight, Monitor, PanelTop, RefreshCw, ShieldCheck, LayoutDashboard, Layers, FlaskConical, Crosshair, Shield, ListTree, Network, Settings2, ListChecks, Menu, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { api } from "@/lib/api";
import { SCOPE_LABEL, type ScopeKind, useScope } from "@/lib/scope";

const GROUPS = [
  { label: "Tổng quan", paths: ["/"], items: [] },
  { label: "Thực nghiệm", paths: ["/batches", "/lab"], items: [{ to: "/batches", label: "Lô thực nghiệm" }, { to: "/lab", label: "Phòng thí nghiệm" }] },
  { label: "Phân tích", paths: ["/attack", "/defense", "/runs"], items: [{ to: "/attack", label: "Tấn công" }, { to: "/defense", label: "Phòng thủ" }, { to: "/runs", label: "Lượt chạy" }] },
  { label: "Hệ thống", paths: ["/system", "/config", "/process"], items: [{ to: "/system", label: "Sơ đồ hệ thống" }, { to: "/config", label: "Cấu hình" }, { to: "/process", label: "Quy trình" }] },
];
const NAV_ICONS = [LayoutDashboard, Layers, Crosshair, Network];
const ITEM_ICONS = [Layers, FlaskConical, Crosshair, Shield, ListTree, Network, Settings2, ListChecks];
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
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => { setMenuOpen(false); }, [loc.pathname]);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);
  useEffect(() => { sessionStorage.setItem("ipi-presentation", String(presenting)); }, [presenting]);
  useEffect(() => {
    const exit = (e: KeyboardEvent) => { if (e.key === "Escape") { setPresenting(false); setMenuOpen(false); } };
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
      {!presenting && <aside className={clsx("app-sidebar", menuOpen && "is-open")} id="workspace-navigation">
        <Link to={href("/")} className="wordmark"><span className="brand-mark"><ShieldCheck size={22} /></span><span>IPI Guard<span className="wordmark-caption">Security workspace</span></span></Link>
        <nav aria-label="Điều hướng chính" className="sidebar-nav">
          {GROUPS.map((g, gi) => {
            const Icon = NAV_ICONS[gi];
            return <div className="nav-group" key={g.label}>
              {g.items.length ? <div className="nav-group-label">{g.label}</div> : <NavLink end to={href("/")} className={({ isActive }) => clsx("sidebar-link", isActive && "is-active")}><span className="nav-icon"><Icon size={18} /></span>{g.label}</NavLink>}
              {g.items.map((it) => { const ItemIcon = ITEM_ICONS[GROUPS.flatMap((x) => x.items).findIndex((x) => x.to === it.to)]; return <NavLink key={it.to} to={href(it.to)} className={({ isActive }) => clsx("sidebar-link", isActive && "is-active")}><span className="nav-icon"><ItemIcon size={18} /></span>{it.label}</NavLink>; })}
            </div>;
          })}
        </nav>
        <div className="sidebar-foot"><span className="status-dot" /> RAG + MCP Lab</div>
      </aside>}
      <div className="workspace-body">
      <header className="app-header">
        {!presenting && <button className="mobile-menu" aria-label={menuOpen ? "Đóng điều hướng" : "Mở điều hướng"} aria-expanded={menuOpen} aria-controls="workspace-navigation" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={20} /> : <Menu size={20} />}</button>}
        <span className="header-location">{presenting ? "IPI Guard" : group.label}<span className="header-divider">/</span><span>{loc.pathname.startsWith("/runs/") ? "Chi tiết lượt chạy" : group.items.find((it) => it.to === root)?.label ?? "Đánh giá agent"}</span></span>
        <button className="presentation-toggle" onClick={() => setPresenting(!presenting)} aria-pressed={presenting}>
          {presenting ? <PanelTop size={16} /> : <Monitor size={16} />}{presenting ? "Về làm việc" : "Trình bày"}
        </button>
      </header>

      <div className="workspace-context">
        {presenting ? <div className="presentation-context"><span className="context-label">Đánh giá an toàn AI Agent</span><span>{scoped ? batch || SCOPE_LABEL[kind] : loc.pathname.startsWith("/runs/") ? "Chi tiết run" : group.label}</span></div> : scoped ? <ScopePicker /> : <span className="context-label">Không gian làm việc</span>}
        <div className="workspace-status">
          <span className="connection-state"><span className={clsx("status-dot", meta.error && "is-error")} />{meta.error ? "Mất kết nối" : meta.isLoading ? "Đang kết nối" : meta.data?.live_demo ? "Demo sẵn sàng" : "Chỉ xem"}</span>
          {!presenting && <button className="refresh-button" disabled={refreshing} onClick={refresh} aria-label="Làm mới dữ liệu"><RefreshCw size={14} className={refreshing ? "animate-spin" : ""} /></button>}
          {!presenting && <span className="update-status" role="status">{refreshError ? "Cập nhật thất bại" : refreshing ? "Đang cập nhật…" : updated ? `Làm mới ${updated.toLocaleTimeString("vi-VN")}` : "Tự cập nhật · 15s"}</span>}
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
    </div>
  );
}
