import { describe, expect, it } from "vitest";
import { ChannelAccount, Conversation, replyCandidates, replyIssue } from "../src/lib/outreach";
import { channelLabel, label } from "../src/lib/format";
const account: ChannelAccount = { id: "a", platform: "facebook", label: "Our page", auth_mode: "facebook_login", sender_id: "123", connected: true, sending_enabled: true, queue_enabled: false, daily_limit: 20, capabilities: ["text_reply"] };
const conversation: Conversation = { id: "c", account_id: "a", recipient_id: "999", lead_id: "l", eligibility_id: "e", last_inbound_at: "2026-10-12T00:00:00Z", window_expires_at: "2026-10-13T00:00:00Z", window_open: true };
const task = { channel: "facebook", lead_id: "l", eligibility_id: "e", status: "pending" };
describe("social reply task selection", () => {
  it("requires the linked identity and current channel", () => {
    expect(replyCandidates([task], conversation, account)).toEqual([task]);
    expect(replyCandidates([{ ...task, channel: "instagram" }], conversation, account)).toEqual([]);
    expect(replyCandidates([{ ...task, eligibility_id: "different" }], conversation, account)).toEqual([]);
  });
  it("hides expired, disconnected and paused tasks", () => {
    expect(replyCandidates([task], { ...conversation, window_open: false }, account)).toEqual([]);
    expect(replyCandidates([task], conversation, { ...account, connected: false })).toEqual([]);
    expect(replyCandidates([{ ...task, status: "paused" }], conversation, account)).toEqual([]);
  });
  it("names LinkedIn and automatic social results", () => {
    expect(channelLabel("linkedin")).toBe("LinkedIn");
    expect(label("sent_social")).toBe("已通过社媒发送");
  });
});

describe("reply readiness diagnostics", () => {
  it("explains a configured account without any inbound conversation", () => {
    expect(replyIssue(task, [], [account])).toContain("尚未关联");
    expect(replyIssue(task, [{ ...conversation, eligibility_id: "other" }], [account])).toContain("尚未关联");
  });
  it("distinguishes expired windows and sending disabled", () => {
    expect(replyIssue(task, [{ ...conversation, window_open: false }], [account])).toContain("过期");
    expect(replyIssue(task, [conversation], [{ ...account, sending_enabled: false }])).toContain("暂停发送");
    expect(replyCandidates([task], conversation, { ...account, sending_enabled: false })).toEqual([]);
    expect(replyIssue(task, [conversation], [account])).toBeUndefined();
  });
});
