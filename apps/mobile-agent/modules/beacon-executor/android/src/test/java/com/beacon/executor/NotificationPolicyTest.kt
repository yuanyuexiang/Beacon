package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class NotificationPolicyTest {
  @Test fun onlyExplicitIncomingMessagesAfterEnableAreCandidates() {
    val now = System.currentTimeMillis()
    assertTrue(NotificationPolicy.incoming("Reply", "customer", "me", now, now - 1000))
    assertFalse(NotificationPolicy.incoming("Reply", "me", "me", now, now - 1000))
    assertFalse(NotificationPolicy.incoming("Reply", null, "me", now, now - 1000))
    assertFalse(NotificationPolicy.incoming("Reply", "customer", null, now, now - 1000))
    assertFalse(NotificationPolicy.incoming("Reply", "customer", "me", now - 2000, now - 1000))
    assertFalse(NotificationPolicy.incoming(" ", "customer", "me", now, now - 1000))
    assertFalse(NotificationPolicy.incoming("Reply", "customer", "me", now + 600000, now - 1000))
  }
}
