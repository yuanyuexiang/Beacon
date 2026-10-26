import { describe, expect, it } from "vitest";
import { nextSendIssue } from "../src/lib/sendflow";

describe("send issue guidance", () => {
  it("shows only the most important action", () => {
    expect(nextSendIssue(["文案缺失", "Gmail 发送已暂停"] )?.action).toBe("settings");
    expect(nextSendIssue(["Gmail 发送已暂停", "客户已拒收"])?.action).toBe("none");
  });
  it("routes missing recipient and evidence to different controls", () => {
    expect(nextSendIssue(["尚未选择联系方式"])?.action).toBe("contact");
    expect(nextSendIssue(["尚缺联系依据"])?.action).toBe("basis");
    expect(nextSendIssue(["缺少该联系方式属于目标门店的原文证据"])?.action).toBe("ownership");
    expect(nextSendIssue([])).toBeUndefined();
  });
});
