package com.beacon.executor

import android.app.Notification
import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.time.Instant
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Receives new notifications only; never opens apps, replies or reads notification history. */
class NotificationMonitor : NotificationListenerService() {
  private val worker = Executors.newSingleThreadScheduledExecutor()
  override fun onCreate() {
    super.onCreate()
    worker.scheduleWithFixedDelay({ flush(this) }, 30, 60, TimeUnit.SECONDS)
  }
  override fun onDestroy() { connected = false; worker.shutdownNow(); super.onDestroy() }
  override fun onListenerConnected() { connected = true; worker.execute { flush(this) } }
  override fun onListenerDisconnected() { connected = false }
  override fun onNotificationPosted(sbn: StatusBarNotification) {
    try { capture(sbn) } catch (_: Exception) {
      getSharedPreferences("beacon-notifications", MODE_PRIVATE).edit().putString("error", "本条通知无法解析，请打开聊天后手动回填").apply()
    }
  }
  private fun capture(sbn: StatusBarNotification) {
    val prefs = getSharedPreferences("beacon-notifications", MODE_PRIVATE)
    val channels = JSONArray(prefs.getString("channels", "[]"))
    val channel = PlatformAdapters.packages.entries.firstOrNull { sbn.packageName in it.value }?.key ?: return
    if (!(0 until channels.length()).any { channels.optString(it) == channel }) return
    val n = sbn.notification
    if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
    val enabledAt = prefs.getLong("since", Long.MAX_VALUE)
    val style = try { Notification.Builder.recoverBuilder(this, n).style as? Notification.MessagingStyle } catch (_: Exception) { null }
    if (style?.isGroupConversation == true) return
    val title = (style?.conversationTitle ?: n.extras.getCharSequence(Notification.EXTRA_TITLE))?.toString()?.trim().orEmpty()
    if (title.isBlank()) return
    val messages = style?.messages.orEmpty()
    if (messages.isNotEmpty()) {
      val self = style?.user
      for (m in messages.takeLast(10)) {
        val sender = m.senderPerson
        val senderId = sender?.key ?: sender?.name?.toString()
        val selfId = self?.key ?: self?.name?.toString()
        val body = m.text?.toString()?.trim().orEmpty()
        if (!NotificationPolicy.incoming(body, senderId, selfId, m.timestamp, enabledAt)) continue
        val thread = n.shortcutId?.takeIf { it.isNotBlank() }?.let { sha("${sbn.packageName}|$selfId|$it") }
        queue(channel, title, body, m.timestamp, thread, true, sbn.packageName)
      }
    } else if ((n.category == Notification.CATEGORY_MESSAGE || n.actions?.any { !it.remoteInputs.isNullOrEmpty() } == true) && sbn.postTime >= enabledAt) {
      val body = (n.extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: n.extras.getCharSequence(Notification.EXTRA_TEXT))?.toString()?.trim().orEmpty()
      if (body.isNotBlank()) queue(channel, title, body, sbn.postTime, null, false, sbn.key)
    }
    worker.execute { flush(this) }
  }
  private fun queue(channel: String, title: String, body: String, at: Long, thread: String?, structured: Boolean, source: String) {
    val value = JSONObject().put("event_key", sha("$source|${thread ?: title}|$at|$body"))
      .put("channel", channel).put("thread_key", thread ?: JSONObject.NULL).put("title", title.take(200))
      .put("body", body.take(4000)).put("occurred_at", Instant.ofEpochMilli(at).toString()).put("structured", structured)
    Journal(this).use { it.notice(value) }
  }
  companion object {
    @Volatile private var connected = false
    private fun sha(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }
    fun enabled(c: Context): Boolean = (Settings.Secure.getString(c.contentResolver, "enabled_notification_listeners") ?: "")
      .split(':').mapNotNull { ComponentName.unflattenFromString(it) }.contains(ComponentName(c, NotificationMonitor::class.java))
    fun channels(c: Context): String = c.getSharedPreferences("beacon-notifications", MODE_PRIVATE).getString("channels", "[]") ?: "[]"
    fun configure(c: Context, raw: String) {
      val arr = JSONArray(raw)
      check((0 until arr.length()).all { arr.optString(it) in PlatformAdapters.packages }) { "未知渠道" }
      val old = channels(c)
      val prefs = c.getSharedPreferences("beacon-notifications", MODE_PRIVATE)
      if (old != raw) {
        Journal(c).use { it.clearNotices() }
        prefs.edit().putString("channels", raw).putLong("since", System.currentTimeMillis()).remove("error").apply()
      }
      if (arr.length() > 0) requestRebind(ComponentName(c, NotificationMonitor::class.java))
    }
    @Synchronized fun flush(c: Context) {
      val prefs = c.getSharedPreferences("beacon-notifications", MODE_PRIVATE)
      if (!enabled(c) || JSONArray(channels(c)).length() == 0) return
      try {
        val credentials = Vault(c).read()
        if (credentials["token"].isNullOrBlank()) return
        Journal(c).use { queue ->
        for (notice in queue.pendingNotices()) {
          if (!(0 until JSONArray(channels(c)).length()).any { JSONArray(channels(c)).optString(it) == notice.optString("channel") }) return
          val conn = URL(credentials["server"] + "/api/mobile/device/notifications").openConnection() as HttpURLConnection
          try {
            conn.requestMethod = "POST"; conn.connectTimeout = 10000; conn.readTimeout = 10000; conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("Authorization", "Bearer " + credentials["token"])
            conn.outputStream.use { it.write(notice.toString().toByteArray()) }
            val code = conn.responseCode
            if (code in 200..299) { conn.inputStream.use { it.readBytes() }; queue.noticeUploaded(notice.getString("event_key")) }
            else if (code == 422) { queue.noticeUploaded(notice.getString("event_key")) }
            else { prefs.edit().putString("error", "通知同步失败（HTTP $code），恢复连接后重试").apply(); return }
          } finally { conn.disconnect() }
        }
        }
        prefs.edit().remove("error").putLong("synced", System.currentTimeMillis()).apply()
      } catch (_: Exception) { prefs.edit().putString("error", "通知暂未上传，恢复网络后自动重试；也可点击同步").apply() }
    }
    fun status(c: Context): Map<String, Any> {
      val prefs = c.getSharedPreferences("beacon-notifications", MODE_PRIVATE)
      return mapOf("granted" to enabled(c), "connected" to connected, "channels" to channels(c), "pending" to Journal(c).use { it.noticeCount() },
        "error" to (prefs.getString("error", "") ?: ""), "synced" to prefs.getLong("synced", 0))
    }
  }
}
