import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/lib/api";

afterEach(() => vi.unstubAllGlobals());
describe("API error responses", () => {
  it.each(["", "null", '"null"', '{"detail":null}', '""'])("explains an empty response: %s", async (body) => {
    vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(body,{status:502})));
    await expect(api("/api/mobile/app/uploads")).rejects.toThrow("HTTP 502");
  });
  it("preserves useful error text without JSON quotes", async () => {
    vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response("Bad Gateway",{status:502})));
    await expect(api("/api/test")).rejects.toThrow(/^Bad Gateway$/);
  });
});
