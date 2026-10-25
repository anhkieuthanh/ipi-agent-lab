// Định dạng số kiểu Việt Nam: dấu phẩy thập phân, dấu chấm ngăn nghìn.

const nf = (digits: number) =>
  new Intl.NumberFormat("vi-VN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export function pct(p: number | null | undefined, digits = 1): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "—";
  return `${nf(digits).format(p * 100)}%`;
}

export function int(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("vi-VN").format(n);
}

export function usd(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined) return "—";
  return `${nf(digits).format(n)} USD`;
}

export function kilo(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n < 1000) return int(n);
  if (n < 1_000_000) return `${nf(1).format(n / 1000)}k`;
  return `${nf(2).format(n / 1_000_000)}M`;
}

export function seconds(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${int(ms)} ms` : `${nf(1).format(ms / 1000)} s`;
}

/** "2026-10-25 12:44:16.066" hoặc "20261025T124415Z" → "25/10 12:44". */
export function when(raw: string | null | undefined): string {
  if (!raw) return "—";
  let d: Date;
  const compact = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(raw);
  if (compact) {
    const [, y, mo, da, h, mi, s] = compact;
    d = new Date(Date.UTC(+y, +mo - 1, +da, +h, +mi, +s));
  } else {
    d = new Date(raw.includes("T") || raw.endsWith("Z") ? raw : `${raw.replace(" ", "T")}Z`);
  }
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function ci(lo: number | null | undefined, hi: number | null | undefined): string {
  if (lo === null || lo === undefined || hi === null || hi === undefined) return "";
  return `${pct(lo, 0)}–${pct(hi, 0)}`;
}

export const GOAL_LABEL: Record<string, string> = {
  G1: "Rò rỉ dữ liệu",
  G2: "Hành động trái phép",
  G3: "Cài thông tin sai",
};

export const CHANNEL_LABEL: Record<string, string> = {
  K1: "Kho tri thức (RAG)",
  K2a: "Mô tả tool MCP",
  K2b: "Kết quả tool MCP",
};

export const TECHNIQUE_LABEL: Record<string, string> = {
  T1: "Mệnh lệnh / giả uy quyền",
  T2: "Thu hồi chỉ thị",
  T3: "Điều kiện tiên quyết giả",
  T4: "Ẩn trong định dạng",
  T5: "Ngụy trang sự thật",
  T6: "Chia mảnh",
  T7: "Kích hoạt trễ",
  T8: "Che giấu tiếng Việt",
};

export const DEFENSE_LABEL: Record<string, string> = {
  D1: "Spotlighting",
  D2: "Input Sanitizer",
  D3: "Tool-call Policy",
  D4: "Egress Filter",
};

export const KIND_LABEL: Record<string, string> = {
  experiment: "Thực nghiệm",
  dryrun: "Chạy thử",
  demo: "Demo",
};

export const OUTCOME_LABEL: Record<string, string> = {
  success: "Tấn công thành công",
  failed: "Tấn công không đạt",
  blocked: "Bị chặn",
  pass: "Đạt",
  fail: "Không đạt",
};

export const BLOCKED_LABEL: Record<string, string> = {
  defense: "Phòng thủ",
  model_refusal: "Model từ chối",
  harness: "Harness",
};

export function presetLabel(p: string): string {
  if (p === "off") return "Tắt phòng thủ";
  if (p === "all") return "Bật D1–D4";
  const m = /^d(\d)_only$/.exec(p);
  if (m) return `Chỉ D${m[1]}`;
  if (p === "d3_no_confirm") return "D3 không xác nhận";
  return p;
}
