package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class AgentPolicyTest {
  @Test fun whatsappPlaceholderIsNotAnotherDraft() {
    assertTrue(AgentPolicy.emptyComposer("发消息", null, false, "com.whatsapp", "com.whatsapp:id/entry"))
    assertTrue(AgentPolicy.emptyComposer("Message", null, false, "com.whatsapp.w4b", "com.whatsapp.w4b:id/entry"))
    assertFalse(AgentPolicy.emptyComposer("客户草稿", null, false, "com.whatsapp", "com.whatsapp:id/entry"))
    assertFalse(AgentPolicy.emptyComposer("发消息", null, false, "other.app", "other.app:id/entry"))
    assertFalse(AgentPolicy.emptyComposer("Message", null, false, "com.whatsapp", "com.whatsapp:id/search"))
    assertTrue(AgentPolicy.emptyComposer("提示", "提示", false, "other.app", "field"))
  }
  @Test fun sendCannotBeReplayed() {
    for (a in listOf("tap", "input", "send", "scroll", "back", "alternate")) assertFalse(AgentPolicy.allowed(a, true))
    assertTrue(AgentPolicy.allowed("wait", true))
    assertTrue(AgentPolicy.allowed("send", false))
  }
  @Test fun noClickIsNotSuccessAndUnknownIsPreserved() {
    assertEquals("unknown", AgentPolicy.terminal("sent", false, true))
    assertEquals("unknown", AgentPolicy.terminal("sent", true, false))
    assertEquals("sent", AgentPolicy.terminal("sent", true, true))
    assertEquals("unknown", AgentPolicy.terminal("failed", true, false))
    assertEquals("unavailable", AgentPolicy.terminal("unavailable", false, false))
  }
  @Test fun publicEntryDoesNotAuthorizePostOrExistingDraftSend() {
    assertFalse(AgentPolicy.blocked("评论", true))
    assertTrue(AgentPolicy.blocked("发布", true))
    assertTrue(AgentPolicy.draftSendControl("发送消息", true))
    assertFalse(AgentPolicy.draftSendControl("发送消息", false))
  }
  @Test fun destructiveControlsAreNotNavigation() {
    assertTrue(AgentPolicy.blocked("Send"))
    assertTrue(AgentPolicy.blocked("删除"))
    assertFalse(AgentPolicy.blocked("Message"))
  }
}
