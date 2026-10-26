// Icon dùng chung cho các khái niệm lặp lại giữa các trang — một khái niệm, một icon.

import {
  Cog,
  Crosshair,
  Eraser,
  Filter,
  FlaskConical,
  Gavel,
  Hand,
  Highlighter,
  type LucideIcon,
  PlayCircle,
  ShieldCheck,
  TestTube,
  ThumbsUp,
} from "lucide-react";

/** D1–D4 theo cách cơ chế làm việc: tô ranh giới, làm sạch, luật gọi tool, lọc dữ liệu ra. */
export const DEFENSE_ICON: Record<string, LucideIcon> = {
  D1: Highlighter,
  D2: Eraser,
  D3: Gavel,
  D4: Filter,
};

/** Giá trị của `blocked_by` trong trace. */
export const BLOCKED_ICON: Record<string, LucideIcon> = {
  defense: ShieldCheck,
  model_refusal: Hand,
  harness: Cog,
};

/** Loại lô (`kind`) và loại run (`run_kind`). */
export const KIND_ICON: Record<string, LucideIcon> = {
  experiment: FlaskConical,
  dryrun: TestTube,
  demo: PlayCircle,
  attack: Crosshair,
  benign: ThumbsUp,
};

export function KindIcon({ kind, size = 12 }: { kind: string; size?: number }) {
  const Icon = KIND_ICON[kind];
  return Icon ? <Icon size={size} /> : null;
}
