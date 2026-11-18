// Khung ứng dụng: thanh trên hai tầng. Tầng trên là luồng làm việc (Tổng quan, 1 Thí nghiệm, 2 Phân tích,
// Hệ thống) và thao tác chung; tầng dưới là các trang của bước hiện tại và phạm vi dữ liệu. Không thanh bên:
// nội dung dùng hết bề ngang, hợp máy chiếu. Dưới 768px các bước gập vào ngăn kéo.
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
import { NAV, NAV_ITEMS, groupOf, locate } from "@/lib/nav";
import { SCOPE_LABEL, type ScopeKind, useScope } from "@/lib/scope";
import { useTheme } from "@/lib/theme";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true" className="shrink-0 text-slate-900">
      <path d="M10 1.5 3 4v5.2c0 4.3 2.9 7.6 7 9.3 4.1-1.7 7-5 7-9.3V4l-7-2.5Z" fill="currentColor" />
      <path d="m6.8 10 2.3 2.3 4.2-4.6" fill="none" stroke="rgb(var(--brand-500))" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ScopePicker() {
  const { kind, batch, setScope } = useScope();
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => api.batches(), refetchInterval: 15_000 });
  const list = (batches.data ?? []).filter((b) => kind === "all" || b.kind === kind);
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <select aria-label="Loại phạm vi dữ liệu" className="input h-8 text-xs" value={kind} onChange={(e) => setScope({ kind: e.target.value as ScopeKind })}>
        {(Object.keys(SCOPE_LABEL) as ScopeKind[]).map((k) => (
          <option key={k} value={k}>{SCOPE_LABEL[k]}</option>
        ))}
      </select>
      <select
        aria-label="Lô dữ liệu"
        className={clsx("input h-8 min-w-0 max-w-[280px] font-mono text-xs", batch && "border-brand-500 bg-brand-50 text-slate-900")}
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
          <button aria-label="Bỏ chọn lô" onClick={() => setScope({ batch: "" })} className="flex touch-target h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted hover:bg-slate-100 hover:text-slate-700">
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
      <button aria-label={label} onClick={onClick} disabled={disabled} className="flex touch-target h-9 w-9 shrink-0 items-center justify-center rounded-md text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 active:bg-slate-200 disabled:opacity-50">
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
  const { item } = locate(loc.pathname);
  const current = groupOf(loc.pathname);
  const onRunDetail = loc.pathname.startsWith("/runs/");
  const scoped = !!item.scoped && !onRunDetail;
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });

  const [presenting, setPresenting] = useState(() => {
    try { return sessionStorage.getItem("ipi-presentation") === "true"; } catch { return false; }
  });
  const [menuOpen, setMenuOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 767px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const update = () => { setMobile(media.matches); if (!media.matches) setMenuOpen(false); };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    const drawer = drawerRef.current;
    const content = contentRef.current;
    if (!drawer || !content) return;
    drawer.inert = !menuOpen;
    content.inert = mobile && menuOpen;
    if (!mobile || !menuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(drawer.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), [tabindex="0"]')).filter((el) => el.getClientRects().length > 0);
    focusable()[0]?.focus();
    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const elements = focusable();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    drawer.addEventListener("keydown", trap);
    return () => {
      content.inert = false;
      drawer.removeEventListener("keydown", trap);
      document.body.style.overflow = previousOverflow;
      menuButtonRef.current?.focus();
    };
  }, [mobile, menuOpen, presenting]);
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
  const subItems = current.items.length > 1 ? current.items : [];

  return (
    <div className="min-h-screen" data-presenting={presenting || undefined}>
      <a href="#main-content" className="fixed left-4 top-[-100px] z-[100] rounded-md bg-slate-900 px-3 py-2 text-sm text-surface focus:top-4">
        Đến nội dung chính
      </a>

      {/* Ngăn kéo điều hướng: chỉ dùng dưới 768px, liệt kê mọi bước và trang. */}
      {menuOpen && <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setMenuOpen(false)} aria-hidden="true" />}
      <aside
        ref={drawerRef}
        role={menuOpen ? "dialog" : undefined}
        aria-modal={menuOpen ? true : undefined}
        aria-label="Điều hướng không gian làm việc"
        id="workspace-navigation"
        data-chrome
        className={clsx(
          "fixed inset-y-0 left-0 z-40 flex w-72 max-w-[85vw] flex-col border-r border-slate-200 bg-ground transition-transform md:hidden",
          menuOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 px-3">
          <button type="button" aria-label="Đóng điều hướng" onClick={() => setMenuOpen(false)} className="touch-target flex h-9 w-9 items-center justify-center rounded-md hover:bg-slate-100"><X size={18} /></button>
          <span className="flex items-center gap-2.5 text-md font-semibold text-slate-900"><Logo /> IPI Guard</span>
        </div>
        <nav aria-label="Điều hướng chính" className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
          {NAV.map((g, i) => (
            <div key={i}>
              {g.label && (
                <div className="flex items-center gap-2 px-2 pb-1.5 text-xs font-medium text-slate-600">
                  {g.step ? <StepNo n={g.step} /> : null}
                  {g.label}
                </div>
              )}
              {g.items.map((it) => (
                <NavLink
                  key={it.to}
                  end={it.to === "/"}
                  to={href(it.to, it.scoped)}
                  className={({ isActive }) =>
                    clsx(
                      "flex h-11 items-center gap-2.5 rounded-md px-2 text-sm",
                      isActive ? "bg-surface font-medium text-slate-900 shadow-[inset_0_0_0_1px_rgb(var(--n-200))] [&>svg]:text-brand-600" : "text-slate-700 hover:bg-slate-100 [&>svg]:text-slate-500",
                    )
                  }
                >
                  <it.icon size={16} strokeWidth={1.75} className="shrink-0" />
                  {it.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <div ref={contentRef}>
        <header data-chrome={presenting ? undefined : true} className="sticky top-0 z-20 border-b border-slate-200 bg-ground">
          {/* Tầng trên: thương hiệu, các bước của luồng, thao tác chung. */}
          <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-2 px-4 md:px-8">
            <button
              ref={menuButtonRef}
              className="touch-target flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-slate-700 hover:bg-slate-100 md:hidden"
              aria-label={menuOpen ? "Đóng điều hướng" : "Mở điều hướng"}
              aria-expanded={menuOpen}
              aria-controls="workspace-navigation"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              {menuOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
            <Link to={href("/", true)} className="mr-4 flex shrink-0 items-center gap-2.5 rounded-md px-1 py-1 text-md font-semibold text-slate-900">
              <Logo />
              <span className="hidden sm:inline">IPI Guard</span>
            </Link>

            <nav aria-label="Các bước làm việc" className="hidden h-full items-stretch md:flex">
              {NAV.map((g, i) => {
                const first = g.items[0];
                const active = g === current;
                return (
                  <Link
                    key={i}
                    to={href(first.to, first.scoped)}
                    aria-current={active ? "page" : undefined}
                    className={clsx(
                      "-mb-px flex items-center gap-2 border-b-2 px-3 text-sm transition-colors",
                      active ? "border-brand-500 font-medium text-slate-900" : "border-transparent text-slate-600 hover:text-slate-900 active:text-slate-900",
                    )}
                  >
                    {g.step ? <StepNo n={g.step} active={active} /> : null}
                    {g.label ?? first.label}
                  </Link>
                );
              })}
            </nav>

            <div className="ml-auto flex min-w-0 items-center gap-1.5">
              {!presenting && (
                <>
                  <button
                    onClick={() => setPaletteOpen(true)}
                    className="hidden h-9 items-center gap-2 rounded-md border border-slate-300 bg-surface px-3 text-sm text-muted transition-colors hover:border-slate-400 hover:text-slate-700 active:bg-slate-50 lg:flex"
                  >
                    <Search size={14} />
                    <span className="pr-6">Tìm run, lô, trang</span>
                    <span className="flex gap-0.5"><Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd><Kbd>K</Kbd></span>
                  </button>
                  <span className="lg:hidden">
                    <IconButton label="Tìm kiếm" onClick={() => setPaletteOpen(true)}>
                      <Search size={15} />
                    </IconButton>
                  </span>
                  <IconButton label={refreshNote || "Làm mới dữ liệu, tự cập nhật mỗi 15 giây"} onClick={refresh} disabled={refreshing}>
                    <RefreshCw size={15} className={refreshing ? "animate-spin" : ""} />
                  </IconButton>
                  <IconButton label={theme.resolved === "dark" ? "Nền sáng" : "Nền tối"} onClick={theme.toggle}>
                    {theme.resolved === "dark" ? <Sun size={15} /> : <Moon size={15} />}
                  </IconButton>
                </>
              )}
              <Button size="sm" onClick={() => setPresenting(!presenting)} aria-pressed={presenting} icon={<Monitor size={13} />}>
                {presenting ? "Thoát trình bày" : "Trình bày"}
              </Button>
            </div>
            <span className="sr-only" role="status">{refreshing ? "Đang cập nhật" : refreshNote}</span>
          </div>

          {/* Tầng dưới: trang trong bước hiện tại (hoặc đường dẫn về danh sách run), phạm vi dữ liệu, dịch vụ. */}
          <div className="border-t border-slate-200 bg-surface">
            <div className="mx-auto flex min-h-11 max-w-[1440px] flex-wrap items-center gap-x-6 px-4 md:px-8">
              {onRunDetail ? (
                <nav aria-label="Vị trí hiện tại" className="flex min-w-0 items-center gap-1.5 text-sm">
                  <Link to={`/runs${loc.search}`} className="text-slate-600 hover:text-slate-900">{item.label}</Link>
                  <ChevronRight size={14} className="shrink-0 text-slate-400" />
                  <span className="truncate font-mono text-xs text-slate-900">{loc.pathname.split("/")[2]?.slice(0, 12)}</span>
                </nav>
              ) : subItems.length ? (
                <nav aria-label={`Trang trong bước ${current.label ?? ""}`} className="flex max-w-full items-stretch gap-1 overflow-x-auto overflow-y-hidden">
                  {subItems.map((it) => (
                    <NavLink
                      key={it.to}
                      to={href(it.to, it.scoped)}
                      className={({ isActive }) =>
                        clsx(
                          "-mb-px flex h-11 shrink-0 items-center gap-2 border-b-2 px-2.5 text-sm transition-colors",
                          isActive ? "border-slate-900 font-medium text-slate-900 [&>svg]:text-brand-600" : "border-transparent text-slate-600 hover:text-slate-900 [&>svg]:text-slate-400",
                        )
                      }
                    >
                      <it.icon size={15} strokeWidth={1.75} className="shrink-0" />
                      {it.label}
                    </NavLink>
                  ))}
                </nav>
              ) : (
                <span className="text-sm font-medium text-slate-900">{item.label}</span>
              )}

              <div className="ml-auto flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 py-1.5">
                {scoped && !presenting && <ScopePicker />}
                {scoped && presenting && <span className="truncate text-sm text-slate-600">{batch || SCOPE_LABEL[kind]}</span>}
                {!presenting && <div className="hidden xl:block"><ServiceStrip /></div>}
              </div>
            </div>
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-[1440px] px-4 pb-12 pt-8 outline-none md:px-8">
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>

        <footer data-chrome className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-6 gap-y-1 border-t border-slate-200 px-4 py-4 text-xs text-slate-600 md:px-8">
          <span className="flex items-center gap-2">
            <span className={clsx("h-3.5 w-[3px] rounded-sm", meta.error ? "bg-attack-500" : meta.isLoading ? "bg-amber-400" : "bg-defense-500")} aria-hidden="true" />
            {conn}
          </span>
          <Link to="/config" className="font-mono text-2xs text-muted hover:text-slate-800" title="Phiên bản bộ model đang ghim">{meta.data?.model_tag ?? "—"}</Link>
          <Link to="/config" className="font-mono text-2xs text-muted hover:text-slate-800" title="Phiên bản bộ payload đang ghim">{meta.data?.attack_tag ?? "—"}</Link>
        </footer>
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

/** Ô số bước của luồng (1 Thí nghiệm, 2 Phân tích). */
function StepNo({ n, active }: { n: number; active?: boolean }) {
  return (
    <span
      className={clsx(
        "num flex h-5 w-5 shrink-0 items-center justify-center rounded border font-mono text-2xs",
        active ? "border-brand-500 bg-brand-500 text-accent-ink" : "border-slate-300 bg-surface text-slate-700",
      )}
    >
      {n}
    </span>
  );
}
