// Bộ chọn kịch bản tự do cho trang Thí nghiệm: kênh → kỹ thuật → mục tiêu → payload → tác vụ chở.
// Chỉ đưa ra các bộ mà backend ghép được (`/api/demo/catalog`, cùng tập cặp ma trận lấy mẫu), nên
// mọi lựa chọn đều chạy được; đổi một tầng trên thì các tầng dưới tự về lựa chọn hợp lệ đầu tiên.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { ErrorBox, Loading, Select } from "@/components/ui";
import { api, type ScenarioCatalog } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, TECHNIQUE_LABEL } from "@/lib/format";

export const CUSTOM_PREFIX = "custom:";

type Row = ScenarioCatalog["rows"][number];
type Pick = [string, string, string, string, string];

const uniq = (xs: string[]) => [...new Set(xs)];

/** Đưa từng tầng về giá trị hợp lệ (giữ lựa chọn cũ nếu còn hợp lệ). */
function resolve(rows: Row[], want: Partial<Pick>): Pick {
  const out: string[] = [];
  let pool = rows;
  for (let i = 0; i < 5; i++) {
    const opts = uniq(pool.map((r) => r[i]));
    const v = want[i] && opts.includes(want[i]!) ? want[i]! : opts[0];
    out.push(v);
    pool = pool.filter((r) => r[i] === v);
  }
  return out as Pick;
}

export function ScenarioPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (key: string) => void;
}) {
  const cat = useQuery({ queryKey: ["scenarioCatalog"], queryFn: api.scenarioCatalog, staleTime: Infinity });
  const rows = useMemo(() => cat.data?.rows ?? [], [cat.data]);
  const initial: Partial<Pick> = value.startsWith(CUSTOM_PREFIX)
    ? (value.slice(CUSTOM_PREFIX.length).split(":") as Pick)
    : [];
  const [pick, setPick] = useState<Pick | null>(null);

  useEffect(() => {
    if (rows.length && !pick) setPick(resolve(rows, initial));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, pick]);
  useEffect(() => {
    if (pick) onChange(CUSTOM_PREFIX + pick.join(":"));
  }, [pick, onChange]);

  if (cat.isLoading) return <Loading />;
  if (cat.error) return <ErrorBox error={cat.error} />;
  if (!pick || !cat.data) return null;

  const set = (i: number, v: string) => {
    const want = [...pick] as Partial<Pick>;
    want[i] = v;
    setPick(resolve(rows, want));
  };
  const optionsAt = (i: number) => {
    const pool = rows.filter((r) => r.slice(0, i).every((x, j) => x === pick[j]));
    return uniq(pool.map((r) => r[i]));
  };
  const count = (i: number, v: string) =>
    rows.filter((r) => r.slice(0, i).every((x, j) => x === pick[j]) && r[i] === v).length;

  const { payloads, carriers } = cat.data;
  const label = (code: string, map: Record<string, string>) => (map[code] ? `${code} · ${map[code]}` : code);
  const payloadLabel = (id: string) => {
    const p = payloads[id];
    return [id, p?.lang?.toUpperCase(), p?.variant].filter(Boolean).join(" · ");
  };
  const carrierLabel = (id: string) => {
    const q = carriers[id] ?? "";
    return `${id} · ${q.length > 70 ? `${q.slice(0, 70)}…` : q}`;
  };

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Select
        label="Kênh"
        value={pick[0]}
        onChange={(v) => set(0, v)}
        options={optionsAt(0).map((v) => ({ value: v, label: `${label(v, CHANNEL_LABEL)} (${count(0, v)})` }))}
      />
      <Select
        label="Kỹ thuật"
        value={pick[1]}
        onChange={(v) => set(1, v)}
        options={optionsAt(1).map((v) => ({ value: v, label: `${label(v, TECHNIQUE_LABEL)} (${count(1, v)})` }))}
      />
      <Select
        label="Mục tiêu"
        value={pick[2]}
        onChange={(v) => set(2, v)}
        options={optionsAt(2).map((v) => ({ value: v, label: `${label(v, GOAL_LABEL)} (${count(2, v)})` }))}
      />
      <Select
        label="Payload"
        value={pick[3]}
        onChange={(v) => set(3, v)}
        options={optionsAt(3).map((v) => ({ value: v, label: payloadLabel(v) }))}
      />
      <Select
        label="Tác vụ chở"
        value={pick[4]}
        onChange={(v) => set(4, v)}
        options={optionsAt(4).map((v) => ({ value: v, label: carrierLabel(v) }))}
      />
    </div>
  );
}
