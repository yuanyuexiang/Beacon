import { describe, expect, it, vi } from "vitest";
import { afterCommit } from "../src/lib/after-commit";

describe("external effect initialization", () => {
  it("cancels abandoned initialization before it starts", async () => {
    const setup = vi.fn();
    const dispose = afterCommit(setup);
    dispose();
    await Promise.resolve();
    expect(setup).not.toHaveBeenCalled();
  });

  it("cleans up timers and subscriptions after initialization", async () => {
    const cleanup = vi.fn();
    const setup = vi.fn(() => cleanup);
    const dispose = afterCommit(setup);
    expect(setup).not.toHaveBeenCalled();
    await Promise.resolve();
    expect(setup).toHaveBeenCalledTimes(1);
    dispose();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it("only initializes the latest subscription during a Strict Mode restart", async () => {
    const abandoned = vi.fn();
    const current = vi.fn();
    afterCommit(abandoned)();
    const dispose = afterCommit(current);
    await Promise.resolve();
    expect(abandoned).not.toHaveBeenCalled();
    expect(current).toHaveBeenCalledTimes(1);
    dispose();
  });
});
