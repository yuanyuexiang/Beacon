package com.beacon.executor

/** Only explicit own-profile controls plus scoped identity fields can produce a candidate. */
object AccountIdentityPolicy {
  data class Field(val id: String, val text: String)
  data class PositionedText(val text: String, val left: Int, val top: Int, val right: Int, val bottom: Int)
  // Facebook virtual views omit resource IDs and heading flags. Scope names to the
  // same horizontal row as the explicit own-profile switcher, never feed headings.
  fun facebookNameRow(switcherLeft: Int, top: Int, bottom: Int, labels: List<PositionedText>): String? {
    if (top >= bottom || switcherLeft <= 0) return null
    return labels.filter { it.left >= 0 && it.right <= switcherLeft && it.top < it.bottom && (it.top + it.bottom) / 2 in top..bottom }
      .map { it.text.replace('\u00a0', ' ').trim() }.filter { it.isNotBlank() && it.length <= 80 }.distinct().singleOrNull()
  }
  private val owners = setOf("edit profile", "edit public profile", "edit channel", "编辑个人资料", "编辑个人主页", "编辑主页", "编辑资料", "编辑频道", "修改个人资料")
  private val ids = mapOf(
    "facebook" to setOf("profile_name", "profile_title", "profile_username"),
    "instagram" to setOf("action_bar_title", "profile_username", "profile_header_full_name"),
    "linkedin" to setOf("profile_name", "profile_view_top_card_name", "profile_top_card_name"),
    "tiktok" to setOf("user_name", "unique_id", "nickname", "profile_username"),
    "youtube" to setOf("channel_name", "channel_handle", "profile_username"),
    "x" to setOf("name", "screen_name", "profile_name", "profile_username"),
    "whatsapp" to setOf("profile_info_name", "profile_info_name_text", "profile_info_phone", "profile_info_phone_text", "registration_phone")
  )
  private fun selfLinks(fields: List<Field>): List<String> = fields.filter { it.id == "self_profile_link" }.mapNotNull {
    Regex("^(?:View your profile|Your profile|查看你的个人主页|你的个人主页)[,，:：]\\s*(.{1,80})$", RegexOption.IGNORE_CASE).matchEntire(it.text)?.groupValues?.get(1)?.trim()
  }.distinct()
  fun ownProfile(channel: String, fields: List<Field>): Boolean {
    if (channel !in ids) return false
    if (channel == "facebook" && selfLinks(fields).size == 1) return true
    if (channel == "whatsapp") return fields.any { it.id in setOf("profile_info_name", "profile_info_name_text") } && fields.any { it.id in setOf("profile_info_phone", "profile_info_phone_text", "registration_phone") }
    return fields.any { it.text.lowercase() in owners }
  }
  fun identity(channel: String, fields: List<Field>): String? {
    if (!ownProfile(channel, fields)) return null
    if (channel == "facebook" && selfLinks(fields).size == 1) return selfLinks(fields).single()
    val scoped = fields.filter { it.id in ids[channel].orEmpty() }.map { it.text.trim() }.filter { it.isNotBlank() && it.length <= 128 }
    if (channel == "whatsapp") {
      return scoped.map { it.replace(Regex("[\\s()\\-\\u200e\\u200f]"), "") }.filter { it.matches(Regex("\\+[1-9][0-9]{6,14}")) }.distinct().singleOrNull()
    }
    val handles = scoped.filter { it.matches(Regex("@[A-Za-z0-9_.-]{2,64}")) }.distinct()
    if (handles.size == 1) return handles.single()
    if (handles.size > 1) return null
    // A name must be in a dedicated profile field, never an arbitrary feed or chat label.
    return scoped.filter { it.lowercase() !in owners && it !in setOf("个人主页", "Profile", "Me", "我") }.distinct().singleOrNull()
  }
}
