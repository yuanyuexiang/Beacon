package com.beacon.executor

internal object ExecutionResultPolicy {
  // Only call with a platform dialog, never arbitrary received chat text.
  fun whatsappDialog(text: String, inviteVisible: Boolean): String? {
    val t = text.lowercase()
    if (inviteVisible && (t.contains("没有 whatsapp") || t.contains("isn't on whatsapp") || t.contains("is not on whatsapp") || t.contains("not registered"))) return "not_registered"
    if (t.contains("无法连接") || t.contains("couldn't connect") || t.contains("could not connect")) return "network_error"
    return null
  }
  fun resultReason(existing: String?, status: String, detail: String): String =
    existing?.takeUnless { it.isBlank() || it == "null" } ?: reason(status, detail)
  fun reason(status: String, detail: String): String = when {
    status == "unknown" -> "send_unconfirmed"
    status == "sent" -> "sent"
    status == "request_submitted" -> "request_submitted"
    detail.contains("无法连接") || detail.contains("网络") -> "network_error"
    detail.contains("登录") || detail.contains("账号受限") -> "account_action_required"
    detail.contains("好友") || detail.contains("建立连接") -> "connection_required"
    status == "unavailable" -> "messaging_unavailable"
    detail.contains("目标电话号码") || detail.contains("核对目标") -> "target_unverified"
    detail.contains("入口") || detail.contains("输入框") -> "entry_not_found"
    else -> "execution_error"
  }
}

internal class ExecutionFailure(val reason: String, val outcome: String, message: String) : Exception(message)
