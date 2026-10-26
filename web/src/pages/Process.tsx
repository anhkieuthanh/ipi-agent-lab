import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Flag, XCircle } from "lucide-react";

import { Badge, Callout, Card, CardHeader, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api, type Gate } from "@/lib/api";

export function allGatesPass(gates: Gate[] | undefined) {
  return !!gates?.length && gates.every((g) => g.status === "pass");
}

function GateRow({ gate }: { gate: Gate }) {
  const icon = {
    pass: <CheckCircle2 size={18} className="text-defense-500" />,
    fail: <XCircle size={18} className="text-attack-500" />,
    pending: <CircleDashed size={18} className="text-slate-400" />,
  }[gate.status];
  const tone = { pass: "defense", fail: "attack", pending: "neutral" } as const;
  const text = { pass: "Đạt", fail: "Chưa đạt", pending: "Chờ" };
  return (
    <div className="flex items-center gap-3 px-5 py-3.5">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-medium text-slate-800">{gate.label}</div>
        <div className="truncate text-[12.5px] text-slate-500">{gate.detail}</div>
      </div>
      <Badge tone={tone[gate.status]}>{text[gate.status]}</Badge>
    </div>
  );
}

export function ProcessPage() {
  const q = useQuery({ queryKey: ["gates"], queryFn: api.gates });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const gates = q.data!;

  return (
    <>
      <PageHeader
        title="Quy trình"
        info="Cổng phải qua trước khi chạy full matrix (quy tắc cứng #5). Tính trên mọi lô thực nghiệm, không theo phạm vi đang xem."
      />
      {allGatesPass(gates) && (
        <div className="mb-6">
          <Callout tone="brand">Cả hai cổng đã đạt — mục này đã ẩn khỏi menu, trang giữ lại làm bằng chứng.</Callout>
        </div>
      )}
      <Card className="max-w-[720px]">
        <CardHeader title="Cổng nghiệm thu" icon={<Flag size={16} />} />
        <div className="divide-y divide-slate-100">
          {gates.map((g) => (
            <GateRow key={g.id} gate={g} />
          ))}
        </div>
      </Card>
    </>
  );
}
