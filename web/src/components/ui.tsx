// Bộ thành phần gốc của console. Trang chỉ ghép các thành phần ở đây; không tự dựng nút, thẻ, nhãn.

import * as RTooltip from "@radix-ui/react-tooltip";
import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, CircleAlert, Info } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { Verdict } from "@/lib/api";
import { BLOCKED_LABEL, OUTCOME_LABEL } from "@/lib/format";

/* ───────────── Bề mặt ───────────── */

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("min-w-0 rounded-lg border border-slate-200 bg-surface", className)}>{children}</div>;
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  /** Không còn hiển thị — tiêu đề khối không mang biểu tượng trang trí. */
  icon?: ReactNode;
}) {
  return (
    <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-2">
      <h2 className="flex min-w-0 flex-1 items-center gap-1.5 text-sm font-semibold text-slate-900">
        {title}
        {/* Giải thích của khối nằm sau ⓘ: mặt giao diện chỉ giữ tiêu đề và số liệu. */}
        {subtitle && <InfoDot>{subtitle}</InfoDot>}
      </h2>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  );
}

/** Tiêu đề một vùng nội dung không nằm trong thẻ. */
export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold text-slate-900">{children}</h2>
      {action}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  info,
  actions,
}: {
  title: string;
  description?: ReactNode;
  info?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <h1 className="flex min-w-0 items-center gap-2 text-xl font-semibold text-slate-900">
        <span className="min-w-0 break-words">{title}</span>
        {(description || info) && (
          <InfoDot>
            {description}
            {description && info && <span className="mt-1.5 block" />}
            {info}
          </InfoDot>
        )}
      </h1>
      {actions && <div className="flex max-w-full flex-wrap items-center gap-2" data-chrome>{actions}</div>}
    </div>
  );
}

/* ───────────── Chú giải ───────────── */

export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <RTooltip.Root>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content
          side={side}
          sideOffset={6}
          collisionPadding={8}
          className="z-50 max-w-xs rounded-md bg-slate-900 px-2.5 py-1.5 text-xs leading-[18px] text-slate-50 shadow-pop"
        >
          {content}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}

export function InfoDot({ children }: { children: ReactNode }) {
  return (
    <Tooltip content={children} side="bottom">
      <button type="button" aria-label="Thông tin chi tiết" className="inline-flex rounded text-slate-400 hover:text-slate-600">
        <Info size={14} />
      </button>
    </Tooltip>
  );
}

/* ───────────── Nhãn và trạng thái ───────────── */

type Tone = "neutral" | "brand" | "attack" | "defense" | "refusal" | "payload" | "canary" | "warn";

const TONE: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-600",
  brand: "bg-brand-50 text-brand-700",
  attack: "bg-attack-50 text-attack-700",
  defense: "bg-defense-50 text-defense-700",
  refusal: "bg-refusal-50 text-refusal-700",
  payload: "bg-payload-50 text-payload-600",
  canary: "bg-canary-50 text-canary-600",
  warn: "bg-amber-50 text-amber-700",
};

const DOT: Record<Tone, string> = {
  neutral: "bg-slate-400",
  brand: "bg-brand-500",
  attack: "bg-attack-500",
  defense: "bg-defense-500",
  refusal: "bg-refusal-500",
  payload: "bg-payload-500",
  canary: "bg-canary-500",
  warn: "bg-amber-400",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  dot,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span className={clsx("inline-flex h-5 items-center gap-1 whitespace-nowrap rounded px-1.5 text-xs font-medium", TONE[tone], className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

/** Trạng thái trong bảng: chấm màu + chữ trung tính. Nghĩa nằm ở chữ, màu chỉ hỗ trợ. */
export function Status({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm text-slate-700">
      <span className={clsx("h-2 w-2 shrink-0 rounded-full", DOT[tone])} aria-hidden="true" />
      {children}
    </span>
  );
}

/** Kết cục một run. `blocked_by` luôn được gọi tên: phòng thủ chặn khác model tự từ chối. */
export function OutcomeBadge({ outcome, blockedBy }: { outcome: string | null; blockedBy?: string | null }) {
  if (!outcome) return <Status tone="warn">Lỗi khi chạy</Status>;
  if (outcome === "success") return <Status tone="attack">{OUTCOME_LABEL.success}</Status>;
  if (outcome === "blocked") {
    const tone: Tone = blockedBy === "defense" ? "defense" : blockedBy === "model_refusal" ? "refusal" : "neutral";
    return <Status tone={tone}>{blockedBy ? `Chặn · ${BLOCKED_LABEL[blockedBy] ?? blockedBy}` : "Bị chặn"}</Status>;
  }
  if (outcome === "pass") return <Status tone="defense">Đạt</Status>;
  if (outcome === "fail") return <Status tone="warn">Không đạt</Status>;
  return <Status>{OUTCOME_LABEL[outcome] ?? outcome}</Status>;
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("font-mono text-xs", className)}>{children}</span>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

/* ───────────── Điều khiển ───────────── */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const BUTTON: Record<ButtonVariant, string> = {
  primary: "bg-slate-900 text-surface hover:bg-slate-800 disabled:bg-slate-300",
  secondary: "border border-slate-200 bg-surface text-slate-700 hover:border-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:text-slate-300",
  danger: "bg-attack-500 text-white hover:bg-attack-600 disabled:bg-slate-300",
};

/** Lớp kiểu của nút — dùng cho `<Link>` hoặc `<a>` cần trông như nút. */
export function buttonClass(variant: ButtonVariant = "secondary", size: "sm" | "md" = "md") {
  return clsx(
    "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors",
    size === "sm" ? "h-7 px-2 text-xs" : "h-8 px-3 text-sm",
    BUTTON[variant],
  );
}

export function Button({
  children,
  onClick,
  variant = "secondary",
  size = "md",
  disabled,
  type = "button",
  className,
  icon,
  ...rest
}: {
  children?: ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  size?: "sm" | "md";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
  icon?: ReactNode;
  "aria-label"?: string;
  "aria-expanded"?: boolean;
  "aria-controls"?: string;
  "aria-pressed"?: boolean;
  title?: string;
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={clsx(buttonClass(variant, size), className)} {...rest}>
      {icon}
      {children}
    </button>
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  className,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  className?: string;
  label?: string;
}) {
  return (
    <label className={clsx("flex flex-col gap-1", className)}>
      {label && <span className="label">{label}</span>}
      <select className="input" value={value} onChange={(e) => onChange(e.target.value as T)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label = "Bộ lọc hiển thị",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; count?: number }[];
  label?: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex max-w-full flex-wrap gap-0.5 rounded-md bg-slate-100 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded px-2.5 text-sm font-medium transition-colors",
            value === o.value ? "bg-surface text-slate-900 shadow-[0_0_0_1px_rgb(var(--n-200))]" : "text-slate-500 hover:text-slate-800",
          )}
        >
          {o.label}
          {o.count !== undefined && <span className="num text-xs text-slate-400">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Tab gạch chân cho nội dung cùng một đối tượng (vd các mặt của một run). */
export function Tabs<T extends string>({
  value,
  onChange,
  options,
  label,
  trailing,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; count?: number }[];
  label: string;
  trailing?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 border-b border-slate-200 px-4">
      <div role="tablist" aria-label={label} className="-mb-px flex max-w-full gap-5 overflow-x-auto">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={value === o.value}
            onClick={() => onChange(o.value)}
            className={clsx(
              "inline-flex h-10 items-center gap-1.5 whitespace-nowrap border-b-2 text-sm font-medium transition-colors",
              value === o.value ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800",
            )}
          >
            {o.label}
            {o.count !== undefined && <span className="num text-xs font-normal text-slate-400">{o.count}</span>}
          </button>
        ))}
      </div>
      {trailing && <div className="py-2">{trailing}</div>}
    </div>
  );
}

/* ───────────── Số liệu ───────────── */

/** Một chỉ số: nhãn, con số, dòng mẫu số. "Chưa đo" hiện bằng chữ, không bao giờ thành 0%. */
export function Metric({
  label,
  value,
  unmeasured,
  children,
}: {
  label: ReactNode;
  value: ReactNode;
  unmeasured?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="min-w-0 px-4 py-3.5">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={clsx("num mt-1.5", unmeasured ? "text-xl text-slate-400" : "text-3xl font-semibold text-slate-900")}>{value}</div>
      {children && <div className="mt-1.5 text-xs leading-[18px] text-slate-500">{children}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  footer,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Card>
      <Metric label={label} value={value}>{hint}</Metric>
      {footer && <div className="border-t border-slate-100 px-4 py-2.5 text-xs">{footer}</div>}
    </Card>
  );
}

/** Thanh tỉ lệ nhỏ kèm khoảng tin cậy (dải nhạt). */
export function RateBar({
  p,
  lo,
  hi,
  tone = "attack",
}: {
  p: number | null | undefined;
  lo?: number | null;
  hi?: number | null;
  tone?: "attack" | "defense" | "brand";
}) {
  const color = { attack: "bg-attack-500", defense: "bg-defense-500", brand: "bg-brand-500" }[tone];
  const band = { attack: "bg-attack-100", defense: "bg-defense-100", brand: "bg-brand-100" }[tone];
  if (p === null || p === undefined) return <div className="h-1 w-full rounded-full bg-slate-100" />;
  return (
    <div className="relative h-1 w-full rounded-full bg-slate-100">
      {lo !== null && lo !== undefined && hi !== null && hi !== undefined && (
        <div className={clsx("absolute inset-y-0 rounded-full", band)} style={{ left: `${lo * 100}%`, width: `${Math.max((hi - lo) * 100, 1)}%` }} />
      )}
      <div className={clsx("absolute inset-y-0 left-0 rounded-full", color)} style={{ width: `${p * 100}%` }} />
    </div>
  );
}

export function KeyValue({ items, columns = 2 }: { items: [string, ReactNode][]; columns?: 2 | 3 | 4 | 6 }) {
  const cols = { 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-2 lg:grid-cols-4", 6: "sm:grid-cols-3 lg:grid-cols-6" }[columns];
  return (
    <dl className={clsx("grid grid-cols-2 gap-x-4 gap-y-3", cols)}>
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-slate-500">{k}</dt>
          <dd className="mt-0.5 break-words text-sm text-slate-800">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ───────────── Trạng thái tải, rỗng, lỗi ───────────── */

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} aria-hidden="true" />;
}

/** Khung chờ giữ chỗ cho nội dung sắp tải — tránh nhảy bố cục. */
export function Loading({ label = "Đang tải dữ liệu…", rows = 6 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3 p-4">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={clsx("h-4", i % 3 === 0 ? "w-2/5" : i % 3 === 1 ? "w-4/5" : "w-3/5")} />
      ))}
    </div>
  );
}

export function Empty({
  title,
  children,
  icon,
  action,
}: {
  title: string;
  children?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon && <div className="mb-2 text-slate-300">{icon}</div>}
      <div className="text-sm font-medium text-slate-800">{title}</div>
      {children && <div className="mt-1 max-w-md text-xs leading-[18px] text-slate-500">{children}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const qc = useQueryClient();
  const [retrying, setRetrying] = useState(false);
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex items-start gap-2.5 rounded-md border border-attack-100 bg-attack-50 px-3 py-2.5 text-sm">
      <CircleAlert size={15} className="mt-0.5 shrink-0 text-attack-600" />
      <div className="min-w-0 flex-1">
        <div className="font-medium text-slate-900">Không tải được dữ liệu</div>
        <div className="mt-0.5 break-words text-slate-600">{msg}</div>
      </div>
      <Button
        size="sm"
        disabled={retrying}
        onClick={async () => {
          setRetrying(true);
          try {
            await qc.refetchQueries({ type: "active" });
          } finally {
            setRetrying(false);
          }
        }}
      >
        {retrying ? "Đang thử lại…" : "Thử lại"}
      </Button>
    </div>
  );
}

export function Callout({
  tone = "warn",
  title,
  children,
  icon,
}: {
  tone?: "warn" | "brand" | "attack" | "defense";
  title?: ReactNode;
  children: ReactNode;
  icon?: ReactNode;
}) {
  const box = {
    warn: "border-amber-200 bg-amber-50",
    brand: "border-slate-200 bg-slate-50",
    attack: "border-attack-100 bg-attack-50",
    defense: "border-defense-100 bg-defense-50",
  }[tone];
  const ink = { warn: "text-amber-600", brand: "text-slate-400", attack: "text-attack-600", defense: "text-defense-600" }[tone];
  return (
    <div className={clsx("flex items-start gap-2.5 rounded-md border px-3 py-2.5 text-sm text-slate-600", box)}>
      <span className={clsx("mt-0.5 shrink-0", ink)}>{icon ?? (tone === "brand" ? <Info size={15} /> : <AlertTriangle size={15} />)}</span>
      <div className="min-w-0">
        {title && <div className="font-medium text-slate-900">{title}</div>}
        {children != null && <div className={clsx(title && "mt-0.5")}>{children}</div>}
      </div>
    </div>
  );
}

export function VerdictBanner({ verdict }: { verdict: Verdict }) {
  const bar = verdict.tone === "attack" ? "bg-attack-500" : verdict.tone === "defense" ? "bg-defense-500" : verdict.tone === "refusal" ? "bg-refusal-500" : "bg-slate-300";
  return (
    <div className="flex gap-3">
      <span className={clsx("w-0.5 shrink-0 rounded-full", bar)} aria-hidden="true" />
      <div className="min-w-0">
        <div className="text-base font-semibold text-slate-900">{verdict.label}</div>
        <div className="mt-0.5 text-sm text-slate-600">{verdict.detail}</div>
      </div>
    </div>
  );
}

/** Phần nội dung phụ gập lại được. */
export function Disclosure({ summary, children, className }: { summary: ReactNode; children: ReactNode; className?: string }) {
  return (
    <details className={clsx("group", className)}>
      <summary className="flex list-none items-center gap-1.5 text-sm font-medium text-slate-700 hover:text-slate-900 [&::-webkit-details-marker]:hidden">
        <svg width="10" height="10" viewBox="0 0 10 10" className="shrink-0 text-slate-400 transition-transform group-open:rotate-90" aria-hidden="true">
          <path d="M3 1.5 6.5 5 3 8.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {summary}
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}
