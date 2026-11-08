package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class NavigationWaitTest {
  private var clock = 0L
  private fun waitFor(sample: () -> String, before: String? = null, cancelled: () -> Boolean = { false }): String =
    NavigationWait.await(sample, { it }, before, cancelled, { clock }, { clock += it })

  @Test fun waitsForSlowPageThenStableControls() {
    val result = waitFor({ if (clock < 1600) "loading" else "composer" }, "loading")
    assertEquals("composer", result)
    assertEquals(2000L, clock)
  }
  @Test fun unchangedPageReturnsAtDeadlineWithoutAnotherClick() {
    assertEquals("same", waitFor({ "same" }, "same"))
    assertEquals(4000L, clock)
  }
  @Test fun intermediatePagesMustSettle() {
    assertEquals("final", waitFor({ when { clock < 200 -> "one"; clock < 400 -> "two"; else -> "final" } }))
    assertEquals(800L, clock)
  }
  @Test fun cancellationStopsDuringWait() {
    try {
      waitFor({ "same" }, "same", { clock >= 600 })
      fail("must cancel")
    } catch (e: IllegalStateException) { assertEquals("执行已暂停", e.message) }
    assertEquals(600L, clock)
  }
  @Test fun appSwitchOrDisconnectedServiceIsNotRetried() {
    var calls = 0
    try {
      waitFor({ calls++; error("应用已切换") })
      fail("must hand over")
    } catch (e: IllegalStateException) { assertEquals("应用已切换", e.message) }
    assertEquals(1, calls)
  }
}
