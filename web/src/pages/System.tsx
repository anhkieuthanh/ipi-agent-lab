import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { AssetPanel, type AssetCode } from "@/components/AssetPanel";
import { ServicesCard } from "@/components/Services";
import { MapLegend, SystemMap } from "@/components/SystemMap";
import { Badge, Card, CardHeader, ErrorBox, InfoDot, Loading, Mono, PageHeader, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { GLOSSARY } from "@/lib/glossary";

type Info = { title: string; codes: string[]; desc: string };

/** Thông tin từng thành phần khi bấm trên sơ đồ — ngắn, chỉ cái cần để đọc sơ đồ. */
const INFO: Record<string, Info> = {
  user: { title: "Nhân viên", codes: ["CT-01…06", "U1–U5"], desc: "Giao tác vụ nghiệp vụ hợp lệ cho agent. Không nhìn thấy payload." },
  sys: { title: "System prompt", codes: ["TS1"], desc: "Quy tắc nghiệp vụ và danh sách tool. Có canary để phát hiện bị lộ." },
  ctx: { title: "Ghép ngữ cảnh", codes: ["D1"], desc: "Gộp câu hỏi, tài liệu truy hồi, kết quả tool thành đầu vào cho LLM. D1 bọc ranh giới dữ liệu ở đây." },
  llm: { title: "LLM", codes: ["A1", "A2", "A3"], desc: "Mô hình đích quyết định gọi tool nào hoặc trả lời. Đây là nơi payload cố đánh lừa." },
  loop: { title: "Vòng lặp agent", codes: [], desc: "Lặp: suy luận → gọi tool → nhận kết quả, đến khi trả lời hoặc hết số bước." },
  search_kb: { title: "search_kb", codes: ["K1"], desc: "Truy hồi tài liệu từ kho tri thức. Tài liệu độc (K1) vào ngữ cảnh qua đây." },
  query_customer_db: { title: "query_customer_db", codes: ["TS2"], desc: "Đọc bản ghi khách hàng, nguồn dữ liệu kẻ tấn công muốn rò." },
  http_request: { title: "http_request", codes: ["TS3", "G1"], desc: "Gọi API. Gửi ra đích lạ = kênh rò dữ liệu." },
  send_email: { title: "send_email", codes: ["TS3", "G1", "G2"], desc: "Gửi email ra ngoài, hành động nguy hiểm nhất." },
  create_ticket: { title: "create_ticket", codes: ["TS3", "G2"], desc: "Ghi phiếu nội bộ, hành động ngoài phạm vi nếu không được yêu cầu." },
  kb: { title: "Kho tri thức", codes: ["K1"], desc: "Vector store Qdrant chứa tài liệu nội bộ; kẻ tấn công cài tài liệu độc vào đây." },
  db: { title: "customers.db", codes: ["TS2"], desc: "Dữ liệu khách hàng mô phỏng (Faker), có bản ghi mồi canary." },
  canary: { title: "Canary listener", codes: ["G1"], desc: "Bồn nhận HTTP. Canary xuất hiện ở đây = rò dữ liệu thành công." },
  mail: { title: "MailHog", codes: ["G1", "G2"], desc: "Hộp thư giả nhận mọi email agent gửi." },
  tickets: { title: "Kho phiếu", codes: ["G2"], desc: "Lưu phiếu agent tạo, để chấm hành động trái phép." },
  attacker: { title: "Kẻ tấn công", codes: ["K1", "K2a", "K2b", "T1–T8"], desc: "Không chạm vào agent trực tiếp, chỉ cài payload vào dữ liệu agent sẽ đọc." },
  trace: { title: "Trace store", codes: [], desc: "Ghi mọi bước của mọi run, kèm ai đã chặn (blocked_by): phòng thủ · model từ chối · harness." },
  scorer: { title: "Scorer", codes: ["G1", "G2", "G3"], desc: "Chấm tự động từng run theo ba mục tiêu; đã kiểm chứng 8/8 ca." },
  console: { title: "Console", codes: ["ASR", "DSR", "USR", "FRR"], desc: "Tổng hợp chỉ số, khoảng tin cậy Wilson 95%." },
  D1: { title: "D1 · Spotlighting", codes: ["context_assembly"], desc: "Đánh dấu nội dung ngoài là dữ liệu, không phải chỉ thị." },
  D2: { title: "D2 · Input Sanitizer", codes: ["kb_retrieval", "tool_result"], desc: "Làm sạch tài liệu truy hồi và kết quả tool trước khi vào ngữ cảnh." },
  D3: { title: "D3 · Tool-call Policy", codes: ["pre_tool_execution"], desc: "Chặn tool không hợp loại tác vụ; hỏi xác nhận hành động ghi. Chạy ngoài LLM." },
  D4: { title: "D4 · Egress Filter", codes: ["pre_egress"], desc: "Soát dữ liệu trước khi rời hệ thống: canary, đích lạ, PII." },
};

function codeTone(code: string) {
  if (code.startsWith("G")) return "attack" as const;
  if (code.startsWith("D")) return "defense" as const;
  if (code.startsWith("K") || code.startsWith("T")) return "payload" as const;
  if (code.startsWith("A")) return "brand" as const;
  return "neutral" as const;
}

function ComponentTip({ id }: { id: string }) {
  const info = INFO[id];
  if (!info) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-base font-medium text-slate-900">{info.title}</div>
      {info.codes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {info.codes.map((c) => (
            <Badge key={c} tone={codeTone(c)} className="font-mono">
              {c}
            </Badge>
          ))}
        </div>
      )}
      <p className="text-xs leading-[18px] text-slate-600">{info.desc}</p>
    </div>
  );
}

export function SystemPage() {
  const [tab, setTab] = useState(GLOSSARY[0].id);
  const [asset, setAsset] = useState<AssetCode | null>(null);
  const group = GLOSSARY.find((g) => g.id === tab)!;
  const isTS = tab === "TS";

  return (
    <>
      <PageHeader title="Hệ thống" info="Rê chuột lên một thành phần hoặc điểm phòng thủ để xem giải thích." />

      <div className="space-y-4">
        <Card>
          <CardHeader title="Sơ đồ kiến trúc lab" subtitle="Luồng tác vụ, ba đường tiêm K1 · K2a · K2b, điểm móc phòng thủ D1–D4 và hệ đo." />
          <div className="border-t border-slate-100 px-3 py-3">
            <SystemMap renderTip={(id) => <ComponentTip id={id} />} />
          </div>
          <div className="border-t border-slate-100 px-4 py-2.5">
            <MapLegend />
          </div>
        </Card>

        <Card>
          <CardHeader title="Chú giải mã" subtitle="Một khái niệm, một ký hiệu, dùng thống nhất trên mọi trang." />
          <Tabs
            id="system-glossary"
            label="Nhóm mã"
            value={tab}
            onChange={setTab}
            options={GLOSSARY.map((g) => ({ value: g.id, label: `${g.prefix} · ${g.label}` }))}
          />
          <div id="system-glossary-panel" role="tabpanel" aria-labelledby={`system-glossary-tab-${tab}`} tabIndex={0}>
          {tab === "CT" ? (
            <CarrierTasks />
          ) : (
            <ul className="divide-y divide-slate-100">
              {group.items.map((t) => {
                const body = (
                  <>
                    <span className="w-16 shrink-0">
                      <Badge tone={codeTone(t.code)} className="font-mono">
                        {t.code}
                      </Badge>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-slate-900">{t.name}</span>
                      <span className="mt-0.5 block text-xs leading-[18px] text-slate-500">{t.desc}</span>
                    </span>
                  </>
                );
                return (
                  <li key={t.code}>
                    {isTS ? (
                      <button
                        type="button"
                        onClick={() => setAsset(t.code as AssetCode)}
                        className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-slate-50"
                      >
                        {body}
                        <span className="inline-flex shrink-0 items-center gap-0.5 pt-0.5 text-xs font-medium text-brand-600">
                          Chi tiết <ChevronRight size={12} aria-hidden="true" />
                        </span>
                      </button>
                    ) : (
                      <div className="flex items-start gap-3 px-4 py-2.5">{body}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          </div>
        </Card>

        <ServicesCard />
      </div>
      <AssetPanel code={asset} onClose={() => setAsset(null)} />
    </>
  );
}

/** Tác vụ chở CT-01…06: việc nghiệp vụ hợp lệ agent đang làm khi bị tấn công (data/carrier_tasks.json). */
function CarrierTasks() {
  const q = useQuery({ queryKey: ["config"], queryFn: api.config });
  if (q.isLoading) return <Loading />;
  if (q.error) return (
    <div className="p-4">
      <ErrorBox error={q.error} />
    </div>
  );
  const carriers = q.data!.carriers;
  return (
    <>
      <div className="max-w-full overflow-x-auto border-t border-slate-100">
        <table className="table-base">
          <thead>
            <tr>
              <th>Mã</th>
              <th>Tác vụ</th>
              <th>Kênh tiêm</th>
              <th>
                <span className="inline-flex items-center gap-1">
                  Tool được phép
                  <InfoDot>
                    Tác vụ nhân viên giao cho agent; payload được cài vào dữ liệu mà tác vụ này đọc. Agent chỉ được gọi
                    tool trong danh sách của tác vụ, D3 chặn tool ngoài danh sách.
                  </InfoDot>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {carriers.map((c) => (
              <tr key={c.id}>
                <td className="whitespace-nowrap align-top">
                  <Mono className="font-medium text-slate-800">{c.id}</Mono>
                </td>
                <td className="min-w-[240px] max-w-[460px]">
                  <div className="font-medium text-slate-900">{c.name || c.id}</div>
                  {c.query && <div className="mt-0.5 text-xs leading-[18px] text-slate-500">{c.query}</div>}
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {c.channels?.map((k) => (
                      <Badge key={k} tone="payload" className="font-mono">
                        {k}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {c.allowed_tools?.map((t) => (
                      <Mono key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
                        {t}
                      </Mono>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
