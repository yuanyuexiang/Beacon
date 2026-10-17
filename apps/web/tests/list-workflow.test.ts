import { describe, expect, it, vi } from "vitest";
import { ListWorkflow, workflowSummary, workflowUnfinished, getAllBatchLeads, workflowBlocksActions, contactFailureLabel } from "../src/lib/list-workflow";

import { api } from "../src/lib/api";
vi.mock("../src/lib/api", () => ({ api: vi.fn() }));

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


describe("全量名单读取", () => {
  it("读取超过 500 家的全部页", async () => {
    const mocked = vi.mocked(api);
    mocked.mockReset();
    mocked.mockResolvedValueOnce(Array.from({ length: 500 }, (_, id) => ({ id }))).mockResolvedValueOnce([{ id: 500 }, { id: 501 }]);
    const rows = await getAllBatchLeads<{ id: number }>("完整 名单");
    expect(rows).toHaveLength(502);
    expect(mocked).toHaveBeenNthCalledWith(2, "/api/leads?batch_key=%E5%AE%8C%E6%95%B4%20%E5%90%8D%E5%8D%95&limit=500&offset=500");
  });
  it("获取失败不返回不完整名单", async () => {
    const mocked = vi.mocked(api);
    mocked.mockReset();
    mocked.mockResolvedValueOnce(Array(500).fill({ id: 1 })).mockRejectedValueOnce(new Error("network"));
    await expect(getAllBatchLeads("full")).rejects.toThrow("network");
  });
});


it("失败可以重试但不会阻止名单操作", () => {
  expect(workflowBlocksActions({ status: "failed" } as ListWorkflow)).toBe(false);
  expect(workflowUnfinished({ status: "failed" } as ListWorkflow)).toBe(true);
  expect(workflowBlocksActions({ status: "running" } as ListWorkflow)).toBe(true);
});


describe("官网读取统计", () => {
  it("部分读取和完全失败分开，不把无官网或旧记录当作成功", () => {
    expect(workflowSummary("contacts", { totals: { read_complete: 36, read_partial: 18, read_failed: 61, with_contacts: 77, no_website: 2, read_unknown: 3, pending: 1, running: 1 } })).toBe("读取完成 36，部分读取 18，读取失败 61，无官网 2，读取情况待确认 3；找到联系方式 77 家；待处理 2");
  });
});


it("区分网络、网站响应和页面内容问题", () => {
  expect(contactFailureLabel("ConnectError: SSL UNEXPECTED_EOF")).toContain("SSL");
  expect(contactFailureLabel("ReadTimeout: timed out")).toContain("超时");
  expect(contactFailureLabel("HTTP 502（unknown）")).toContain("5xx");
  expect(contactFailureLabel("HTTP 200（pdf）")).toContain("不是可读取的网页");
});
