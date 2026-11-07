package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class NavigationPolicyTest {
  @Test fun titleMustMatchTheVisibleHeader() {
    assertTrue(NavigationPolicy.title("Aberdeen Ladies Golf Club", "ABERDEEN LADIES GOLF CLUB", 80, 190, 2400))
    assertFalse(NavigationPolicy.title("Other Club", "Aberdeen Ladies Golf Club", 80, 190, 2400))
    assertFalse(NavigationPolicy.title("Aberdeen Ladies Golf Club", "Aberdeen Ladies Golf Club", 900, 1000, 2400))
  }
  @Test fun genericPrivateInputNeverMatchesSearchOrComment() {
    assertTrue(NavigationPolicy.privateComposer("Message…", "chat_composer", true))
    assertFalse(NavigationPolicy.privateComposer("Message…", "comment_input", true))
    assertFalse(NavigationPolicy.privateComposer("Search", "", true))
    assertFalse(NavigationPolicy.privateComposer("Message…", "", false))
  }
  @Test fun navigationNeverOffersSendOrPublicActions() {
    assertEquals("open_messages", NavigationPolicy.navigationLabel("发消息"))
    assertEquals("open_more", NavigationPolicy.navigationLabel("更多"))
    for (label in listOf("Send", "Comment", "Follow", "Call", "InMail", "发送", "评论")) {
      assertTrue(NavigationPolicy.forbidden(label))
      assertNull(NavigationPolicy.navigationLabel(label))
    }
    assertFalse(NavigationPolicy.mayContinue("send"))
    assertFalse(NavigationPolicy.mayContinue("type"))
    assertTrue(NavigationPolicy.mayContinue("scroll"))
  }
}
