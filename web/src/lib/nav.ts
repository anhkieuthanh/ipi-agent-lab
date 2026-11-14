// Cấu trúc điều hướng — một nguồn cho thanh bên, đường dẫn trên thanh trên, bảng lệnh và phím tắt.

import {
  Crosshair,
  FlaskConical,
  Layers,
  LayoutDashboard,
  ListChecks,
  ListTree,
  type LucideIcon,
  Network,
  Settings2,
  Shield,
} from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Phím thứ hai của tổ hợp `g` rồi phím này. */
  key: string;
  /** Trang đọc phạm vi dữ liệu (?scope, ?batch) ở thanh trên. */
  scoped?: boolean;
};

/** `step`: số bước trong luồng thí nghiệm (chạy rồi phân tích); nhóm tham chiếu không có số. */
export type NavGroup = { label: string | null; step?: number; items: NavItem[] };

export const NAV: NavGroup[] = [
  { label: null, items: [{ to: "/", label: "Tổng quan", icon: LayoutDashboard, key: "o", scoped: true }] },
  {
    label: "Thí nghiệm",
    step: 1,
    items: [
      { to: "/lab", label: "Chạy thí nghiệm", icon: FlaskConical, key: "l" },
      { to: "/batches", label: "Lô thực nghiệm", icon: Layers, key: "b" },
    ],
  },
  {
    label: "Phân tích",
    step: 2,
    items: [
      { to: "/attack", label: "Tấn công", icon: Crosshair, key: "a", scoped: true },
      { to: "/defense", label: "Phòng thủ", icon: Shield, key: "d", scoped: true },
      { to: "/runs", label: "Lượt chạy", icon: ListTree, key: "r", scoped: true },
    ],
  },
  {
    label: "Hệ thống",
    items: [
      { to: "/system", label: "Sơ đồ hệ thống", icon: Network, key: "s" },
      { to: "/config", label: "Cấu hình", icon: Settings2, key: "c" },
      { to: "/process", label: "Quy trình", icon: ListChecks, key: "p" },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);

/** Mục điều hướng và nhóm của một đường dẫn (vd `/runs/abc` → Lượt chạy, Phân tích). */
export function locate(pathname: string): { item: NavItem; group: string | null } {
  const root = "/" + (pathname.split("/")[1] ?? "");
  for (const g of NAV) {
    const item = g.items.find((it) => it.to === root);
    if (item) return { item, group: g.label };
  }
  return { item: NAV_ITEMS[0], group: null };
}
