package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class ReplyCapturePolicyTest {
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
