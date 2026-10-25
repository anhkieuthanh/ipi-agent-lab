import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import type { Verdict } from "@/lib/api";
import { BLOCKED_LABEL, OUTCOME_LABEL } from "@/lib/format";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("card", className)}>{children}</div>;
}

export function CardHeader({
  title,
  subtitle,
  action,
  icon,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-slate-900">{title}</h3>
          {subtitle && <p className="mt-0.5 text-[13px] text-slate-500">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-[13.5px] text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

type Tone = "neutral" | "brand" | "attack" | "defense" | "refusal" | "payload" | "canary" | "warn";

const TONE: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-100",
  attack: "bg-attack-50 text-attack-700 ring-attack-100",
  defense: "bg-defense-50 text-defense-700 ring-defense-100",
  refusal: "bg-refusal-50 text-refusal-700 ring-refusal-100",
  payload: "bg-payload-50 text-payload-600 ring-payload-100",
  canary: "bg-canary-50 text-canary-600 ring-canary-100",
  warn: "bg-amber-50 text-amber-700 ring-amber-200",
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
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-0.5 text-[12px] font-medium ring-1 ring-inset",
        TONE[tone],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("font-mono text-[12.5px]", className)}>{children}</span>;
}

export function Button({
  children,
  onClick,
  variant = "secondary",
  disabled,
  type = "button",
  className,
  icon,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
  icon?: ReactNode;
}) {
  const styles = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm disabled:bg-slate-300",
    secondary:
      "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
    ghost: "text-slate-600 hover:bg-slate-100 disabled:text-slate-300",
    danger: "bg-attack-600 text-white hover:bg-attack-700 disabled:bg-slate-300",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3.5 text-[13.5px] font-medium transition disabled:cursor-not-allowed",
        styles,
        className,
      )}
    >
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
      <select
        className="input pr-8"
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
      >
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
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; count?: number }[];
}) {
  return (
    <div className="inline-flex rounded-lg bg-slate-100 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition",
            value === o.value ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800",
          )}
        >
          {o.label}
          {o.count !== undefined && (
            <span className="rounded bg-slate-200/70 px-1.5 text-[11px] text-slate-600">{o.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
  icon,
  footer,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  footer?: ReactNode;
}) {
  const accent = {
    neutral: "text-slate-500 bg-slate-100",
    brand: "text-brand-600 bg-brand-50",
    attack: "text-attack-600 bg-attack-50",
    defense: "text-defense-600 bg-defense-50",
    refusal: "text-refusal-600 bg-refusal-50",
    payload: "text-payload-600 bg-payload-50",
    canary: "text-canary-600 bg-canary-50",
    warn: "text-amber-600 bg-amber-50",
  }[tone];
  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium text-slate-500">{label}</span>
        {icon && <span className={clsx("flex h-8 w-8 items-center justify-center rounded-lg", accent)}>{icon}</span>}
      </div>
      <div className="num mt-3 text-[28px] font-semibold leading-none tracking-tight text-slate-900">{value}</div>
      {hint && <div className="mt-2 text-[12.5px] text-slate-500">{hint}</div>}
      {footer && <div className="mt-4 border-t border-slate-100 pt-3 text-[12.5px]">{footer}</div>}
    </Card>
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
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-slate-400">
        {icon ?? <Inbox size={20} />}
      </div>
      <div className="text-[14px] font-semibold text-slate-800">{title}</div>
      {children && <div className="mt-1 max-w-md text-[13px] text-slate-500">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Loading({ label = "Đang tải dữ liệu…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-slate-500">
      <Loader2 size={16} className="animate-spin" />
      {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex items-start gap-3 rounded-xl border border-attack-100 bg-attack-50 p-4 text-[13px] text-attack-700">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <div>
        <div className="font-semibold">Không tải được dữ liệu</div>
        <div className="mt-0.5">{msg}</div>
      </div>
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
  const styles = {
    warn: "border-amber-200 bg-amber-50 text-amber-800",
    brand: "border-brand-100 bg-brand-50 text-brand-700",
    attack: "border-attack-100 bg-attack-50 text-attack-700",
    defense: "border-defense-100 bg-defense-50 text-defense-700",
  }[tone];
  return (
    <div className={clsx("flex items-start gap-3 rounded-xl border p-3.5 text-[13px]", styles)}>
      <span className="mt-0.5 shrink-0">{icon ?? <AlertTriangle size={16} />}</span>
      <div>
        {title && <div className="font-semibold">{title}</div>}
        <div className={clsx(title && "mt-0.5")}>{children}</div>
      </div>
    </div>
  );
}

/** Thanh tỉ lệ nhỏ kèm khoảng tin cậy (vạch mờ). */
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
  if (p === null || p === undefined) return <div className="h-1.5 w-full rounded-full bg-slate-100" />;
  return (
    <div className="relative h-1.5 w-full rounded-full bg-slate-100">
      {lo !== null && lo !== undefined && hi !== null && hi !== undefined && (
        <div
          className={clsx("absolute inset-y-0 rounded-full", band)}
          style={{ left: `${lo * 100}%`, width: `${Math.max((hi - lo) * 100, 1)}%` }}
        />
      )}
      <div className={clsx("absolute inset-y-0 left-0 rounded-full", color)} style={{ width: `${p * 100}%` }} />
    </div>
  );
}

export function OutcomeBadge({ outcome, blockedBy }: { outcome: string | null; blockedBy?: string | null }) {
  if (!outcome) return <Badge tone="warn">Lỗi khi chạy</Badge>;
  if (outcome === "success") return <Badge tone="attack" dot>{OUTCOME_LABEL.success}</Badge>;
  if (outcome === "blocked") {
    const tone = blockedBy === "defense" ? "defense" : "refusal";
    return (
      <Badge tone={tone} dot>
        {blockedBy ? `Chặn · ${BLOCKED_LABEL[blockedBy] ?? blockedBy}` : "Bị chặn"}
      </Badge>
    );
  }
  if (outcome === "pass") return <Badge tone="defense" dot>Đạt</Badge>;
  if (outcome === "fail") return <Badge tone="warn" dot>Không đạt</Badge>;
  return <Badge dot>{OUTCOME_LABEL[outcome] ?? outcome}</Badge>;
}

export function VerdictBanner({ verdict }: { verdict: Verdict }) {
  const styles = {
    attack: "from-attack-600 to-attack-500",
    defense: "from-defense-600 to-defense-500",
    refusal: "from-refusal-600 to-refusal-500",
    neutral: "from-slate-600 to-slate-500",
  }[verdict.tone];
  return (
    <div className={clsx("rounded-xl bg-gradient-to-br p-4 text-white shadow-card", styles)}>
      <div className="text-[15px] font-semibold tracking-wide">{verdict.label}</div>
      <div className="mt-1 text-[13px] text-white/85">{verdict.detail}</div>
    </div>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="label">{k}</dt>
          <dd className="mt-1 truncate text-[13.5px] text-slate-800">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
