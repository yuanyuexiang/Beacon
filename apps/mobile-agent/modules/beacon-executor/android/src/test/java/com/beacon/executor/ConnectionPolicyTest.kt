package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class ConnectionPolicyTest {
  @Test fun staleConnectionDoesNotClaimAfterLongSleep() {
    assertTrue(ConnectionPolicy.fresh(true, true, 1000, 59999))
    assertFalse(ConnectionPolicy.fresh(true, true, 1000, 61000))
    assertFalse(ConnectionPolicy.fresh(false, true, 1000, 2000))
    assertFalse(ConnectionPolicy.fresh(true, false, 1000, 2000))
    assertFalse(ConnectionPolicy.fresh(true, true, 1000, 999))
  }
  @Test fun retriesBackOffAndStayBounded() {
    assertEquals(listOf(5000L, 10000L, 20000L, 40000L, 60000L, 60000L), (0..5).map { ConnectionPolicy.retryMillis(it) })
    assertEquals(60000L, ConnectionPolicy.retryMillis(Int.MAX_VALUE))
  }
  @Test fun lockedPhoneRemainsConnectedButCannotClaim() {
    assertEquals("已连接 · 等待解锁", ConnectionPolicy.label(true, true, false, true))
    assertFalse(AutomaticPolicy.canClaim(true, false, false, false))
    assertTrue(AutomaticPolicy.canClaim(true, true, false, false))
    assertFalse(AutomaticPolicy.canClaim(true, true, false, true))
  }
  @Test fun pauseAndConnectionAreIndependent() {
    assertEquals("已连接 · 执行已暂停", ConnectionPolicy.label(true, false, true, true))
    assertEquals("已连接 · 等待开启无障碍", ConnectionPolicy.label(true, false, true, false))
    assertEquals("连接中断 · 正在重连", ConnectionPolicy.label(false, true, true, true))
    assertFalse(AutomaticPolicy.canContinue("unknown", true))
  }
}
