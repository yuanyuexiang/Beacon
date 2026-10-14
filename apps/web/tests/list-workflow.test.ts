import { describe, expect, it } from "vitest";
import { ListWorkflow, workflowSummary, workflowUnfinished } from "../src/lib/list-workflow";

describe("名单进度展示", () => {
  it("失败与崩溃中的任务保持未完成状态", () => {
    for (const status of ["pending", "running", "failed"] as const) expect(workflowUnfinished({ status } as ListWorkflow)).toBe(true);
    for (const status of ["completed", "cancelled"] as const) expect(workflowUnfinished({ status } as ListWorkflow)).toBe(false);
    expect(workflowUnfinished(null)).toBe(false);
  });
  it("追加结果区分已有成员与可选新成员", () => {
    expect(workflowSummary("fsa", { fetched: 80, already_in_list: 50, pool: 30, selected: 20, created: 15, linked: 5 })).toBe("名录 80 家，已有 50 家，剩余可选 30 家，本次选入 20 家（新增 15，关联已有 5）");
  });
  it("联系方式部分失败仍展示失败与剩余项", () => {
    expect(workflowSummary("contacts", { totals: { succeeded: 18, failed: 2, pending: 4, running: 1 } })).toBe("成功 18，失败 2，待处理 5");
    expect(workflowSummary("contacts")).toBeUndefined();
  });
});
