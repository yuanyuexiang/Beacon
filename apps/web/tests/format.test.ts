import { describe, expect, it } from "vitest";
import { approvalText, formatRatio, label } from "@/lib/format";

describe("format", () => {
  it("零分母写不适用", () => {
    expect(formatRatio({ numerator: 0, denominator: 0, value: null, note: "不适用" })).toContain("不适用");
    expect(formatRatio({ numerator: 1, denominator: 4, value: 0.25, note: null })).toBe("1/4 = 25.0%");
  });
  it("状态文案有回退", () => {
    expect(label("needs_review")).toBe("需人工");
    expect(label("something_new")).toBe("something_new");
    expect(label(null)).toBe("-");
  });
  it("审批无效带原因", () => {
    expect(approvalText(false, "已有更新版本的内容")).toContain("已有更新版本");
    expect(approvalText(true, null)).toBe("审批有效");
  });
});
