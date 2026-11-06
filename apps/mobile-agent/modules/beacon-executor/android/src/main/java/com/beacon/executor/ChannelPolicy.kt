package com.beacon.executor

/** Pure semantic rules, independently replayed in JVM tests without opening any social app. */
object ChannelPolicy {
  private val titleIds = Regex(".*(thread_title|thread_name|chat_title|conversation_title|toolbar_title|profile_name|profile_username|user_name|username).*", RegexOption.IGNORE_CASE)
  private val inputIds = Regex(".*(message_input|message_text_input|message_edit_text|message_composer|chat_input|composer_edit|messaging_text).*", RegexOption.IGNORE_CASE)
  fun identity(id: String, text: String, handle: String): Boolean =
    handle.isNotBlank() && !handle.all { it.isDigit() } && handle != "profile.php" && titleIds.matches(id) && text.removePrefix("@").equals(handle, true)
  fun facebookTitle(text: String, handle: String, top: Int, bottom: Int, height: Int, chat: Boolean): Boolean =
    handle.matches(Regex("[A-Za-z][A-Za-z0-9. _-]+")) && text.trim().replace(Regex("\\s+"), "").equals(handle, true) &&
      top >= 0 && bottom > top && bottom <= height * (if (chat) 0.18 else 0.5)
  fun facebookComposer(hint: String, description: String, editable: Boolean): Boolean = editable &&
    hint in setOf("发消息", "输入消息...", "输入消息…", "Message", "Write a message…", "Type a message") && description in setOf("输入消息", "Message", "Type a message")
  fun facebookOutgoingCaption(description: String, body: String, left: Int, center: Int): Boolean =
    left >= center && body.isNotBlank() && description.endsWith(", $body") && description.length > body.length + 2
  fun composer(id: String, editable: Boolean) = editable && inputIds.matches(id)
  fun sentOutcome(action: String) = if (action == "message_request") "request_submitted" else "sent"
  fun manualAction(action: String) = action in setOf("connection_request", "inmail", "contact_discovery")
}
