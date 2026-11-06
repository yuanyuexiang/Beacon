package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class ChannelPolicyTest {
  @Test fun requiresAnIdentityHeaderNotAnArbitraryMessage() {
    assertTrue(ChannelPolicy.identity("profile_username", "@test_shop", "test_shop"))
    assertFalse(ChannelPolicy.identity("message_text", "test_shop", "test_shop"))
    assertFalse(ChannelPolicy.identity("profile_name", "Restaurant", "test_shop"))
    assertFalse(ChannelPolicy.identity("toolbar_title", "123456", "123456"))
    assertFalse(ChannelPolicy.identity("profile_username", "@test_shop", "other_shop"))
  }
  @Test fun facebookSemanticHeadersAndComposersWithoutResourceIds() {
    assertTrue(ChannelPolicy.facebookTitle("Aberdeen Airport", "aberdeenairport", 126, 273, 2400, true))
    assertFalse(ChannelPolicy.facebookTitle("Aberdeen Airport", "aberdeenairport", 1200, 1300, 2400, true))
    assertFalse(ChannelPolicy.facebookTitle("Different Airport", "aberdeenairport", 126, 273, 2400, true))
    assertTrue(ChannelPolicy.facebookComposer("发消息", "输入消息", true))
    assertTrue(ChannelPolicy.facebookComposer("输入消息...", "输入消息", true))
    assertTrue(ChannelPolicy.facebookComposer("输入消息…", "输入消息", true))
    assertFalse(ChannelPolicy.facebookComposer("输入消息...", "输入消息", false))
    assertFalse(ChannelPolicy.facebookComposer("发表评论", "输入消息", true))
  }
  @Test fun facebookSenderNameCaptionsRequireExactOutgoingText() {
    assertTrue(ChannelPolicy.facebookOutgoingCaption("Sender, 你好", "你好", 858, 540))
    assertFalse(ChannelPolicy.facebookOutgoingCaption("Sender, 你好呀", "你好", 858, 540))
    assertFalse(ChannelPolicy.facebookOutgoingCaption("Sender, 你好", "你好", 138, 540))
    assertFalse(ChannelPolicy.facebookOutgoingCaption("你好", "你好", 858, 540))
  }
  @Test fun publicCommentsAndSearchInputsAreNotPrivateComposers() {
    assertTrue(ChannelPolicy.composer("message_input", true))
    assertFalse(ChannelPolicy.composer("comment_input", true))
    assertFalse(ChannelPolicy.composer("search_edit", true))
    assertFalse(ChannelPolicy.composer("message_input", false))
  }
  @Test fun invitationAndPaidActionsNeverEnterTheAutomaticSendPath() {
    for (action in listOf("connection_request", "inmail", "contact_discovery")) assertTrue(ChannelPolicy.manualAction(action))
    assertFalse(ChannelPolicy.manualAction("direct_message"))
    assertEquals("request_submitted", ChannelPolicy.sentOutcome("message_request"))
    assertEquals("sent", ChannelPolicy.sentOutcome("direct_message"))
  }
}
