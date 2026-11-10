package com.beacon.executor

import android.graphics.Bitmap
import android.graphics.Path
import android.accessibilityservice.GestureDescription
import android.util.Base64
import android.view.WindowManager
import java.io.ByteArrayOutputStream
import java.util.concurrent.CompletableFuture
import android.accessibilityservice.AccessibilityService
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
  @Volatile var autoEnabled = false
  @Volatile var autoError = ""
  private var autoGeneration = 0L
  private val main = Handler(Looper.getMainLooper())
  override fun onServiceConnected() {
    super.onServiceConnected(); instance = this
    main.post(object : Runnable {
      override fun run() {
        if (instance !== this@PhoneService) return
        val event = AccessibilityEvent.obtain().apply { packageName = "com.facebook.katana" }
        onAccessibilityEvent(event)
        event.recycle()
        main.postDelayed(this, 5000)
      }
    })
  }
  private var replyCheckPending = false
  private val replyStable = mutableMapOf<String, Int>()
  override fun onAccessibilityEvent(event: AccessibilityEvent?) {
    if (replyCheckPending || running || event?.packageName?.toString() !in PlatformAdapters.packages.values.flatten()) return
    replyCheckPending = true
    main.postDelayed({
      thread(name = "beacon-chat-replies") {
        try { observeReplies() } catch (_: Exception) { /* A different screen is normal. */ }
        finally { main.post { replyCheckPending = false } }
      }
    }, 1200)
  }
  private fun replyHash(body: String) = java.security.MessageDigest.getInstance("SHA-256")
    .digest(body.toByteArray()).joinToString("") { "%02x".format(it) }
  private fun seedReplies(j: JSONObject, texts: List<String>) {
    j.put("_reply_policy", 2).put("_reply_seen", org.json.JSONArray(texts.map(::replyHash)))
    Journal(this).use { it.save(j) }
  }
  private fun observeReplies() {
    if (running || Vault(this).disconnected() || !ConnectionService.unlocked(this)) return
    val enabled = org.json.JSONArray(NotificationMonitor.channels(this))
    val jobs = Journal(this).use { it.recent() }.map(::JSONObject)
    for (j in jobs) {
      val snapshot = j.optJSONObject("snapshot") ?: continue
      val channel = snapshot.optString("channel", "whatsapp")
      if (!(0 until enabled.length()).any { enabled.optString(it) == channel } ||
          j.optString("outcome") !in setOf("sent", "request_submitted", "unknown")) continue
      val texts = ui {
        if (running) return@ui emptyList<String>()
        val r = rootInActiveWindow ?: return@ui emptyList<String>()
        if (r.packageName?.toString() !in PlatformAdapters.packages[channel].orEmpty()) return@ui emptyList<String>()
        val values = PlatformAdapters.incoming(r, snapshot, true)
        if (PlatformAdapters.header(r, snapshot) != null) {
          getSharedPreferences("beacon-notifications", MODE_PRIVATE).edit()
            .putString("pageStatus", "聊天已匹配 · 可识别回复 ${values.size} 项").apply()
        }
        values
      }
      if (texts.isEmpty()) continue
      // Older app versions have no baseline. Only messages BELOW this task's exact
      // outgoing body can be recovered; unrelated chat history is never scanned.
      val seen = if (j.optInt("_reply_policy") == 2) j.optJSONArray("_reply_seen") ?: org.json.JSONArray() else org.json.JSONArray()
      val known = (0 until seen.length()).map { seen.optString(it) }.toMutableSet()
      for (body in texts) {
        val hash = replyHash(body)
        if (hash in known) continue
        val key = j.getString("id") + hash
        replyStable[key] = (replyStable[key] ?: 0) + 1
        if (replyStable[key]!! < 2) continue
        NotificationMonitor.foreground(this, j, body)
        known.add(hash)
      }
      if (known.size != seen.length() && !running) {
        j.put("_reply_policy", 2).put("_reply_seen", org.json.JSONArray(known.toList().takeLast(100)))
        Journal(this).use { it.save(j) }
      }
      NotificationMonitor.flush(this)
      break // One screen belongs to one most recent execution, never multiple jobs.
    }
  }
  override fun onInterrupt() { pauseAutomatic() }
  private fun detach() { pauseAutomatic(); if (instance === this) instance = null }
  override fun onUnbind(intent: Intent?): Boolean { detach(); return super.onUnbind(intent) }
  override fun onDestroy() { detach(); super.onDestroy() }

  @Synchronized fun pauseReceiving() {
    autoEnabled = false; autoGeneration++
  }
  @Synchronized fun pauseAutomatic() {
    autoEnabled = false; autoGeneration++; stopRequested = true
  }
  @Synchronized fun startAutomatic() {
    check(!autoEnabled) { "自动执行已开启" }
    check(!running && Journal(this).unfinished().isEmpty()) { "请先核对未完成记录，再开启自动执行" }
    check(!Vault(this).disconnected()) { "请先连接平台" }
    check(ConnectionService.unlocked(this)) { "请先解锁手机" }
    ConnectionService.start(this)
    autoEnabled = true; autoError = ""; stopRequested = false
    val generation = ++autoGeneration
    thread(name = "beacon-auto-queue") {
      var autoJob: String? = null
      try {
        while (autoEnabled && generation == autoGeneration) {
          val unlocked = ConnectionService.unlocked(this)
          if (!unlocked) { Thread.sleep(1000); continue }
          if (!ConnectionService.isConnected() || !ConnectionService.executionReady) { Thread.sleep(1000); continue }
          check(!Vault(this).disconnected()) { "平台连接已断开" }
          if (!running) {
            if (autoJob != null) {
              val result = Journal(this).latest()?.let { JSONObject(it) }
              check(result != null && result.optString("id") == autoJob && AutomaticPolicy.canContinue(result.optString("outcome"), result.optBoolean("reported"))) {
                "执行未完成或结果待核对，请回 Beacon 查看记录"
              }
              autoJob = null
            }
            if (AutomaticPolicy.canClaim(autoEnabled && generation == autoGeneration, unlocked, running, Journal(this).unfinished().isNotEmpty())) {
              val response = request("/claim", JSONObject())
              check(response.optString("blocked").isBlank()) { response.optString("blocked") }
              val next = response.optJSONObject("job")
              if (next != null) {
                // Persist a claimed job even if pause arrived during the HTTP request. Never replay it automatically.
                next.put("phase", "claimed"); Journal(this).save(next)
                if (!autoEnabled || generation != autoGeneration) break
                autoJob = next.getString("id")
                execute(next.toString())
              }
            }
          }
          Thread.sleep(5000)
        }
      } catch (e: Exception) {
        if (generation == autoGeneration) { autoError = e.message ?: "自动执行暂停"; pauseAutomatic() }
      }
    }
  }

  private fun <T> ui(fn: () -> T): T {
    if (Looper.myLooper() == Looper.getMainLooper()) return fn()
    val f = FutureTask(fn); main.post(f); return f.get(5, TimeUnit.SECONDS)
  }
  fun inspectAccount(channel: String): String {
    synchronized(this) { check(!running) { "请先完成当前执行，再识别账号" }; running = true }
    return try { AccountInspector(this).inspect(channel) } finally { running = false }
  }
  private fun root(): AccessibilityNodeInfo {
    check(ConnectionService.unlocked(this)) { "手机已锁屏" }
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
  private fun openKnownRecent(j: JSONObject): Boolean {
    val s = j.getJSONObject("snapshot")
    val r = root()
    val candidates = nodes(r, "conversations_row_contact_name").filter {
      val name = it.text?.toString()?.trim() ?: ""
      phone(name) == s.getString("target") ||
        (s.getString("target") == s.getString("sender") &&
          listOf("（你）", "(你)", "(You)", "(you)").any { suffix -> name.endsWith(suffix) })
    }
    return candidates.size == 1 && PlatformAdapters.click(candidates.single())
  }
  private fun waitForTarget(j: JSONObject, rounds: Int): Boolean {
    repeat(rounds) {
      check(!stopRequested) { "执行已暂停" }
      Thread.sleep(500)
      if (ui { try { target(root(), j) } catch (_: Exception) { false } }) return true
      val issue = ui {
        try {
          val r = root(); val texts = PlatformAdapters.flatten(r).mapNotNull { it.text?.toString() }
          val invite = texts.any { it == "邀请使用 WhatsApp" || it.equals("Invite to WhatsApp", true) }
          val message = r.findAccessibilityNodeInfosByViewId("android:id/message").mapNotNull { it.text?.toString() }.joinToString(" ")
          ExecutionResultPolicy.whatsappDialog(if (invite) texts.joinToString(" ") else message, invite)
        } catch (_: Exception) { null }
      }
      if (issue == "not_registered") throw ExecutionFailure(issue, "unavailable", "电话号码 ${j.getJSONObject("snapshot").getString("target")} 没有 WhatsApp 账户，请选择其他联系方式")
      if (issue == "network_error") throw ExecutionFailure(issue, "failed", "WhatsApp 查询号码时无法连接，请检查网络后重试")
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
      if (code !in 200..299) {
        val raw = conn.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
        val diagnostic = try {
          val data = JSONObject(raw); val detail = data.opt("detail")
          if (detail is String) detail.take(300) else if (detail is org.json.JSONArray) (0 until detail.length()).joinToString("; ") { i ->
            val item = detail.getJSONObject(i); "${item.optJSONArray("loc")}: ${item.optString("msg")}"
          }.take(300) else ""
        } catch (_: Exception) { "" }
        error("回填／执行检查失败（HTTP $code）${if (diagnostic.isBlank()) "" else "：$diagnostic"}")
      }
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
    j.put("reason_code", ExecutionResultPolicy.resultReason(j.optString("reason_code"), status, detail))
    if (!j.optBoolean("screenshot_checked")) {
      j.put("screenshot_checked", true)
      // Do not capture another app, lock screen or password page after an interruption.
      val allowed = ui { try { val r = root(); !PlatformAdapters.flatten(r).any { it.isPassword } } catch (_: Exception) { false } }
      if (allowed) screenshot()?.takeIf { it.length <= 900000 }?.let { j.put("screenshot", it) }
    }
    j.put("outcome", status).put("detail", detail).put("reported", false)
    Journal(this).save(j)
    val payload = attempt(j).put("status", status).put("detail", detail).put("reason_code", j.getString("reason_code"))
    if (j.has("screenshot")) payload.put("screenshot", j.getString("screenshot"))
    request("/jobs/${j.getString("id")}/result", payload)
    j.remove("screenshot")
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
        progress(j, "opening")
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
          progress(j, "finding_entry")
          ui { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/$number")).setPackage("com.whatsapp").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
          verified = waitForTarget(j, 30)
        }
        check(verified && !stopRequested) { "未能核对目标电话号码。请在 WhatsApp 核对或使用人工执行" }
        progress(j, "composing")
        val before = ui {
          val r = root(); check(target(r, j)); val entry = nodes(r, "entry").singleOrNull() ?: error("未找到输入框")
          check(entry.text.isNullOrBlank() || entry.text.toString() in setOf("发消息", "Message")) { "聊天已有草稿，已暂停，避免覆盖" }
          val baseline = count(r, body)
          check(entry.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, body) })) { "文字填写失败" }
          baseline
        }
        check(!stopRequested)
        // Permission is checked first. Only the persisted final click boundary is uncertain on recovery.
        seedReplies(j, ui { PlatformAdapters.incoming(root(), snapshot) })
    j.put("phase", "preflight"); Journal(this).save(j)
        request("/jobs/${j.getString("id")}/start", attempt(j))
        ui {
          val r = root(); check(!stopRequested && target(r, j)) { "目标改变或已暂停" }
          check(nodes(r, "entry").singleOrNull()?.text?.toString() == body) { "消息已改变" }
          val sendButton = nodes(r, "send").singleOrNull() ?: error("未找到发送按钮")
          j.put("phase", "click_attempted"); Journal(this).save(j); clickAttempted = true
          check(PlatformAdapters.click(sendButton)) { "发送点击未完成" }
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
          val uncertain = clickAttempted || j.optString("phase") == "click_attempted"
          if (!uncertain && e is ExecutionFailure) j.put("reason_code", e.reason)
          try { settle(j, if (uncertain) "unknown" else if (e is ExecutionFailure) e.outcome else if (e is ContactUnavailable) "unavailable" else if (e is NeedsPhoneAction) "needs_action" else "failed", e.message?.take(500) ?: "执行中断") } catch (_: Exception) { }
        }
      } finally {
        try { returnToBeacon(j) } catch (_: Exception) { /* Saved result remains authoritative. */ }
        running = false
      }
    }
  }
  // Returning is presentation only: never change or repeat the saved execution result.
  private fun returnToBeacon(j: JSONObject) {
    if (j.optString("outcome") !in setOf("sent", "request_submitted", "unavailable", "failed")) return
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse("beacon-mobile:///?tab=" + Uri.encode("任务")))
      .setClassName(packageName, "$packageName.MainActivity")
      .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
    try {
      val manager = getSystemService(android.app.NotificationManager::class.java)
      val channel = "execution-results"
      manager.createNotificationChannel(android.app.NotificationChannel(channel, "任务处理结果", android.app.NotificationManager.IMPORTANCE_DEFAULT))
      val open = android.app.PendingIntent.getActivity(this, 700, intent,
        android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE)
      manager.notify(700, android.app.Notification.Builder(this, channel)
        .setSmallIcon(android.R.drawable.stat_notify_sync).setContentTitle("任务已处理")
        .setContentText(if (j.optBoolean("reported")) "结果已回填，点击返回 Beacon" else "结果已保存在手机，等待同步；点击返回 Beacon")
        .setContentIntent(open).setAutoCancel(true).build())
    } catch (_: Exception) { /* Notification permission may be disabled. */ }
    ui {
      val r = rootInActiveWindow
      val targetForeground = r?.packageName?.toString() in (PlatformAdapters.packages[platform] ?: emptyList())
      val passwordVisible = r?.let { PlatformAdapters.flatten(it).any { node -> node.isPassword } } ?: true
      if (TaskReturnPolicy.shouldReturn(j.optString("outcome"), ConnectionService.unlocked(this), targetForeground, passwordVisible)) {
        try { startActivity(intent) } catch (_: Exception) { /* Result notification remains available. */ }
      }
    }
  }
  private fun progress(j: JSONObject, stage: String) {
    check(!stopRequested) { "执行已暂停" }
    j.put("progress", stage); Journal(this).save(j)
    request("/jobs/${j.getString("id")}/progress", attempt(j).put("stage", stage))
  }
  private fun observation(): JSONObject = ui {
    val bounds = getSystemService(WindowManager::class.java).maximumWindowMetrics.bounds
    PageObservation.json(root(), bounds.width(), bounds.height())
  }
  private fun screenshot(): String? {
    val future = CompletableFuture<String?>()
    try { takeScreenshot(android.view.Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
      override fun onFailure(code: Int) { future.complete(null) }
      override fun onSuccess(result: ScreenshotResult) {
        val buffer = result.hardwareBuffer
        try {
          val bitmap = Bitmap.wrapHardwareBuffer(buffer, result.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
          if (bitmap == null) { future.complete(null); return }
          val scale = minOf(1.0, 720.0 / bitmap.width, 1600.0 / bitmap.height)
          val resized = Bitmap.createScaledBitmap(bitmap, (bitmap.width * scale).toInt(), (bitmap.height * scale).toInt(), true)
          val bytes = ByteArrayOutputStream().also { resized.compress(Bitmap.CompressFormat.JPEG, 65, it) }.toByteArray()
          future.complete(Base64.encodeToString(bytes, Base64.NO_WRAP))
          if (resized !== bitmap) resized.recycle()
          bitmap.recycle()
        } catch (_: Exception) { future.complete(null) } finally { buffer.close() }
      }
    })
    } catch (_: Exception) { return null }
    return try { future.get(5, TimeUnit.SECONDS) } catch (_: Exception) { null }
  }
  private fun navigateStep(advice: JSONObject, page: JSONObject): Boolean = ui {
    check(!stopRequested) { "执行已暂停" }
    if (observation().getString("screen_id") != page.getString("screen_id")) return@ui false
    val action = advice.optString("action")
    check(NavigationPolicy.mayContinue(action)) { "不支持的导航动作" }
    val r = root()
    if (action in setOf("open_messages", "open_more", "close_popup")) {
      // Model positions never reach the send boundary, editable fields or a known destructive control.
      if (PlatformAdapters.input(r) != null) return@ui false
      val flat = PlatformAdapters.flatten(r)
      val nodeId = if (advice.isNull("node_id")) -1 else advice.optInt("node_id", -1)
      if (nodeId >= 0) {
        val node = flat.getOrNull(nodeId) ?: return@ui false
        check(node.isEnabled && !node.isEditable && !NavigationPolicy.forbidden(PageObservation.label(node))) { "该控件不是导航入口" }
        if (PlatformAdapters.click(node)) return@ui true
        val bounds = android.graphics.Rect().also { node.getBoundsInScreen(it) }
        if (!bounds.intersect(0, 0, page.getInt("width"), page.getInt("height")) || !node.isVisibleToUser) return@ui false
        val path = Path().apply { moveTo(bounds.exactCenterX(), bounds.exactCenterY()) }
        return@ui dispatchGesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, 80)).build(), null, null)
      }
      val x = advice.getInt("x") * page.getInt("width") / 1000f
      val y = advice.getInt("y") * page.getInt("height") / 1000f
      val hit = flat.filter { n -> android.graphics.Rect().also { n.getBoundsInScreen(it) }.contains(x.toInt(), y.toInt()) }
      check(hit.none { it.isEditable || NavigationPolicy.forbidden(PageObservation.label(it)) }) { "该位置不是导航入口" }
      val path = Path().apply { moveTo(x, y) }
      return@ui dispatchGesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, 80)).build(), null, null)
    }
    if (action == "back") return@ui performGlobalAction(GLOBAL_ACTION_BACK)
    if (action == "scroll") {
      val forward = advice.optString("direction", "down") != "up"
      return@ui PlatformAdapters.flatten(r).firstOrNull { it.isScrollable }?.performAction(if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD) ?: false
    }
    true
  }
  private fun awaitNavigationPage(before: JSONObject? = null): JSONObject {
    return NavigationWait.await(
      sample = { observation() }, signature = { PageObservation.signature(it) },
      before = before?.let { PageObservation.signature(it) },
      cancelled = { stopRequested }, now = { android.os.SystemClock.elapsedRealtime() },
      pause = { Thread.sleep(it) },
    )
  }

  private fun navigationFeedback(j: JSONObject, advice: JSONObject, before: JSONObject, history: org.json.JSONArray, feedback: org.json.JSONArray): Boolean {
    val dispatched = navigateStep(advice, before)
    val after = if (dispatched) awaitNavigationPage(before) else observation()
    val delta = NavigationFeedback.delta(PageObservation.keys(before), PageObservation.keys(after))
    val changed = delta.first.isNotEmpty() || delta.second.isNotEmpty()
    val rows = before.getJSONArray("nodes")
    val target = (0 until rows.length()).map { rows.getJSONObject(it) }.firstOrNull { it.optInt("id") == advice.optInt("node_id", -1) }?.optString("text").orEmpty()
    val outcome = if (!dispatched) "未执行，页面或控件已变化" else if (changed) "页面已变化" else "页面无明显变化"
    val summary = "${advice.optString("action")}:$target:$outcome; 新增=${delta.first.joinToString().take(60)}; 消失=${delta.second.joinToString().take(60)}".take(240)
    feedback.put(JSONObject().put("action", advice.optString("action")).put("target", target.take(200))
      .put("dispatched", dispatched).put("changed", changed)
      .put("appeared", org.json.JSONArray(delta.first.map { it.take(200) }))
      .put("disappeared", org.json.JSONArray(delta.second.map { it.take(200) })))
    while (feedback.length() > 12) feedback.remove(0)
    history.put(summary)
    while (history.length() > 12) history.remove(0)
    j.put("navigation_history", history); Journal(this).save(j)
    request("/jobs/${j.getString("id")}/progress", attempt(j).put("stage", "finding_entry").put("detail", outcome).put("navigation_history", history))
    return dispatched
  }
  private fun navigationKey(page: JSONObject, advice: JSONObject): String {
    val rows = page.getJSONArray("nodes")
    val node = (0 until rows.length()).map { rows.getJSONObject(it) }
      .firstOrNull { it.optInt("id") == advice.optInt("node_id", -1) }
    val target = node?.let { "${it.optString("role")}|${it.optString("resource_id")}|${it.optString("text")}|${it.optJSONArray("bounds")}" }
      ?: "${advice.optInt("x", -1)}:${advice.optInt("y", -1)}"
    return NavigationFeedback.actionKey(PageObservation.signature(page), advice.optString("action"), target, advice.optString("direction", "down"))
  }
  private fun reachComposer(j: JSONObject, snapshot: JSONObject) {
    val visited = mutableSetOf<String>()
    val history = org.json.JSONArray()
    val feedback = org.json.JSONArray()
    var aiCalls = 0
    repeat(14) {
      check(!stopRequested) { "执行已暂停" }
      val page = awaitNavigationPage()
      val id = page.getString("screen_id")
      val composer = ui { PlatformAdapters.input(root()) != null }
      if (composer && ui { PlatformAdapters.header(root(), snapshot) != null }) return
      val rows = page.getJSONArray("nodes")
      // A page is tried only once per control; the same menu cannot oscillate forever.
      var rule: JSONObject? = null
      if (!composer) for (index in 0 until rows.length()) {
        val node = rows.getJSONObject(index)
        val action = NavigationFeedback.ruleAction(node.getString("text"), node.optBoolean("editable"), node.optBoolean("enabled", true)) ?: continue
        val candidate = JSONObject().put("action", action).put("node_id", node.getInt("id"))
        if (visited.add(navigationKey(page, candidate))) { rule = candidate; break }
      }
      if (rule != null && navigationFeedback(j, rule!!, page, history, feedback)) return@repeat
      if (aiCalls >= 4) throw NeedsPhoneAction("多次观察后仍未找到可用私信入口，消息已保留，可改用其他联系方式")
      progress(j, "reading_page")
      val picture = screenshot()
      if (observation().getString("screen_id") != id) return@repeat
      if (picture != null) page.put("image", picture)
      page.put("history", history).put("feedback", feedback)
      val advice = request("/jobs/${j.getString("id")}/navigation", attempt(j).put("screen", page), 65000)
      aiCalls++
      check(!stopRequested) { "执行已暂停" }
      if (advice.optString("screen_id") != id || observation().getString("screen_id") != id) return@repeat
      val action = advice.optString("action")
      if (action == "ready" && composer && advice.optBoolean("target_match")) {
        val titleId = advice.optInt("title_node_id", -1)
        val title = (0 until rows.length()).map { rows.getJSONObject(it) }.firstOrNull { it.getInt("id") == titleId }
        if (title != null && !title.optBoolean("editable")) {
          snapshot.put("_resolved_title", title.getString("text"))
          if (ui { PlatformAdapters.header(root(), snapshot) != null }) return
        }
      }
      if (action == "unavailable") throw ContactUnavailable(advice.optString("detail", "目标暂无私信入口"))
      if (action == "needs_action") throw NeedsPhoneAction(advice.optString("detail", "当前暂未找到私信入口，消息已保留"))
      if (NavigationPolicy.mayContinue(action)) {
        if (!visited.add(navigationKey(page, advice))) throw NeedsPhoneAction("页面没有进展，已停止重复操作；消息已保留，可人工继续或换渠道")
        navigationFeedback(j, advice, page, history, feedback)
      }
    }
    throw NeedsPhoneAction("当前页面未能进入私信，消息已保留，可继续人工联系或选择其他渠道")
  }
  private fun executeSocial(j: JSONObject, snapshot: JSONObject) {
    val body = snapshot.getString("body")
    val action = snapshot.optString("action", "direct_message")
    progress(j, "opening")
    ui { PlatformAdapters.open(this, snapshot) }
    Thread.sleep(1500)
    if (ChannelPolicy.manualAction(action)) {
      throw NeedsPhoneAction(if (action == "contact_discovery") "已打开频道。请检查消息邀请、商务邮箱或外链；不会自动评论" else "已打开目标主页。请人工确认连接邀请或 InMail 入口及费用；不会自动申请或付费")
    }
    progress(j, "finding_entry")
    reachComposer(j, snapshot)
    progress(j, "composing")
    val before = ui {
      val r = root()
      if (PlatformAdapters.header(r, snapshot) == null) throw NeedsPhoneAction("进入聊天后无法再次核对目标用户名，请人工处理")
      if (PlatformAdapters.requestScreen(r)) j.put("observed_action", "message_request")
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
    seedReplies(j, ui { PlatformAdapters.incoming(root(), snapshot) })
    j.put("phase", "preflight"); Journal(this).save(j)
    request("/jobs/${j.getString("id")}/start", attempt(j))
    ui {
      val r = root()
      check(!stopRequested && PlatformAdapters.header(r, snapshot) != null) { "目标改变或已暂停" }
      check(PlatformAdapters.input(r)?.text?.toString() == body) { "消息已改变" }
      val send = PlatformAdapters.sendButton(r) ?: error("发送按钮已变化")
      j.put("phase", "click_attempted"); Journal(this).save(j)
      if (PlatformAdapters.linkedinForm(r)) {
        // This Compose form rejects ACTION_CLICK. Dispatch ONE gesture as the primary
        // action; never fall back after an ambiguous click that might already submit.
        val b = android.graphics.Rect().also { send.getBoundsInScreen(it) }
        val screen = android.graphics.Rect().also { r.getBoundsInScreen(it) }
        check(!b.isEmpty && screen.contains(b)) { "发送按钮位置无效" }
        val path = Path().apply { moveTo(b.exactCenterX(), b.exactCenterY()) }
        check(dispatchGesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, 80)).build(), null, null)) { "发送点击未完成" }
      } else check(PlatformAdapters.click(send)) { "发送点击未完成" }
    }
    progress(j, "verifying_send")
    var observed = false
    var stableObservations = 0
    repeat(20) {
      if (!observed) {
        Thread.sleep(500)
        val accepted = ui { try { val r = root(); PlatformAdapters.header(r, snapshot) != null && PlatformAdapters.count(r, body) > before && PlatformAdapters.sent(r, body) } catch (_: Exception) { false } }
        stableObservations = if (accepted) stableObservations + 1 else 0
        observed = stableObservations >= (if (platform in setOf("instagram", "facebook")) 4 else 1)
      }
    }
    check(observed) { "无法确认平台发送结果，请核对聊天；不会自动重发" }
    val outcomeAction = j.optString("observed_action", action)
    settle(j, ChannelPolicy.sentOutcome(outcomeAction), if (outcomeAction == "message_request") "已观察到消息请求提交，请等待对方接受" else if (platform == "instagram") "已观察到新增发出气泡且输入框清空，未见发送中或失败；不代表送达或已读" else "已在目标私信观察到新增消息和发送状态")
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
    val texts = PlatformAdapters.incoming(r, snapshot)
    org.json.JSONArray(texts).toString()
    }
  }
  @Synchronized fun recover() {
    check(!running) { "正在执行，请稍后恢复" }
    running = true
    thread {
      try {
        for (j in Journal(this).unfinished()) {
          try { settle(j, j.optString("outcome", if (j.optString("phase") == "click_attempted") "unknown" else "failed"), j.optString("detail", "进程中断，需核对实际聊天")) } catch (e: Exception) { autoError = e.message ?: "结果尚未回填，请稍后重试" }
        }
      } finally { running = false }
    }
  }
}
