export type ContactAssessment = { recommendation: string; affiliation?: string; owner?: string; purpose?: string; reason?: string; citations?: { quote: string; url?: string }[] };
export const CONTACT_RANK_LABELS: Record<string, string> = { recommended: "优先推荐", backup: "备选", not_recommended: "不推荐", review: "待确认" };
export const CONTACT_PURPOSE: Record<string, string> = { business: "商务／采购／经营", general: "门店通用联系", booking: "预订专用", media: "媒体", recruitment: "招聘", complaints: "投诉", support: "技术支持", other: "其他用途", unknown: "用途不明" };
export const contactRank = (assessment?: ContactAssessment | null) => ({ recommended: 0, backup: 1, review: 2, not_recommended: 3 }[assessment?.recommendation || "review"] ?? 2);
