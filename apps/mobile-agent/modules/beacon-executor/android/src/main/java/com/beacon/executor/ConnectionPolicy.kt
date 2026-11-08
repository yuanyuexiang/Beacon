package com.beacon.executor

internal object ConnectionPolicy {
  fun fresh(active: Boolean, connected: Boolean, lastContact: Long, now: Long): Boolean =
    active && connected && lastContact > 0 && now >= lastContact && now - lastContact < 60000L
  fun retryMillis(failures: Int): Long = (5000L * (1L shl failures.coerceIn(0, 4))).coerceAtMost(60000L)
  fun label(connected: Boolean, automatic: Boolean, unlocked: Boolean, accessibility: Boolean): String = when {
    !connected -> "连接中断 · 正在重连"
    !accessibility -> "已连接 · 等待开启无障碍"
    !automatic -> "已连接 · 执行已暂停"
    !unlocked -> "已连接 · 等待解锁"
    else -> "已连接 · 等待任务"
  }
}
