import { afterEach, describe, expect, it, vi } from "vitest";
import { uploadMobileApp } from "../src/lib/mobile-app-upload";

const reply=(body:unknown,status=200) => new Response(JSON.stringify(body),{status});
afterEach(() => vi.unstubAllGlobals());
describe("APK segmented upload", () => {
  it("retries a lost chunk response at the same offset and finishes only after all bytes", async () => {
    const calls: Array<[string,RequestInit]> = [];
    let failed=false;
    vi.stubGlobal("fetch",vi.fn(async (url:string, init:RequestInit) => {
      calls.push([url,init]);
      if(url.endsWith("/start")) return reply({upload_id:"test",chunk_bytes:3});
      if(url.endsWith("/finish")) return reply({id:"pending"});
      if(url.endsWith("offset=0") && !failed) {failed=true;throw new TypeError("network error");}
      return reply({received:url.endsWith("offset=0") ? 3 : 5});
    }));
    const progress=vi.fn();
    await uploadMobileApp(new Blob(["12345"]),progress);
    expect(calls.map(c=>c[0])).toEqual([
      "/api/mobile/app/uploads/start", "/api/mobile/app/uploads/test/chunks?offset=0",
      "/api/mobile/app/uploads/test/chunks?offset=0", "/api/mobile/app/uploads/test/chunks?offset=3",
      "/api/mobile/app/uploads/test/finish",
    ]);
    expect(await (calls[3][1].body as Blob).text()).toBe("45");
    expect(progress.mock.calls).toEqual([[60],[100]]);
  });
  it("cancels staging on a permission failure without completing or retrying", async () => {
    const fetcher=vi.fn().mockResolvedValueOnce(reply({upload_id:"test",chunk_bytes:3}))
      .mockResolvedValueOnce(reply({detail:"权限已撤销"},403)).mockResolvedValueOnce(new Response(null,{status:204}));
    vi.stubGlobal("fetch",fetcher);
    await expect(uploadMobileApp(new Blob(["12345"]),vi.fn())).rejects.toThrow("权限已撤销");
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls[2]).toEqual(["/api/mobile/app/uploads/test",expect.objectContaining({method:"DELETE"})]);
  });
});
