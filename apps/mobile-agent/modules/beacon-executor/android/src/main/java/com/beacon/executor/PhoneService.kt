package com.beacon.executor

import android.accessibilityservice.AccessibilityService
import android.app.KeyguardManager
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class PhoneService : AccessibilityService() {
  companion object { @Volatile var instance: PhoneService? = null }
  @Volatile var running = false
  @Volatile var stopRequested = false
  private val main = Handler(Looper.getMainLooper())
  override fun onServiceConnected() { instance = this }
  override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
  override fun onInterrupt() { stopRequested = true }
  override fun onDestroy() { stopRequested = true; instance = null; super.onDestroy() }

  private fun <T> ui(fn: () -> T): T {
    if (Looper.myLooper() == Looper.getMainLooper()) return fn()
    val f = FutureTask(fn); main.post(f); return f.get(5, TimeUnit.SECONDS)
  }
  private fun root(): AccessibilityNodeInfo {
    check(!getSystemService(KeyguardManager::class.java).isKeyguardLocked) { "手机已锁屏" }
    val r = rootInActiveWindow ?: error("无法读取页面")
    check(r.packageName?.toString() == "com.whatsapp") { "当前不在 WhatsApp，请人工接管" }
    return r
  }
  private fun nodes(r: AccessibilityNodeInfo, id: String) = r.findAccessibilityNodeInfosByViewId("com.whatsapp:id/$id")
  private fun phone(s: String) = s.replace(Regex("[\\s()\\-\\u200e\\u200f]"), "")
  private fun target(r: AccessibilityNodeInfo, j: JSONObject): Boolean {
    val s = j.getJSONObject("snapshot")
    val header = nodes(r, "conversation_contact_name").firstOrNull()?.text?.toString() ?: return false
    if (phone(header) == s.getString("target")) return true
    // Self chat has a distinct semantic label; a named external contact is not inferred from its display name.
    val subtitle = nodes(r, "conversation_contact_status").firstOrNull()?.text?.toString() ?: ""
    return s.getString("target") == s.getString("sender") &&
      (subtitle == "给自己发消息" || subtitle.equals("Message yourself", true))
  }
  private fun clicked(n: AccessibilityNodeInfo): Boolean {
    if (n.isClickable) return n.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    return n.parent?.let { clicked(it) } ?: false
  }
  private fun openKnownRecent(j: JSONObject): Boolean {
    val s = j.getJSONObject("snapshot")
    val r = root()
    val candidates = nodes(r, "conversations_row_contact_name").filter {
      val name = it.text?.toString()?.trim() ?: ""
      phone(name) == s.getString("target") ||
        (s.getString("target") == s.getString("sender") &&
          listOf("（你）", "(你)", "(You)", "(you)").any { suffix -> name.endsWith(suffix) })
    }
    return candidates.size == 1 && clicked(candidates.single())
  }
  private fun waitForTarget(j: JSONObject, rounds: Int): Boolean {
    repeat(rounds) {
      check(!stopRequested) { "执行已暂停" }
      Thread.sleep(500)
      if (ui { try { target(root(), j) } catch (_: Exception) { false } }) return true
      val disconnected = ui {
        try { root().findAccessibilityNodeInfosByViewId("android:id/message").any {
          it.text?.toString() in setOf("无法连接，请稍后重试。", "Couldn't connect. Please try again later.")
        } } catch (_: Exception) { false }
      }
      check(!disconnected) { "WhatsApp 查询号码时无法连接，请先在 WhatsApp 打开目标聊天后再执行" }
    }
    return false
  }
  private fun request(path: String, payload: JSONObject): JSONObject {
    val cred = Vault(this).read()
    val base = cred["server"] ?: error("未配对")
    check(base.startsWith("https://") || base.startsWith("http://127.0.0.1:")) { "需要 HTTPS 服务器" }
    val conn = URL(base + "/api/mobile/device" + path).openConnection() as HttpURLConnection
    conn.connectTimeout = 10000; conn.readTimeout = 15000; conn.requestMethod = "POST"; conn.doOutput = true
    conn.setRequestProperty("Authorization", "Bearer " + cred["token"])
    conn.setRequestProperty("Content-Type", "application/json")
    try {
      conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
      val code = conn.responseCode
      if (code !in 200..299) error("服务端检查未通过（HTTP $code），请回 Beacon 查看任务")
      return JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
    } finally { conn.disconnect() }
  }
  private fun attempt(j: JSONObject) = JSONObject().put("attempt", j.getInt("attempt")).put("lease", j.getString("lease"))
  private fun count(r: AccessibilityNodeInfo, body: String) = nodes(r, "message_text").count { it.text?.toString() == body }
  private fun sent(r: AccessibilityNodeInfo, body: String): Boolean {
    val message = nodes(r, "message_text").lastOrNull { it.text?.toString() == body } ?: return false
    var parent: AccessibilityNodeInfo? = message.parent
    repeat(4) {
      val statuses = parent?.let { nodes(it, "status") } ?: emptyList()
      if (statuses.any { n -> n.contentDescription?.toString() in setOf("已发送", "已送达", "已读", "Sent", "Delivered", "Read") }) return true
      parent = parent?.parent
    }
    return false
  }
  private fun settle(j: JSONObject, status: String, detail: String) {
    // Persist the exact result before networking; retries replay this result, never the send action.
    j.put("outcome", status).put("detail", detail).put("reported", false)
    Journal(this).save(j)
    request("/jobs/${j.getString("id")}/result", attempt(j).put("status", status).put("detail", detail))
    j.put("reported", true); Journal(this).save(j)
  }
  @Synchronized fun execute(raw: String) {
    check(!running) { "已有执行中的任务" }
    val j = JSONObject(raw)
    val pending = Journal(this).unfinished()
    check(pending.size == 1 && pending[0].getString("id") == j.getString("id") && pending[0].optString("phase") == "claimed") { "本机已有执行日志，请先核对恢复，不会重复发送" }
    running = true; stopRequested = false
    j.put("phase", "preparing"); Journal(this).save(j)
    thread(name = "beacon-phone-execution") {
      var clickAttempted = false
      try {
        val snapshot = j.getJSONObject("snapshot"); val body = snapshot.getString("body")
        val number = snapshot.getString("target").removePrefix("+")
        // Reuse an already open, verified conversation before requesting a fresh number lookup.
        ui {
          val launch = packageManager.getLaunchIntentForPackage("com.whatsapp") ?: error("WhatsApp 未安装")
          startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        var verified = waitForTarget(j, 4)
        if (!verified && ui { try { openKnownRecent(j) } catch (_: Exception) { false } }) {
          verified = waitForTarget(j, 4)
        }
        if (!verified) {
          ui { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/$number")).setPackage("com.whatsapp").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
          verified = waitForTarget(j, 30)
        }
        check(verified && !stopRequested) { "未能核对目标电话号码。请在 WhatsApp 核对或使用人工执行" }
        val before = ui {
          val r = root(); check(target(r, j)); val entry = nodes(r, "entry").singleOrNull() ?: error("未找到输入框")
          check(entry.text.isNullOrBlank() || entry.text.toString() in setOf("发消息", "Message")) { "聊天已有草稿，已暂停，避免覆盖" }
          val baseline = count(r, body)
          check(entry.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, body) })) { "文字填写失败" }
          baseline
        }
        check(!stopRequested)
        // Permission is checked first. Only the persisted final click boundary is uncertain on recovery.
        j.put("phase", "preflight"); Journal(this).save(j)
        request("/jobs/${j.getString("id")}/start", attempt(j))
        ui {
          val r = root(); check(!stopRequested && target(r, j)) { "目标改变或已暂停" }
          check(nodes(r, "entry").singleOrNull()?.text?.toString() == body) { "消息已改变" }
          val sendButton = nodes(r, "send").singleOrNull() ?: error("未找到发送按钮")
          j.put("phase", "click_attempted"); Journal(this).save(j); clickAttempted = true
          check(clicked(sendButton)) { "发送点击未完成" }
        }
        var observed = false
        repeat(20) {
          if (!observed) { Thread.sleep(500); observed = ui { try { val r = root(); target(r, j) && count(r, body) > before && sent(r, body) } catch (_: Exception) { false } } }
        }
        check(observed) { "无法确认发送结果，请核对聊天；不会重复发送" }
        settle(j, "sent", "已在目标聊天观察到新增消息与发送状态")
      } catch (e: Exception) {
        // If result upload failed, preserve the already observed outcome.
        if (!j.has("outcome")) {
          try { settle(j, if (clickAttempted) "unknown" else "failed", e.message?.take(500) ?: "执行中断") } catch (_: Exception) { }
        }
      } finally { running = false }
    }
  }
  @Synchronized fun recover() {
    check(!running) { "正在执行，请稍后恢复" }
    running = true
    thread {
      try {
        for (j in Journal(this).unfinished()) {
          try { settle(j, j.optString("outcome", if (j.optString("phase") == "click_attempted") "unknown" else "failed"), j.optString("detail", "进程中断，需核对实际聊天")) } catch (_: Exception) { }
        }
      } finally { running = false }
    }
  }
}
