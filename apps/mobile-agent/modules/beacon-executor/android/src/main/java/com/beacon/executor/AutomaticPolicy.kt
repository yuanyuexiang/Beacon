package com.beacon.executor

internal object AutomaticPolicy {
  fun canClaim(enabled: Boolean, unlocked: Boolean, running: Boolean, unfinished: Boolean): Boolean =
    enabled && unlocked && !running && !unfinished

  fun canContinue(outcome: String, reported: Boolean): Boolean =
    reported && outcome in setOf("sent", "request_submitted", "unavailable")
}
