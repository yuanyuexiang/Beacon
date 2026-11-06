package com.beacon.executor

object NotificationPolicy {
  fun incoming(body: String, sender: String?, self: String?, timestamp: Long, enabledAt: Long): Boolean =
    body.isNotBlank() && !sender.isNullOrBlank() && !self.isNullOrBlank() && sender != self &&
      timestamp >= enabledAt && timestamp <= System.currentTimeMillis() + 300000
}
