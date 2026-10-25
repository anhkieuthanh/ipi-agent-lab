import clsx from "clsx";
import { MousePointerClick } from "lucide-react";
import { useState } from "react";

import { MapLegend, SystemMap } from "@/components/SystemMap";
import { Badge, Card, CardHeader, PageHeader } from "@/components/ui";
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
  query_customer_db: { title: "query_customer_db", codes: ["TS2"], desc: "Đọc bản ghi khách hàng — nguồn dữ liệu kẻ tấn công muốn rò." },
  http_request: { title: "http_request", codes: ["TS3", "G1"], desc: "Gọi API. Gửi ra đích lạ = kênh rò dữ liệu." },
  send_email: { title: "send_email", codes: ["TS3", "G1", "G2"], desc: "Gửi email ra ngoài — hành động nguy hiểm nhất." },
  create_ticket: { title: "create_ticket", codes: ["TS3", "G2"], desc: "Ghi phiếu nội bộ — hành động ngoài phạm vi nếu không được yêu cầu." },
  kb: { title: "Kho tri thức", codes: ["K1"], desc: "Vector store Qdrant chứa tài liệu nội bộ; kẻ tấn công cài tài liệu độc vào đây." },
  db: { title: "customers.db", codes: ["TS2"], desc: "Dữ liệu khách hàng mô phỏng (Faker), có bản ghi mồi canary." },
  canary: { title: "Canary listener", codes: ["G1"], desc: "Bồn nhận HTTP. Canary xuất hiện ở đây = rò dữ liệu thành công." },
  mail: { title: "MailHog", codes: ["G1", "G2"], desc: "Hộp thư giả nhận mọi email agent gửi." },
  tickets: { title: "Kho phiếu", codes: ["G2"], desc: "Lưu phiếu agent tạo, để chấm hành động trái phép." },
  attacker: { title: "Kẻ tấn công", codes: ["K1", "K2a", "K2b", "T1–T8"], desc: "Không chạm vào agent trực tiếp — chỉ cài payload vào dữ liệu agent sẽ đọc." },
  trace: { title: "Trace store", codes: [], desc: "Ghi mọi bước của mọi run, kèm blocked_by: phòng thủ · model từ chối · harness." },
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

export function SystemPage() {
  const [selected, setSelected] = useState<string>("llm");
  const [tab, setTab] = useState(GLOSSARY[0].id);
  const info = INFO[selected];
  const group = GLOSSARY.find((g) => g.id === tab)!;

  return (
    <>
      <PageHeader title="Sơ đồ hệ thống" info="Bấm một thành phần hoặc điểm phòng thủ trên sơ đồ để xem giải thích." />

      <Card>
        <div className="px-4 pb-2 pt-4">
          <SystemMap selected={selected} onSelect={setSelected} />
        </div>
        <div className="border-t border-slate-100 px-5 py-3">
          <MapLegend />
        </div>
      </Card>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader title="Thành phần đang chọn" icon={<MousePointerClick size={16} />} />
          {info ? (
            <div className="space-y-3 p-5">
              <div className="text-[16px] font-semibold text-slate-900">{info.title}</div>
              {info.codes.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {info.codes.map((c) => (
                    <Badge key={c} tone={codeTone(c)}>
                      {c}
                    </Badge>
                  ))}
                </div>
              )}
              <p className="text-[13.5px] leading-relaxed text-slate-600">{info.desc}</p>
            </div>
          ) : (
            <p className="p-5 text-[13px] text-slate-500">Bấm một thành phần trên sơ đồ.</p>
          )}
        </Card>

        <Card className="xl:col-span-2">
          <div className="flex flex-wrap gap-1 border-b border-slate-100 px-3 pt-3">
            {GLOSSARY.map((g) => (
              <button
                key={g.id}
                onClick={() => setTab(g.id)}
                className={clsx(
                  "rounded-t-lg px-3 py-2 text-[13px] font-medium transition",
                  tab === g.id ? "border-b-2 border-brand-600 text-brand-700" : "text-slate-500 hover:text-slate-800",
                )}
              >
                {g.label}
                <span className="ml-1.5 font-mono text-[11px] text-slate-400">{g.prefix}</span>
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-2 p-4 md:grid-cols-2">
            {group.items.map((t) => (
              <div key={t.code} className="flex gap-3 rounded-lg border border-slate-100 p-3 hover:border-slate-200">
                <Badge tone={codeTone(t.code)} className="h-fit shrink-0 font-mono">
                  {t.code}
                </Badge>
                <div className="min-w-0">
                  <div className="text-[13.5px] font-semibold text-slate-800">{t.name}</div>
                  <div className="text-[12.5px] text-slate-500">{t.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
