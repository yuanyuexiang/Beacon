package com.beacon.executor

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

class NeedsPhoneAction(message: String) : Exception(message)
class ContactUnavailable(message: String) : Exception(message)

/** Platform semantics; visual navigation is isolated from the final send boundary. */
object PlatformAdapters {
  val packages = linkedMapOf(
    "whatsapp" to listOf("com.whatsapp"),
    "facebook" to listOf("com.facebook.katana", "com.facebook.orca"),
    "instagram" to listOf("com.instagram.android"),
    "linkedin" to listOf("com.linkedin.android"),
    "tiktok" to listOf("com.zhiliaoapp.musically", "com.ss.android.ugc.trill"),
    "youtube" to listOf("com.google.android.youtube"),
    "x" to listOf("com.twitter.android")
  )
  private val hosts = mapOf("facebook" to setOf("facebook.com", "www.facebook.com", "m.facebook.com"), "instagram" to setOf("instagram.com", "www.instagram.com"), "linkedin" to setOf("linkedin.com", "www.linkedin.com"), "tiktok" to setOf("tiktok.com", "www.tiktok.com"), "youtube" to setOf("youtube.com", "www.youtube.com", "m.youtube.com"), "x" to setOf("x.com", "www.x.com", "twitter.com", "www.twitter.com"))
  fun open(c: Context, snapshot: JSONObject) {
    val channel = snapshot.getString("channel")
    val target = snapshot.getString("target")
    val uri = Uri.parse(if (channel == "whatsapp") "https://wa.me/${target.removePrefix("+")}" else target)
    check(uri.scheme == "https" && uri.userInfo == null && (uri.port == -1 || uri.port == 443)) { "目标链接无效" }
    check(if (channel == "whatsapp") uri.host == "wa.me" else uri.host in (hosts[channel] ?: emptySet())) { "链接与渠道不一致" }
    val candidates = packages[channel] ?: error("尚未适配此平台")
    val pkg = candidates.firstOrNull { try { c.packageManager.getPackageInfo(it, 0); true } catch (_: Exception) { false } } ?: throw NeedsPhoneAction("请先安装 ${channel} 官方应用")
    c.startActivity(Intent(Intent.ACTION_VIEW, uri).setPackage(pkg).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
  }
  fun flatten(r: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
    val result = mutableListOf<AccessibilityNodeInfo>()
    fun visit(n: AccessibilityNodeInfo, depth: Int) {
      if (depth > 40 || result.size >= 1500) return
      if (n.isVisibleToUser) result.add(n)
      for (i in 0 until n.childCount) n.getChild(i)?.let { visit(it, depth + 1) }
    }
    visit(r, 0); return result
  }
  fun click(n: AccessibilityNodeInfo): Boolean {
    var node: AccessibilityNodeInfo? = n
    repeat(4) { val current = node ?: return false; if (current.isClickable) return current.performAction(AccessibilityNodeInfo.ACTION_CLICK); node = current.parent }
    return false
  }
  private fun clickableNode(n: AccessibilityNodeInfo): AccessibilityNodeInfo? {
    var node: AccessibilityNodeInfo? = n
    repeat(4) { val current = node ?: return null; if (current.isClickable) return current; node = current.parent }
    return null
  }
  private fun id(n: AccessibilityNodeInfo) = n.viewIdResourceName?.substringAfter(":id/")?.lowercase() ?: ""
  private fun label(n: AccessibilityNodeInfo) = (n.text?.toString()?.takeIf { it.isNotBlank() } ?: n.contentDescription?.toString())?.trim() ?: ""
  fun header(r: AccessibilityNodeInfo, snapshot: JSONObject): String? {
    val uri = Uri.parse(snapshot.getString("target")); val handle = uri.lastPathSegment?.removePrefix("@") ?: return null
    val expectedName = snapshot.optString("_resolved_title").ifBlank { if (handle == "profile.php" || handle.all { it.isDigit() }) snapshot.optString("lead_name") else "" }
    val all = flatten(r)
    val facebook = r.packageName?.toString() in packages["facebook"].orEmpty()
    val rect = android.graphics.Rect().also { r.getBoundsInScreen(it) }
    val chat = all.any { ChannelPolicy.facebookComposer(it.hintText?.toString() ?: "", it.contentDescription?.toString() ?: "", it.isEditable) }
    return all.firstOrNull {
      val bounds = android.graphics.Rect().also { box -> it.getBoundsInScreen(box) }
      (expectedName.isNotBlank() && !it.isEditable && NavigationPolicy.title(label(it), expectedName, bounds.top - rect.top, bounds.bottom - rect.top, rect.height())) ||
      ChannelPolicy.identity(id(it), label(it), handle) || facebook && !it.isEditable && ChannelPolicy.facebookTitle(label(it), handle, bounds.top - rect.top, bounds.bottom - rect.top, rect.height(), chat)
    }?.let { label(it) }
  }
  fun linkedinForm(r: AccessibilityNodeInfo) = r.packageName?.toString() in packages["linkedin"].orEmpty() && ChannelPolicy.linkedinCompanyForm(flatten(r).map(::label))
  fun input(r: AccessibilityNodeInfo): AccessibilityNodeInfo? = flatten(r).filter {
    (linkedinForm(r) && it.isEditable) || ChannelPolicy.composer(id(it), it.isEditable) || NavigationPolicy.privateComposer(it.hintText?.toString().orEmpty(), id(it), it.isEditable) || r.packageName?.toString() in packages["facebook"].orEmpty() && ChannelPolicy.facebookComposer(it.hintText?.toString() ?: "", it.contentDescription?.toString() ?: "", it.isEditable)
  }.singleOrNull()
  fun requestScreen(r: AccessibilityNodeInfo): Boolean = flatten(r).any {
    label(it).lowercase() in setOf("message request", "send message request", "invite to chat", "消息请求", "发送消息请求", "邀请聊天")
  }
  fun fill(r: AccessibilityNodeInfo, body: String) {
    val entry = input(r) ?: throw NeedsPhoneAction("未识别到独立私信输入框。请在官方应用进入目标聊天后人工处理，系统不会改发公开评论")
    if (entry.text?.toString() == body) return // Reuse the exact unsent draft; never overwrite another draft.
    check(entry.text.isNullOrBlank() || entry.isShowingHintText || (!entry.hintText.isNullOrBlank() && entry.text?.toString() == entry.hintText?.toString()) || label(entry) in setOf("Message", "发消息", "发送消息", "Write a message…", "Message…")) { "聊天已有草稿，请先人工核对，避免覆盖" }
    check(entry.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, body) })) { "文字填写失败" }
  }
  fun sendButton(r: AccessibilityNodeInfo): AccessibilityNodeInfo? = flatten(r).filter {
    (id(it).matches(Regex(".*(send_button|send_message_button|composer_send|message_send).*")) || label(it) in setOf("Send", "发送") || linkedinForm(r) && label(it) == "发消息") && it.isEnabled && !it.isEditable
  }.mapNotNull { clickableNode(it) }.distinctBy { android.graphics.Rect().also { rect -> it.getBoundsInScreen(rect) }.toString() }.singleOrNull()
  private fun bodyNode(n: AccessibilityNodeInfo, body: String, center: Int): Boolean {
    if (n.isEditable) return false
    if (n.text?.toString() == body) return true
    val desc = n.contentDescription?.toString() ?: return false
    val bounds = android.graphics.Rect().also { n.getBoundsInScreen(it) }
    return n.packageName?.toString() in packages["facebook"].orEmpty() &&
      (desc.startsWith("你, $body，") || desc.startsWith("你，$body，") || desc.startsWith("$body，双击") || desc.startsWith("You, $body,") || ChannelPolicy.facebookOutgoingCaption(desc, body, bounds.left, center))
  }
  fun count(r: AccessibilityNodeInfo, body: String): Int {
    val screen = android.graphics.Rect().also { r.getBoundsInScreen(it) }
    return flatten(r).count { bodyNode(it, body, screen.centerX()) }
  }
  fun sent(r: AccessibilityNodeInfo, body: String): Boolean {
    val rootBounds = android.graphics.Rect().also { r.getBoundsInScreen(it) }
    val message = flatten(r).lastOrNull { bodyNode(it, body, rootBounds.centerX()) } ?: return false
    val messageBounds = android.graphics.Rect().also { message.getBoundsInScreen(it) }
    if (r.packageName?.toString() in packages["facebook"].orEmpty()) {
      val screen = android.graphics.Rect().also { r.getBoundsInScreen(it) }
      val receipt = flatten(r).any {
        val b = android.graphics.Rect().also { box -> it.getBoundsInScreen(box) }
        val status = label(it)
        ChannelPolicy.facebookReceipt(status, b.left, b.top, b.bottom, screen.centerX(), screen.height(), messageBounds.top, messageBounds.bottom)
      }
      if (receipt) return true
    }
    if (r.packageName?.toString() in packages["instagram"].orEmpty()) {
      val entry = input(r)
      val empty = entry != null && (entry.text.isNullOrBlank() || entry.isShowingHintText ||
        (!entry.hintText.isNullOrBlank() && entry.text?.toString() == entry.hintText?.toString()))
      var parent = message.parent
      var inList = false
      val bubbleNodes = mutableListOf(message)
      repeat(6) {
        parent?.let { node ->
          if (id(node) == "message_list") inList = true
          else if (!inList) bubbleNodes.addAll(flatten(node))
          parent = node.parent
        }
      }
      val pending = bubbleNodes.any {
        val text = label(it).lowercase()
        text in setOf("sending", "sending…", "sending...", "failed to send", "not sent", "retry", "发送中", "发送中…", "发送失败", "未发送", "重试") ||
          id(it).contains("send_failed") || it.className?.toString() == "android.widget.ProgressBar"
      }
      if (ChannelPolicy.instagramBubble(messageBounds.left - rootBounds.left, messageBounds.right - rootBounds.left,
          rootBounds.width(), inList, empty, pending)) return true
    }
    var ancestor = message.parent
    repeat(3) {
      val node = ancestor ?: return false
      val children = flatten(node)
      if (children.count { !it.isEditable && (id(it).matches(Regex(".*(message_text|message_body|message_content|message_bubble).*")) || it.text?.toString() == body) } > 1) return false
      if (children.any { label(it) in setOf("Sent", "Delivered", "Read", "已发送", "已送达", "已读") && id(it).contains("status") }) return true
      ancestor = node.parent
    }
    return false
  }
}
