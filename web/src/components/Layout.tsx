// Khung ứng dụng: thanh bên điều hướng, một thanh trên (vị trí · phạm vi · trạng thái), nội dung.
// Phím tắt: ⌘K / Ctrl+K mở bảng lệnh; `g` rồi một chữ để đổi trang; Esc thoát chế độ trình bày.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronRight, Menu, Monitor, Moon, RefreshCw, Search, Sun, X } from "lucide-react";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { CommandPalette } from "@/components/CommandPalette";
import { ServiceStrip } from "@/components/Services";
import { Button, Kbd, Loading, Tooltip } from "@/components/ui";
import { api } from "@/lib/api";
import { NAV, NAV_ITEMS, locate } from "@/lib/nav";
import { SCOPE_LABEL, type ScopeKind, useScope } from "@/lib/scope";
import { useTheme } from "@/lib/theme";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

function Logo() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true" className="shrink-0 text-slate-900">
      <path d="M10 1.5 3 4v5.2c0 4.3 2.9 7.6 7 9.3 4.1-1.7 7-5 7-9.3V4l-7-2.5Z" fill="currentColor" />
      <path d="m6.8 10 2.3 2.3 4.2-4.6" fill="none" stroke="rgb(var(--surface))" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ScopePicker() {
  const { kind, batch, setScope } = useScope();
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => api.batches(), refetchInterval: 15_000 });
  const list = (batches.data ?? []).filter((b) => kind === "all" || b.kind === kind);
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <select aria-label="Loại phạm vi dữ liệu" className="input h-7 text-xs" value={kind} onChange={(e) => setScope({ kind: e.target.value as ScopeKind })}>
        {(Object.keys(SCOPE_LABEL) as ScopeKind[]).map((k) => (
          <option key={k} value={k}>{SCOPE_LABEL[k]}</option>
        ))}
      </select>
      <select
        aria-label="Lô dữ liệu"
        className={clsx("input h-7 min-w-0 max-w-[260px] font-mono text-xs", batch && "border-brand-500 text-slate-900")}
        value={batch}
        onChange={(e) => setScope({ batch: e.target.value })}
        disabled={batches.isLoading || !!batches.error}
      >
        <option value="">{batches.isLoading ? "Đang tải lô…" : batches.error ? "Không tải được lô" : `Tất cả lô (${list.length})`}</option>
        {list.map((b) => (
          <option key={b.batch_id} value={b.batch_id}>{b.batch_id}</option>
        ))}
      </select>
      {batch && (
        <Tooltip content="Bỏ chọn lô">
          <button aria-label="Bỏ chọn lô" onClick={() => setScope({ batch: "" })} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X size={14} />
          </button>
        </Tooltip>
      )}
    </div>
  );
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <Tooltip content={label} side="bottom">
      <button aria-label={label} onClick={onClick} disabled={disabled} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:opacity-50">
        {children}
      </button>
    </Tooltip>
  );
}

export function Layout() {
  const loc = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { kind, batch } = useScope();
  const theme = useTheme();
  const { item, group } = locate(loc.pathname);
  const onRunDetail = loc.pathname.startsWith("/runs/");
  const scoped = !!item.scoped && !onRunDetail;
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });

  const [presenting, setPresenting] = useState(() => {
    try { return sessionStorage.getItem("ipi-presentation") === "true"; } catch { return false; }
  });
  const [menuOpen, setMenuOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState("");

  useEffect(() => { setMenuOpen(false); }, [loc.pathname]);
  useEffect(() => {
    try { sessionStorage.setItem("ipi-presentation", String(presenting)); } catch { /* chỉ mất ghi nhớ phiên */ }
  }, [presenting]);

  const scopeSearch = (() => {
    const sp = new URLSearchParams();
    sp.set("scope", kind);
    if (batch) sp.set("batch", batch);
    return sp.toString();
  })();
  const href = useCallback((to: string, keepScope?: boolean) => ({ pathname: to, search: keepScope ? scopeSearch : "" }), [scopeSearch]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await qc.refetchQueries({ type: "active" }, { throwOnError: true });
      setRefreshNote(`Đã làm mới lúc ${new Date().toLocaleTimeString("vi-VN")}`);
    } catch {
      setRefreshNote("Làm mới thất bại");
    } finally {
      setRefreshing(false);
    }
  }, [qc]);

  // Phím tắt toàn cục. Bỏ qua khi đang gõ trong ô nhập.
  const pendingG = useRef(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      if (e.key === "Escape") {
        setPresenting(false);
        setMenuOpen(false);
        return;
      }
      const t = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))) return;
      const k = e.key.toLowerCase();
      if (k === "g") {
        pendingG.current = Date.now();
        return;
      }
      if (Date.now() - pendingG.current < 1200) {
        pendingG.current = 0;
        const dest = NAV_ITEMS.find((it) => it.key === k);
        if (dest) {
          e.preventDefault();
          navigate(href(dest.to, dest.scoped));
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, href]);

  const conn = meta.error ? "Mất kết nối API" : meta.isLoading ? "Đang kết nối" : meta.data?.live_demo ? "Demo sẵn sàng" : "Chỉ xem";

  return (
    <div className="min-h-screen" data-presenting={presenting || undefined}>
      <a href="#main-content" className="fixed left-4 top-[-100px] z-[100] rounded-md bg-slate-900 px-3 py-2 text-sm text-surface focus:top-4">
        Đến nội dung chính
      </a>

      {!presenting && menuOpen && <div className="fixed inset-0 z-30 bg-slate-900/20 md:hidden" onClick={() => setMenuOpen(false)} aria-hidden="true" />}

      {!presenting && (
        <aside
          id="workspace-navigation"
          data-chrome
          className={clsx(
            "fixed inset-y-0 left-0 z-40 flex w-[var(--sidebar-w)] flex-col border-r border-slate-200 bg-slate-50 transition-transform md:translate-x-0",
            menuOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <div className="flex h-[var(--topbar-h)] shrink-0 items-center px-3">
            <Link to={href("/", true)} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-base font-semibold text-slate-900">
              <Logo />
              IPI Guard
            </Link>
          </div>

          <div className="px-3 pb-2">
            <button
              onClick={() => setPaletteOpen(true)}
              className="flex h-8 w-full items-center gap-2 rounded-md border border-slate-200 bg-surface px-2.5 text-sm text-slate-400 transition-colors hover:border-slate-300 hover:text-slate-600"
            >
              <Search size={14} />
              <span className="flex-1 text-left">Tìm kiếm</span>
              <span className="flex gap-0.5"><Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd><Kbd>K</Kbd></span>
            </button>
          </div>

          <nav aria-label="Điều hướng chính" className="flex-1 space-y-4 overflow-y-auto px-3 py-2">
            {NAV.map((g, i) => (
              <div key={i}>
                {g.label && <div className="px-2 pb-1 text-2xs font-medium text-slate-400">{g.label}</div>}
                <div className="space-y-px">
                  {g.items.map((it) => (
                    <NavLink
                      key={it.to}
                      end={it.to === "/"}
                      to={href(it.to, it.scoped)}
                      className={({ isActive }) =>
                        clsx(
                          "flex h-8 items-center gap-2.5 rounded-md px-2 text-sm transition-colors",
                          isActive ? "bg-slate-200/70 font-medium text-slate-900" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                        )
                      }
                    >
                      <it.icon size={15} strokeWidth={1.75} className="shrink-0" />
                      {it.label}
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </nav>

          <div className="shrink-0 space-y-1.5 border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            <div className="flex items-center gap-2">
              <span className={clsx("h-1.5 w-1.5 rounded-full", meta.error ? "bg-attack-500" : meta.isLoading ? "bg-amber-400" : "bg-defense-500")} />
              {conn}
            </div>
            <Link to="/config" className="block truncate font-mono text-2xs text-slate-400 hover:text-slate-700" title="Phiên bản bộ model và bộ payload đang ghim">
              {meta.data?.model_tag ?? "—"} · {meta.data?.attack_tag ?? "—"}
            </Link>
          </div>
        </aside>
      )}

      <div className={clsx(!presenting && "md:pl-[var(--sidebar-w)]")}>
        <header data-chrome className="sticky top-0 z-20 flex h-[var(--topbar-h)] items-center gap-3 border-b border-slate-200 bg-surface/90 px-4 backdrop-blur md:px-6">
          {!presenting && (
            <button
              className="flex h-8 w-8 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 md:hidden"
              aria-label={menuOpen ? "Đóng điều hướng" : "Mở điều hướng"}
              aria-expanded={menuOpen}
              aria-controls="workspace-navigation"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              {menuOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          )}

          <nav aria-label="Vị trí hiện tại" className="flex min-w-0 items-center gap-1.5 text-sm">
            {presenting && <span className="flex items-center gap-2 font-semibold text-slate-900"><Logo /> IPI Guard</span>}
            {!presenting && group && <span className="hidden text-slate-400 sm:inline">{group}</span>}
            {(presenting || group) && <ChevronRight size={13} className={clsx("shrink-0 text-slate-300", !presenting && "hidden sm:block")} />}
            {onRunDetail ? (
              <>
                <Link to={`/runs${loc.search}`} className="text-slate-500 hover:text-slate-900">{item.label}</Link>
                <ChevronRight size={13} className="shrink-0 text-slate-300" />
                <span className="truncate font-mono text-xs text-slate-900">{loc.pathname.split("/")[2]?.slice(0, 12)}</span>
              </>
            ) : (
              <span className="truncate font-medium text-slate-900">{item.label}</span>
            )}
          </nav>

          <div className="ml-auto flex min-w-0 items-center gap-2">
            {scoped && !presenting && <div className="hidden lg:block"><ScopePicker /></div>}
            {scoped && presenting && <span className="truncate text-sm text-slate-500">{batch || SCOPE_LABEL[kind]}</span>}
            {!presenting && <div className="hidden xl:block"><ServiceStrip /></div>}
            {!presenting && (
              <>
                <span className="mx-1 hidden h-4 w-px bg-slate-200 sm:block" />
                <IconButton label={refreshNote || "Làm mới dữ liệu · tự cập nhật mỗi 15 giây"} onClick={refresh} disabled={refreshing}>
                  <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
                </IconButton>
                <IconButton label={theme.resolved === "dark" ? "Nền sáng" : "Nền tối"} onClick={theme.toggle}>
                  {theme.resolved === "dark" ? <Sun size={14} /> : <Moon size={14} />}
                </IconButton>
              </>
            )}
            <Button size="sm" onClick={() => setPresenting(!presenting)} aria-pressed={presenting} icon={<Monitor size={13} />}>
              {presenting ? "Thoát trình bày" : "Trình bày"}
            </Button>
          </div>
          <span className="sr-only" role="status">{refreshing ? "Đang cập nhật" : refreshNote}</span>
        </header>

        {scoped && !presenting && (
          <div data-chrome className="border-b border-slate-200 px-4 py-2 lg:hidden">
            <ScopePicker />
          </div>
        )}

        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-[1360px] px-4 py-6 outline-none md:px-6">
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        scopeSearch={scopeSearch}
        dark={theme.resolved === "dark"}
        onToggleTheme={theme.toggle}
        onTogglePresent={() => setPresenting((p) => !p)}
        onRefresh={refresh}
      />
    </div>
  );
}
