package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class ReplyCapturePolicyTest {
  @Test fun wideFacebookReplyStillHasIncomingDirection() {
    assertTrue(ReplyCapturePolicy.incomingAligned(159, 177))
    assertFalse(ReplyCapturePolicy.incomingAligned(320, 68))
    assertFalse(ReplyCapturePolicy.incomingAligned(159, 159))
    assertEquals("Hi, thanks", ReplyCapturePolicy.facebook(", Hi, thanks", "Old Masons Arms", "Hello", ReplyCapturePolicy.incomingAligned(159, 177)))
  }
  @Test fun immediateReplyRequiresStableNewText() {
    assertEquals(emptyList<String>(), ReplyCapturePolicy.stableIncoming(emptySet(), listOf("Thanks"), emptySet()) { it })
    assertEquals(listOf("Thanks"), ReplyCapturePolicy.stableIncoming(setOf("Thanks"), listOf("Thanks", "Thanks"), emptySet()) { it })
    assertEquals(emptyList<String>(), ReplyCapturePolicy.stableIncoming(setOf("Thanks"), listOf("Thanks"), setOf("Thanks")) { it })
    assertEquals(emptyList<String>(), ReplyCapturePolicy.stableIncoming(setOf("Old"), listOf("Changed"), emptySet()) { it })
  }

  @Test fun facebookIncomingRequiresConversationSender() {
    assertEquals("Thank you\nPlease call us", ReplyCapturePolicy.facebook("The Dutch Mill Hotel, Thank you\nPlease call us，双击可查看收发日期和时间", "The Dutch Mill Hotel", "Hello"))
    assertNull(ReplyCapturePolicy.facebook("You, Hello", "The Dutch Mill Hotel", "Hello"))
    assertNull(ReplyCapturePolicy.facebook("Other Hotel, Thanks", "The Dutch Mill Hotel", "Hello"))
    assertNull(ReplyCapturePolicy.facebook("The Dutch Mill Hotel, Hello", "The Dutch Mill Hotel", "Hello"))
    assertEquals("Thanks", ReplyCapturePolicy.facebook(", Thanks", "Hotel", "Hello", true))
    assertNull(ReplyCapturePolicy.facebook(", Thanks", "Hotel", "Hello", false))
    assertNull(ReplyCapturePolicy.facebook("Thank you", "The Dutch Mill Hotel", "Hello"))
  }
  @Test fun localAcceptanceIsNotJustAnyBubble() {
    assertTrue(ChannelPolicy.facebookOutgoingCaption("My name, Long message，双击可查看收发日期和时间", "Long message", 312, 540, 1060))
    assertTrue(ChannelPolicy.facebookOutgoingCaption(", Long message", "Long message", 312, 540, 1060))
    assertFalse(ChannelPolicy.facebookOutgoingCaption(", Long message", "Long message", 138, 540, 878))
    assertTrue(ChannelPolicy.facebookAccepted(159, 1048, 1080, true, false))
    assertFalse(ChannelPolicy.facebookAccepted(159, 906, 1080, true, false))
    assertFalse(ChannelPolicy.facebookAccepted(159, 1048, 1080, false, false))
    assertFalse(ChannelPolicy.facebookAccepted(159, 1048, 1080, true, true))
  }
}
