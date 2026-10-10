import type { Money, PriceRange } from "./google-places.generated";

export function formatMoney(m: Money | null | undefined): string | null {
  if (!m) return null;
  const amount = Number(m.units ?? "0") + (m.nanos ?? 0) / 1e9;
  if (!Number.isFinite(amount)) return null;
  try { return new Intl.NumberFormat("zh-CN", { style: "currency", currency: m.currencyCode, maximumFractionDigits: 2 }).format(amount); }
  catch { return `${m.currencyCode} ${amount}`; }
}
export function formatPriceRange(range: PriceRange | null | undefined): string {
  const start = formatMoney(range?.startPrice), end = formatMoney(range?.endPrice);
  if (start && end) return `${start} – ${end}`;
  if (start) return `${start} 以上`;
  if (end) return `${end} 以下`;
  return "未知";
}
export const PRICE_LEVEL: Record<string, string> = {
  PRICE_LEVEL_FREE: "免费", PRICE_LEVEL_INEXPENSIVE: "较低", PRICE_LEVEL_MODERATE: "中等",
  PRICE_LEVEL_EXPENSIVE: "较高", PRICE_LEVEL_VERY_EXPENSIVE: "很高",
};
export const BUSINESS_STATUS: Record<string, string> = {
  OPERATIONAL: "营业中", CLOSED_TEMPORARILY: "暂时关闭", CLOSED_PERMANENTLY: "永久关闭", FUTURE_OPENING: "尚未开业",
};
