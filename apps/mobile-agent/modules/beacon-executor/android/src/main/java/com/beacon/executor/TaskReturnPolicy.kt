package com.beacon.executor

internal object TaskReturnPolicy {
  fun shouldReturn(outcome: String, unlocked: Boolean, targetForeground: Boolean, passwordVisible: Boolean): Boolean =
    outcome in setOf("sent", "request_submitted", "unavailable", "failed") &&
      unlocked && targetForeground && !passwordVisible
}
