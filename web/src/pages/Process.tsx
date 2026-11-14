import { useQuery } from "@tanstack/react-query";

import { Callout, Card, CardHeader, ErrorBox, Loading, PageHeader, Status } from "@/components/ui";
import { api, type Gate } from "@/lib/api";

export function allGatesPass(gates: Gate[] | undefined) {
  return !!gates?.length && gates.every((g) => g.status === "pass");
}

const TONE = { pass: "defense", fail: "attack", pending: "neutral" } as const;
const TEXT = { pass: "Đạt", fail: "Chưa đạt", pending: "Chờ" };

function GateRow({ gate, index }: { gate: Gate; index: number }) {
  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <span className="num w-5 shrink-0 pt-0.5 font-mono text-xs text-muted" aria-hidden="true">
        {String(index + 1).padStart(2, "0")}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-900">{gate.label}</div>
        <div className="mt-0.5 break-words text-xs leading-[18px] text-slate-500">{gate.detail}</div>
      </div>
      <div className="shrink-0">
        <Status tone={TONE[gate.status]}>{TEXT[gate.status]}</Status>
      </div>
    </li>
  );
}

export function ProcessPage() {
  const q = useQuery({ queryKey: ["gates"], queryFn: api.gates });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const gates = q.data!;
  const passed = gates.filter((g) => g.status === "pass").length;

  return (
    <>
      <PageHeader
        title="Quy trình"
        description="Cổng phải qua trước khi chạy full matrix (quy tắc cứng #5). Tính trên mọi lô thực nghiệm, không theo phạm vi đang xem."
      />
      <div className="max-w-[720px] space-y-4">
        {allGatesPass(gates) && (
          <Callout tone="brand">Cả hai cổng đã đạt, mục này đã ẩn khỏi menu, trang giữ lại làm bằng chứng.</Callout>
        )}
        <Card>
          <CardHeader
            title="Cổng nghiệm thu"
            action={
              <span className="num text-xs text-slate-500">
                {passed}/{gates.length} đạt
              </span>
            }
          />
          <ol className="divide-y divide-slate-100 border-t border-slate-100">
            {gates.map((g, i) => (
              <GateRow key={g.id} gate={g} index={i} />
            ))}
          </ol>
        </Card>
      </div>
    </>
  );
}
