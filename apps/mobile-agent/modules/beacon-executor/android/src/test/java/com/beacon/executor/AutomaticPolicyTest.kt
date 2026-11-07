package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class AutomaticPolicyTest {
  @Test fun onlyClaimWhileEnabledUnlockedIdleAndSettled() {
    assertTrue(AutomaticPolicy.canClaim(true, true, false, false))
    assertFalse(AutomaticPolicy.canClaim(false, true, false, false))
    assertFalse(AutomaticPolicy.canClaim(true, false, false, false))
    assertFalse(AutomaticPolicy.canClaim(true, true, true, false))
    assertFalse(AutomaticPolicy.canClaim(true, true, false, true))
  }
  @Test fun onlyContinueAfterSuccessfulPersistedAndReportedResult() {
    assertTrue(AutomaticPolicy.canContinue("sent", true))
    assertTrue(AutomaticPolicy.canContinue("request_submitted", true))
    assertFalse(AutomaticPolicy.canContinue("sent", false))
    for (outcome in listOf("unknown", "failed", "needs_action", "unavailable", "claimed", "")) {
      assertFalse(AutomaticPolicy.canContinue(outcome, true))
    }
  }
}
