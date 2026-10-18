export type MenuAnalysisState = { version: number; status: string; review_state: string | null; issues?: { confirmed: boolean | null; deleted?: boolean }[] | null };
export type MenuAssetState = { id: string; fetch_status: string };

// 只看当前文件的最新分析；旧审批或可选样稿不能推进菜单资料阶段。
export function menuJourney(assets: MenuAssetState[], analyses: Record<string, MenuAnalysisState[]>) {
  const fetched = assets.filter((a) => a.fetch_status === "fetched");
  const latest = fetched.map((a) => ({ asset: a, analysis: [...(analyses[a.id] || [])].sort((x, y) => y.version - x.version)[0] }));
  const readable = latest.filter((x) => x.analysis && ["succeeded", "needs_review"].includes(x.analysis.status));
  const reviewed = readable.filter((x) => x.analysis.review_state === "reviewed");
  if (reviewed.length) return { current: 3, action: "准备触达", message: "菜单事实已核对，可以选择渠道并准备文案；样稿按需制作。", assetId: reviewed[0].asset.id };
  if (readable.length) return { current: 2, action: "核对菜单事实", message: "分析已完成。对照原文件核对菜名、价格，只确认有依据的问题。", assetId: readable[0].asset.id };
  if (fetched.length) return { current: 1, action: "开始分析", message: "已获取菜单。自动提取可读文字，图片和扫描菜单交给 AI。", assetId: fetched[0].id };
  return { current: 0, action: "无菜单，准备询问", message: "尚未获取可用菜单，可以直接询问菜单或负责人；收到菜单后再分析。查找和上传菜单仍可继续。", assetId: undefined };
}


export const issueLabel = (code: string) => ({ text_overlap: "文本重叠", missing_spaces: "字间距异常", low_resolution: "图片清晰度不足", price_format_mixed_decimals: "价格小数格式不一致", price_format_mixed_symbol: "货币符号格式不一致", small_text: "字号偏小", typo: "疑似拼写问题", other: "其他问题", image_only_menu: "图片菜单需核对", pdf_no_text: "扫描菜单需 AI 识别" } as Record<string, string>)[code] || "其他待核对问题";
