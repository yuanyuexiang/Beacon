import { expect, it } from "vitest";
import { leadNextAction } from "../src/lib/lead-list";

it("沟通状态优先于资料缺项，抑制和回复不能退回准备", () => {
  expect(leadNextAction({ contact_count: 0, communication_progress: { status: "suppressed" } })).toEqual({ text: "停止触达", target: "tasks" });
  expect(leadNextAction({ contact_count: 0, communication_progress: { status: "replied" } }).text).toBe("处理客户回复");
});
it("准备中按已选择的数据提示操作，不宣称可以发送", () => {
  expect(leadNextAction({ contact_count: 0 }).target).toBe("contacts");
  expect(leadNextAction({ contact_count: 1, communication_progress: { status: "preparing", contact_selected: false } }).text).toBe("选择联系方式");
  expect(leadNextAction({ contact_count: 1, communication_progress: { status: "preparing", contact_selected: true, content_selected: false } }).text).toBe("准备并审批文案");
  expect(leadNextAction({ contact_count: 1, communication_progress: { status: "preparing", contact_selected: true, content_selected: true } }).text).toBe("检查文案与渠道准入");
});
it("没有菜单也能准备询问，已有分析指向核对", () => {
  expect(leadNextAction({ contact_count: 1, list_summary: { menu_status: "missing", channels: ["email"] } }).target).toBe("prepare");
  expect(leadNextAction({ contact_count: 1, list_summary: { menu_status: "needs_review", channels: [] } }).target).toBe("detail");
});
