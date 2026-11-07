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
  @Volatile private var platform = "whatsapp"
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
  fun inspectAccount(channel: String): String {
    synchronized(this) { check(!running) { "请先完成当前执行，再识别账号" }; running = true }
    return try { AccountInspector(this).inspect(channel) } finally { running = false }
  }
  private fun root(): AccessibilityNodeInfo {
    check(!getSystemService(KeyguardManager::class.java).isKeyguardLocked) { "手机已锁屏" }
    val r = rootInActiveWindow ?: error("无法读取页面")
    check(r.packageName?.toString() in (PlatformAdapters.packages[platform] ?: emptyList())) { "当前不在目标社媒应用，请人工接管" }
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
  fun assistAccount(payload: JSONObject): JSONObject {
    return try { request("/account-assistance", payload, 65000) }
    catch (_: Exception) { JSONObject().put("status", "unavailable").put("detail", "AI 辅助暂不可用，请检查 Beacon 平台连接或手动填写账号；本次未保存。") }
  }
  private fun request(path: String, payload: JSONObject, timeout: Int = 15000): JSONObject {
    val cred = Vault(this).read()
    val base = cred["server"] ?: error("未配对")
    check(validServer(base)) { "需要 HTTPS 服务器" }
    val conn = URL(base + "/api/mobile/device" + path).openConnection() as HttpURLConnection
    conn.connectTimeout = 10000; conn.readTimeout = timeout; conn.requestMethod = "POST"; conn.doOutput = true
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
      // A surrounding message list may contain older "read" receipts; never use those.
      if (parent?.let { nodes(it, "message_text").size > 1 } == true) return false
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
        platform = snapshot.optString("channel", "whatsapp")
        if (platform != "whatsapp") {
          executeSocial(j, snapshot)
          return@thread
        }
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
          try { settle(j, if (clickAttempted || j.optString("phase") == "click_attempted") "unknown" else if (e is NeedsPhoneAction) "needs_action" else "failed", e.message?.take(500) ?: "执行中断") } catch (_: Exception) { }
        }
      } finally { running = false }
    }
  }
  private fun executeSocial(j: JSONObject, snapshot: JSONObject) {
    val body = snapshot.getString("body")
    val action = snapshot.optString("action", "direct_message")
    ui { PlatformAdapters.open(this, snapshot) }
    Thread.sleep(1500)
    if (ChannelPolicy.manualAction(action)) {
      throw NeedsPhoneAction(if (action == "contact_discovery") "已打开频道。请检查消息邀请、商务邮箱或外链；不会自动评论" else "已打开目标主页。请人工确认连接邀请或 InMail 入口及费用；不会自动申请或付费")
    }
    var verified = false
    repeat(40) {
      if (!verified) { Thread.sleep(500); verified = ui { try { PlatformAdapters.header(root(), snapshot) != null } catch (_: Exception) { false } } }
    }
    if (!verified) throw NeedsPhoneAction("已打开主页，但无法从页面核对目标用户名。请人工核对目标并进入私信；本次未发送")
    ui {
      val r = root()
      if (PlatformAdapters.input(r) == null) PlatformAdapters.messageButton(r)?.let { PlatformAdapters.click(it) }
    }
    var composerReady = false
    repeat(40) {
      if (!composerReady) { Thread.sleep(500); composerReady = ui { try { PlatformAdapters.input(root()) != null } catch (_: Exception) { false } } }
    }
    if (!composerReady) throw NeedsPhoneAction("聊天尚未出现私信输入框；首次聊天的开始按钮可能向对方发送事件，请在手机确认后再继续")
    val before = ui {
      val r = root()
      if (PlatformAdapters.header(r, snapshot) == null) throw NeedsPhoneAction("进入聊天后无法再次核对目标用户名，请人工处理")
      if (PlatformAdapters.requestScreen(r) && action != "message_request") throw NeedsPhoneAction("平台当前是消息请求入口，请在网页选择消息请求后重新准备，不能记为普通私信")
      val count = PlatformAdapters.count(r, body)
      PlatformAdapters.fill(r, body)
      count
    }
    // ACTION_SET_TEXT changes the composer asynchronously (e.g. Like becomes Send).
    // Re-read the tree instead of testing the pre-fill AccessibilityNodeInfo snapshot.
    var sendReady = false
    repeat(20) {
      if (!sendReady) {
        Thread.sleep(250)
        sendReady = ui {
          val fresh = root()
          !stopRequested && PlatformAdapters.header(fresh, snapshot) != null &&
            PlatformAdapters.input(fresh)?.text?.toString() == body &&
            PlatformAdapters.sendButton(fresh) != null
        }
      }
    }
    if (!sendReady) throw NeedsPhoneAction("消息已填入但未找到唯一发送按钮，请人工核对；系统未点击发送")
    check(!stopRequested) { "执行已暂停" }
    j.put("phase", "preflight"); Journal(this).save(j)
    request("/jobs/${j.getString("id")}/start", attempt(j))
    ui {
      val r = root()
      check(!stopRequested && PlatformAdapters.header(r, snapshot) != null) { "目标改变或已暂停" }
      check(PlatformAdapters.input(r)?.text?.toString() == body) { "消息已改变" }
      val send = PlatformAdapters.sendButton(r) ?: error("发送按钮已变化")
      j.put("phase", "click_attempted"); Journal(this).save(j)
      check(PlatformAdapters.click(send)) { "发送点击未完成" }
    }
    var observed = false
    repeat(20) {
      if (!observed) { Thread.sleep(500); observed = ui { try { val r = root(); PlatformAdapters.header(r, snapshot) != null && PlatformAdapters.count(r, body) > before && PlatformAdapters.sent(r, body) } catch (_: Exception) { false } } }
    }
    check(observed) { "无法确认平台发送结果，请核对聊天；不会自动重发" }
    settle(j, ChannelPolicy.sentOutcome(action), if (action == "message_request") "已观察到消息请求提交，请等待对方接受" else "已在目标私信观察到新增消息和发送状态")
  }
  fun captureReplies(raw: String): String {
    check(!running) { "正在执行，请稍后读取回复" }
    val snapshot = JSONObject(raw).getJSONObject("snapshot")
    val channel = snapshot.optString("channel", "whatsapp")
    ui {
      val pkg = PlatformAdapters.packages[channel]?.firstOrNull { try { packageManager.getPackageInfo(it, 0); true } catch (_: Exception) { false } } ?: error("未安装目标应用")
      val launch = packageManager.getLaunchIntentForPackage(pkg) ?: error("无法打开目标应用")
      startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
    Thread.sleep(1000)
    return ui {
    check(!running) { "正在执行，请稍后读取回复" }
    val j = JSONObject(raw); val snapshot = j.getJSONObject("snapshot")
    platform = snapshot.optString("channel", "whatsapp")
    val r = root()
    check(if (platform == "whatsapp") target(r, j) else PlatformAdapters.header(r, snapshot) != null) { "当前聊天无法与目标关联，请核对后人工填写回复" }
    val texts = PlatformAdapters.flatten(r).filter { n ->
      !n.isEditable && !n.text.isNullOrBlank() && n.text.toString() != snapshot.optString("body") &&
      (n.viewIdResourceName ?: "").contains(Regex("incoming_message|received_text|message_in_text"))
    }.map { it.text.toString() }.distinct().takeLast(5)
    org.json.JSONArray(texts).toString()
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
