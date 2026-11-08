package com.beacon.executor

/** Injectable clock/sleep make slow loading, timeout and cancellation reproducible without a phone. */
object NavigationWait {
  fun <T> await(
    sample: () -> T,
    signature: (T) -> String,
    before: String? = null,
    cancelled: () -> Boolean,
    now: () -> Long,
    pause: (Long) -> Unit,
    timeoutMs: Long = 4000,
  ): T {
    val deadline = now() + timeoutMs
    var previous: String? = null
    var stable = 0
    while (true) {
      check(!cancelled()) { "执行已暂停" }
      val page = sample() // App switches and lost accessibility propagate; never silently retried.
      val key = signature(page)
      stable = if (key == previous) stable + 1 else 0
      previous = key
      if ((stable >= 2 && (before == null || key != before)) || now() >= deadline) return page
      pause(minOf(200, (deadline - now()).coerceAtLeast(1)))
    }
  }
}
