import { describe, expect, it } from "vitest";
import { menuJourney } from "../src/lib/menu-journey";

describe("菜单资料进度", () => {
  const assets = [{ id: "menu", fetch_status: "fetched" }];
  it("没有菜单仍可留在资料阶段，失败文件不算获取成功", () => {
    expect(menuJourney([], {}).current).toBe(0);
    expect(menuJourney([], {}).action).toBe("无菜单，准备询问");
    expect(menuJourney([], {}).message).toContain("收到菜单后再分析");
    expect(menuJourney([{ id: "menu", fetch_status: "failed" }], {}).current).toBe(0);
  });
  it("按获取、分析和事实核对推进，不要求样稿或发送审批", () => {
    expect(menuJourney(assets, {}).current).toBe(1);
    expect(menuJourney(assets, { menu: [{ version: 1, status: "needs_review", review_state: null }] }).current).toBe(2);
    expect(menuJourney(assets, { menu: [{ version: 1, status: "succeeded", review_state: "reviewed" }] }).current).toBe(3);
  });
  it("新版本失败或未核对时，不能沿用旧版本的完成状态", () => {
    const old = { version: 1, status: "succeeded", review_state: "reviewed" };
    expect(menuJourney(assets, { menu: [old, { version: 2, status: "failed", review_state: null }] }).current).toBe(1);
    expect(menuJourney(assets, { menu: [{ version: 2, status: "needs_review", review_state: null }, old] }).current).toBe(2);
  });
  it("另一份失败或未处理文件不阻塞已有可用菜单", () => {
    expect(menuJourney([...assets, { id: "other", fetch_status: "fetched" }], { menu: [{ version: 1, status: "succeeded", review_state: "reviewed" }] }).current).toBe(3);
  });
});
