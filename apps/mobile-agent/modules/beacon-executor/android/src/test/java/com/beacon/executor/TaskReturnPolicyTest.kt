package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class TaskReturnPolicyTest {
  @Test fun returnsForSettledOutcomesOnly() {
    for (outcome in listOf("sent", "request_submitted", "unavailable", "failed"))
      assertTrue(TaskReturnPolicy.shouldReturn(outcome, true, true, false))
    for (outcome in listOf("unknown", "needs_action", "claimed", ""))
      assertFalse(TaskReturnPolicy.shouldReturn(outcome, true, true, false))
  }
  @Test fun preservesUserForegroundAndSensitiveScreens() {
    assertFalse(TaskReturnPolicy.shouldReturn("sent", false, true, false))
    assertFalse(TaskReturnPolicy.shouldReturn("sent", true, false, false))
    assertFalse(TaskReturnPolicy.shouldReturn("sent", true, true, true))
  }
}
