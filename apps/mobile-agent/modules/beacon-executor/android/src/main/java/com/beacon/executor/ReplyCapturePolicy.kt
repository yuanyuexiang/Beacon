package com.beacon.executor

/** Only explicit incoming message semantics; a left-aligned label alone is not a reply. */
object ReplyCapturePolicy {
  fun facebook(caption: String, title: String, outgoing: String, incomingAligned: Boolean = false): String? {
    val prefix = "$title, "
    if (title.isBlank()) return null
    val raw = if (caption.startsWith(prefix)) caption.removePrefix(prefix)
      else if (incomingAligned && caption.startsWith(", ")) caption.removePrefix(", ") else return null
    val body = raw
      .substringBefore("，双击").substringBefore(", Double tap").trim()
    return body.takeIf { it.isNotBlank() && it != outgoing.trim() && it.length <= 4000 }
  }
}
