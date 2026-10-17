import { describe, expect, it } from "vitest";
import { safeReturnTo, taskLink } from "../src/lib/communication";

describe("名单与沟通工作台的上下文", () => {
  it("保留中文名单、筛选和页码，定位到具体任务", () => {
    const back = "/leads?batch=测试&q=coffee&type=1&page=2&pageSize=20";
    const link = new URL(taskLink({ lead: "customer", task: "task", batch: "测试", preparation: "group", returnTo: back }), "https://beacon.local");
    expect(link.searchParams.get("task")).toBe("task");
    expect(link.searchParams.get("preparation")).toBe("group");
    expect(new URL(link.searchParams.get("returnTo")!, "https://beacon.local").searchParams.get("batch")).toBe("测试");
    expect(link.searchParams.get("returnTo")).toContain("page=2");
  });
  it("返回链接只允许名单或线索详情", () => {
    for (const path of ["https://evil.test", "//evil.test/leads", "/\\evil.test/leads", "javascript:alert(1)", "/settings", "/leads-other"]) expect(safeReturnTo(path)).toBe("/leads");
    const detail = "/leads/88361c8b-71f6-46c1-9313-2440e0cf3d09#menu-files";
    expect(safeReturnTo(detail)).toBe(detail);
  });
});
