package com.beacon.executor
import org.junit.Assert.*
import org.junit.Test

class ExecutionResultPolicyTest {
  @Test fun unregisteredDialogIsAResultAndNotAChatTextGuess() {
    assertEquals("not_registered", ExecutionResultPolicy.whatsappDialog("电话号码+44 1224 632443没有 WhatsApp 账户。", true))
    assertEquals("not_registered", ExecutionResultPolicy.whatsappDialog("This phone number isn't on WhatsApp", true))
    assertNull(ExecutionResultPolicy.whatsappDialog("This phone number isn't on WhatsApp", false))
    assertEquals("network_error", ExecutionResultPolicy.whatsappDialog("无法连接，请稍后重试。", false))
  }
  @Test fun pendingServerNullDoesNotBecomeALiteralReason() {
    for (value in listOf(null, "", "null")) assertEquals("target_unverified", ExecutionResultPolicy.resultReason(value, "failed", "未能核对目标电话号码"))
    assertEquals("not_registered", ExecutionResultPolicy.resultReason("not_registered", "unavailable", "没有账户"))
  }
  @Test fun uncertainClickNeverBecomesAnUnregisteredOrRetryableResult() {
    assertEquals("send_unconfirmed", ExecutionResultPolicy.reason("unknown", "网络失败"))
    assertEquals("network_error", ExecutionResultPolicy.reason("failed", "网络失败"))
    assertEquals("account_action_required", ExecutionResultPolicy.reason("needs_action", "请登录"))
    assertEquals("messaging_unavailable", ExecutionResultPolicy.reason("unavailable", "无私信入口"))
  }
}
