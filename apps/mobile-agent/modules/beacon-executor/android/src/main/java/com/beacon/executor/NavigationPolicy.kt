package com.beacon.executor

/** Navigation has no send/type tool. Public replies and account-changing actions are excluded. */
object NavigationPolicy {
  fun normalized(value: String) = value.lowercase().replace(Regex("[^\\p{L}\\p{N}]"), "")
  fun sameTitle(actual: String, expected: String) = normalized(expected).length >= 4 && normalized(actual) == normalized(expected)
  fun title(text: String, expected: String, top: Int, bottom: Int, height: Int) =
    sameTitle(text, expected) && top >= 0 && bottom > top && bottom <= height * .22
  fun navigationLabel(value: String): String? = when (value.trim().lowercase()) {
    "message", "send message", "发消息", "发送消息", "私信", "messenger", "在 messenger 中打开", "open in messenger", "chat", "聊天" -> "open_messages"
    "more", "more options", "更多", "更多选项", "⋯", "…", "..." -> "open_more"
    else -> null
  }
  fun forbidden(value: String): Boolean = value.trim().lowercase() in setOf(
    "send", "发送", "post", "发布", "comment", "评论", "reply", "回复", "follow", "关注", "like", "赞", "connect", "建立联系", "add friend", "加为好友", "call", "打电话", "inmail", "subscribe", "订阅", "buy", "购买", "log out", "退出登录"
  )
  fun privateComposer(hint: String, resourceId: String, editable: Boolean): Boolean = editable &&
    !Regex("comment|search|reply_to").containsMatchIn(resourceId.lowercase()) &&
    hint.trim().lowercase() in setOf("message", "message…", "message...", "write a message", "write a message…", "write a message...", "type a message", "type a message…", "输入消息", "输入消息…", "输入消息...", "发消息", "发送消息")
  fun mayContinue(action: String) = action in setOf("open_messages", "open_more", "close_popup", "scroll", "back", "wait")
}
