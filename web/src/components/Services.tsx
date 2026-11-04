// Trạng thái dịch vụ hạ tầng lab (API `/api/services*`, hợp đồng ở config/services.yaml).
// Probe chạy ở backend, có cache dùng chung; ở đây chỉ hỏi lại mỗi 15 giây khi tab đang hiện.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  CheckCircle2,
  CircleHelp,
  CircleMinus,
  ExternalLink,
  KeyRound,
  Loader2,
  Mail,
  RadioTower,
  RefreshCw,
  Server,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { Button, Callout, Card, CardHeader, ErrorBox, Loading, Mono } from "@/components/ui";
import { api, type DemoCheck, type ServiceStatus, type ServicesStatus } from "@/lib/api";
import { when } from "@/lib/format";

export const SERVICES_REFRESH_MS = 15_000;

const STATE: Record<ServiceStatus["status"], { label: string; icon: LucideIcon; cls: string }> = {
  up: { label: "Hoạt động", icon: CheckCircle2, cls: "text-defense-700 bg-defense-50 ring-defense-100" },
  down: { label: "Lỗi", icon: XCircle, cls: "text-attack-700 bg-attack-50 ring-attack-100" },
  unknown: { label: "Không rõ", icon: CircleHelp, cls: "text-amber-700 bg-amber-50 ring-amber-200" },
  not_configured: { label: "Chưa cấu hình", icon: CircleMinus, cls: "text-slate-500 bg-slate-50 ring-slate-200" },
  // Chỉ có cấu hình, chưa probe: không dùng màu xanh "đang hoạt động".
  configured: { label: "Đã cấu hình", icon: KeyRound, cls: "text-slate-700 bg-slate-100 ring-slate-200" },
};

export function useServices() {
  return useQuery({
    queryKey: ["services"],
    queryFn: () => api.services(),
    refetchInterval: SERVICES_REFRESH_MS,
    // Tab ẩn thì ngừng hỏi; react-query không chạy hai lượt chồng nhau cho cùng một khóa.
    refetchIntervalInBackground: false,
    staleTime: 10_000,
  });
}

function StateTag({ s, compact }: { s: ServiceStatus; compact?: boolean }) {
  const st = STATE[s.status];
  const Icon = st.icon;
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 font-medium ring-1 ring-inset", st.cls, compact ? "text-[11px]" : "text-[12px]")}>
      <Icon size={compact ? 12 : 13} aria-hidden="true" />
      {compact ? s.short : st.label}
      {compact && <span className="sr-only">: {st.label}</span>}
    </span>
  );
}

function tip(s: ServiceStatus) {
  const parts = [`${s.label}: ${STATE[s.status].label}`];
  if (s.port) parts.push(`cổng ${s.port}`);
  if (s.latency_ms != null) parts.push(`kiểm tra sức khỏe ${Math.round(s.latency_ms)} ms`);
  if (s.error) parts.push(s.error);
  return parts.join(" · ");
}

/** Dãy trạng thái trên thanh ngữ cảnh: tên ngắn + biểu tượng, không chỉ dựa vào màu. */
export function ServiceStrip() {
  const q = useServices();
  if (q.isLoading) return <span className="text-[11px] text-slate-400">Đang kiểm tra dịch vụ…</span>;
  if (q.error || !q.data) return <span className="text-[11px] text-attack-600">Không đọc được trạng thái dịch vụ</span>;
  return (
    <Link to="/system#services" className="flex flex-wrap items-center gap-1" aria-label="Trạng thái dịch vụ hạ tầng — xem chi tiết">
      {q.data.services.map((s) => (
        <span key={s.id} title={tip(s)}>
          <StateTag s={s} compact />
        </span>
      ))}
    </Link>
  );
}

/** Bảng chi tiết ở trang Hệ thống. */
export function ServicesCard() {
  const qc = useQueryClient();
  const q = useServices();
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<unknown>(null);
  const anchor = useRef<HTMLDivElement>(null);
  const loc = useLocation();
  // Bấm dãy trạng thái ở thanh trên → cuộn tới bảng này.
  useEffect(() => {
    if (loc.hash === "#services") anchor.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [loc.hash, q.isLoading]);
  async function refresh() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      qc.setQueryData<ServicesStatus>(["services"], await api.services(true));
    } catch (e) {
      setRefreshError(e);
    } finally {
      setRefreshing(false);
    }
  }
  return (
    <Card>
      <div id="services" ref={anchor} className="scroll-mt-24" />
      <CardHeader
        title="Dịch vụ hạ tầng"
        icon={<Server size={16} />}
        subtitle="Console kiểm tra từ backend theo đúng địa chỉ harness dùng, mỗi dịch vụ chờ tối đa 1 giây, kết quả dùng chung trong vài giây. Trạng thái xanh chỉ cho biết dịch vụ trả lời được, không chứng minh payload đã tới đúng nơi — xem email và sự kiện canary ở trang Thí nghiệm sau mỗi lượt."
        action={
          <Button onClick={refresh} disabled={refreshing} icon={refreshing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}>
            Làm mới
          </Button>
        }
      />
      {q.isLoading ? (
        <Loading label="Đang kiểm tra dịch vụ…" />
      ) : q.error ? (
        <div className="p-5"><ErrorBox error={q.error} /></div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-[13px]">
            <thead className="border-b border-slate-100 text-[11.5px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-2 font-medium">Dịch vụ</th>
                <th className="px-3 py-2 font-medium">Cổng</th>
                <th className="px-3 py-2 font-medium">Trạng thái</th>
                <th className="px-3 py-2 font-medium">Kiểm tra sức khỏe</th>
                <th className="px-3 py-2 font-medium">Lỗi</th>
                <th className="px-5 py-2 text-right font-medium">Mở</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {q.data!.services.map((s) => (
                <tr key={s.id}>
                  <td className="px-5 py-2.5">
                    <div className="font-semibold text-slate-800">{s.label}</div>
                    <div className="text-[12px] text-slate-500">{s.role}</div>
                  </td>
                  <td className="px-3 py-2.5"><Mono>{s.port ?? "—"}</Mono></td>
                  <td className="px-3 py-2.5"><StateTag s={s} /></td>
                  <td className="px-3 py-2.5 text-[12px] text-slate-600">
                    {s.kind === "config" ? "Không gửi request" : s.latency_ms != null ? `${Math.round(s.latency_ms)} ms` : "—"}
                    <div className="text-slate-400">lúc {when(s.checked_at)}</div>
                  </td>
                  <td className="px-3 py-2.5 text-[12px] text-attack-700">{s.error ?? ""}</td>
                  <td className="px-5 py-2.5 text-right">
                    {s.public_url ? (
                      <a href={s.public_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-brand-700 hover:underline">
                        Mở <ExternalLink size={12} />
                      </a>
                    ) : s.id === "canary" ? (
                      <Link to="/lab" className="text-[12.5px] text-slate-500 hover:text-brand-700">Xem ở Thí nghiệm</Link>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-slate-100 px-5 py-2 text-[11.5px] text-slate-500">
            Kiểm tra lúc {when(q.data!.checked_at)} · tự hỏi lại mỗi {SERVICES_REFRESH_MS / 1000}s khi tab đang mở
          </div>
        </div>
      )}
      {refreshError != null && <div className="px-5 pb-4"><ErrorBox error={refreshError} /></div>}
    </Card>
  );
}

/** Kết quả kiểm tra dịch vụ trước khi chạy demo — chỉ các dịch vụ kịch bản đang chọn cần. */
export function DemoCheckNote({ check }: { check: DemoCheck }) {
  const bad = check.deps.filter((d) => d.status !== "up");
  if (!bad.length) return null;
  const required = bad.filter((d) => d.need === "required");
  const optional = bad.filter((d) => d.need === "optional");
  const line = (d: DemoCheck["deps"][number]) => `${d.label} (${STATE[d.status].label.toLowerCase()}${d.error ? ` — ${d.error}` : ""})`;
  return (
    <div className="space-y-2">
      {required.length > 0 && (
        <Callout tone="attack" title="Dịch vụ bắt buộc của kịch bản này đang lỗi">
          {required.map(line).join(", ")}. Lượt chạy sẽ lỗi hoặc cho số liệu sai. Kiểm tra <Mono>docker compose ps</Mono> rồi thử lại.
        </Callout>
      )}
      {optional.length > 0 && (
        <Callout tone="warn" title="Dịch vụ tùy chọn đang lỗi — vẫn chạy được">
          {optional.map(line).join(", ")}. Scorer vẫn chấm trên trace; chỉ thiếu bước đối chiếu phía hạ tầng.
        </Callout>
      )}
    </div>
  );
}

/** Nghiệm thu sau lượt chạy: email trong MailHog, hit của canary listener, mở Qdrant. */
export function VerifyPanel({ runIds, channel, goal }: { runIds: string[]; channel: string; goal: string }) {
  const [open, setOpen] = useState<"mail" | "canary" | null>(null);
  const services = useServices();
  const qdrant = services.data?.services.find((s) => s.id === "qdrant");
  const mail = useQuery({ queryKey: ["svc-mail", runIds], queryFn: () => api.mail(runIds), enabled: open === "mail" });
  const hits = useQuery({ queryKey: ["svc-canary", runIds], queryFn: () => api.canaryHits(runIds), enabled: open === "canary" });
  const toggle = (k: "mail" | "canary") => setOpen(open === k ? null : k);
  return (
    <Card className="mt-4">
      <CardHeader
        title="Đối chiếu hạ tầng"
        icon={<RadioTower size={16} />}
        subtitle="Xem nội dung đã thực sự rời agent. Scorer chấm trên trace; phần này chỉ để đối chiếu. MailHog không gắn run_id nên email được quy về run theo thời điểm nhận; runner xóa hộp thư ở đầu mỗi run, nên chỉ còn email của run cuối."
      />
      <div className="flex flex-wrap gap-2 px-5 pb-4">
        <Button onClick={() => toggle("mail")} icon={<Mail size={14} />} variant={open === "mail" ? "primary" : "secondary"}>Xem email</Button>
        {goal === "G1" && (
          <Button onClick={() => toggle("canary")} icon={<RadioTower size={14} />} variant={open === "canary" ? "primary" : "secondary"}>Xem sự kiện Canary</Button>
        )}
        {channel === "K1" && qdrant?.public_url && (
          <a href={`${qdrant.public_url}#/collections`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50">
            <ExternalLink size={14} /> Mở Qdrant
          </a>
        )}
      </div>
      {open === "mail" && (
        <div className="border-t border-slate-100 px-5 py-4">
          {mail.isLoading ? <Loading /> : mail.error ? <ErrorBox error={mail.error} /> : mail.data!.status !== "up" ? (
            <Callout tone="warn">MailHog: {mail.data!.status}{mail.data!.error ? ` — ${mail.data!.error}` : ""}</Callout>
          ) : !mail.data!.items.length ? (
            <p className="text-[13px] text-slate-500">Hộp thư trống — không email nào rời agent ở run cuối.</p>
          ) : (
            <ul className="space-y-3">
              {mail.data!.items.map((m) => (
                <li key={m.id} className="rounded-lg border border-slate-100 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-slate-500">
                    <span>Nhận lúc {when(m.received_at)}</span>
                    {m.run_id ? <Link to={`/runs/${m.run_id}`} className="font-mono text-brand-700 hover:underline">{m.run_id}</Link> : <span>không khớp run nào của lượt này</span>}
                  </div>
                  <div className="mt-1 text-[13.5px] font-semibold text-slate-800">{m.subject || "(không tiêu đề)"}</div>
                  <div className="text-[12px] text-slate-600">{m.from} → {m.to.join(", ")}</div>
                  {m.attachments.length > 0 && <div className="text-[12px] text-slate-500">Đính kèm: {m.attachments.join(", ")}</div>}
                  <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-[12px] text-slate-700">{m.snippet}{m.truncated ? "…" : ""}</pre>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {open === "canary" && (
        <div className="border-t border-slate-100 px-5 py-4">
          {hits.isLoading ? <Loading /> : hits.error ? <ErrorBox error={hits.error} /> : hits.data!.status !== "up" ? (
            <Callout tone="warn">Canary listener: {hits.data!.status}{hits.data!.error ? ` — ${hits.data!.error}` : ""}</Callout>
          ) : !hits.data!.items.length ? (
            <p className="text-[13px] text-slate-500">Listener không nhận request nào gắn với các run của lượt này.</p>
          ) : (
            <ul className="space-y-3">
              {hits.data!.items.map((h) => (
                <li key={h.id} className="rounded-lg border border-slate-100 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-slate-500">
                    <span>Nhận lúc {when(h.received_at)}</span>
                    {h.run_id && <Link to={`/runs/${h.run_id}`} className="font-mono text-brand-700 hover:underline">{h.run_id}</Link>}
                  </div>
                  <div className="mt-1 break-all font-mono text-[12.5px] text-slate-800">{h.method} {h.original_url ?? "—"}</div>
                  {h.body_preview && (
                    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-[12px] text-slate-700">
                      {h.body_encoding === "base64" ? `[base64] ${h.body_preview}` : h.body_preview}{h.truncated ? "…" : ""}
                    </pre>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
