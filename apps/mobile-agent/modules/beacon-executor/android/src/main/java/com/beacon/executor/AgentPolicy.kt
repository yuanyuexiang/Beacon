package com.beacon.executor

/** The model chooses controls; frozen text and one-send semantics remain device-owned. */
object AgentPolicy {
  fun emptyComposer(text: String?, hint: String?, showingHint: Boolean, pkg: String?, resource: String?): Boolean {
    if (text.isNullOrBlank() || showingHint || (!hint.isNullOrBlank() && text == hint)) return true
    // WhatsApp exposes its placeholder as text on some versions, without hint metadata.
    return pkg in setOf("com.whatsapp", "com.whatsapp.w4b") && resource == "$pkg:id/entry" &&
      text.trim() in setOf("发消息", "发送消息", "Message", "Type a message")
  }
  fun allowed(action: String, attempted: Boolean): Boolean = if (attempted) action in setOf("wait", "finish") else
    action in setOf("tap", "input", "send", "scroll", "back", "wait", "finish", "alternate")
  fun terminal(outcome: String, attempted: Boolean, observed: Boolean): String = when {
    attempted && outcome != "sent" -> "unknown"
    outcome == "sent" -> if (attempted && observed) "sent" else "unknown"
    outcome in setOf("unavailable", "needs_action", "failed") -> outcome
    else -> "needs_action"
  }
  fun draftSendControl(text: String, hasDraft: Boolean): Boolean = hasDraft &&
    Regex("(?i)send|post|publish|发送|发布").containsMatchIn(text)
  fun blocked(text: String, publicComment: Boolean = false) = (NavigationPolicy.forbidden(text) && !(publicComment && text.trim().lowercase() in setOf("comment", "comments", "评论", "回复", "reply"))) || Regex(
    "(?i)^(delete|remove|block|report|log out|switch account|pay|purchase|删除|移除|屏蔽|举报|退出登录|切换账号|付款|购买)$"
  ).matches(text.trim())
}
