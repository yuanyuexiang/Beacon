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
  @Test fun continueAfterReportedTerminalResultButNeverUnknownOrUnreported() {
    assertTrue(AutomaticPolicy.canContinue("sent", true))
    assertTrue(AutomaticPolicy.canContinue("request_submitted", true))
    assertTrue(AutomaticPolicy.canContinue("unavailable", true))
    assertFalse(AutomaticPolicy.canContinue("unavailable", false))
    assertFalse(AutomaticPolicy.canContinue("sent", false))
    assertTrue(AutomaticPolicy.canContinue("failed", true))
    assertTrue(AutomaticPolicy.canContinue("needs_action", true))
    assertFalse(AutomaticPolicy.canContinue("failed", false))
    assertFalse(AutomaticPolicy.canContinue("needs_action", false))
    for (outcome in listOf("unknown", "claimed", "")) {
      assertFalse(AutomaticPolicy.canContinue(outcome, true))
    }
  }
}
