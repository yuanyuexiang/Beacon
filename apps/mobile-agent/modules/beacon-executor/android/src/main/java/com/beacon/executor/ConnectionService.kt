package com.beacon.executor

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** User-started cross-device messaging session. Never claims or sends messages. */
class ConnectionService : Service() {
  private val worker = Executors.newSingleThreadScheduledExecutor()
  @Volatile private var stopped = false
  private var failures = 0
  private var notificationText = ""
  override fun onBind(intent: Intent?): IBinder? = null
  override fun onCreate() {
    super.onCreate(); active = true
    getSystemService(NotificationManager::class.java).createNotificationChannel(
      NotificationChannel(CHANNEL, "平台连接", NotificationManager.IMPORTANCE_LOW))
    val n = notification("正在连接 Beacon")
    if (Build.VERSION.SDK_INT >= 34) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING)
    else startForeground(ID, n)
    worker.execute { tick() }
  }
  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    if (intent?.action == PAUSE) PhoneService.instance?.pauseAutomatic()
    if (intent?.action == DISCONNECT) {
      disconnect(this); return START_NOT_STICKY
    }
    if (Vault(this).disconnected()) { stopSelf(); return START_NOT_STICKY }
    // A system restart restores only the connection, never automatic sending.
    return START_STICKY
  }
  private fun tick() {
    if (stopped) return
    var delay = 15000L
    val session = try { Vault(this).read() } catch (_: Exception) {
      error = "设备凭据无法读取，请重新配对"; stopSelf(); return
    }
    try {
      val vault = Vault(this)
      if (vault.disconnected() || vault.read()["token"].isNullOrBlank()) { stopSelf(); return }
      val s = PhoneService.instance
      val unlocked = unlocked(this)
      val installed = PlatformAdapters.packages.filterValues { pkgs -> pkgs.any { try { packageManager.getPackageInfo(it, 0); true } catch (_: Exception) { false } } }.keys
      val payload = JSONObject().put("account", vault.account()).put("accounts", JSONObject(vault.accounts()))
        .put("installed", JSONArray(installed.toList())).put("ready", s?.autoEnabled == true)
        .put("accessibility", s != null).put("unlocked", unlocked).put("app_version", "0.4.0").put("protocol", 3)
      post(this, "/heartbeat", payload)
      if (stopped || vault.disconnected() || vault.read() != session) return
      lastContact = System.currentTimeMillis(); executionReady = payload.optBoolean("ready"); connected = true; error = ""; failures = 0
      update(ConnectionPolicy.label(true, s?.autoEnabled == true, unlocked, s != null))
    } catch (e: DeviceHttpError) {
      if (stopped || Vault(this).read() != session) return
      connected = false; error = "平台检查失败（HTTP ${e.code}）"
      if (e.code == 401 || e.code == 403) {
        PhoneService.instance?.pauseAutomatic(); Vault(this).setDisconnected(true)
        error = "设备授权已失效，请重新配对"; stopSelf(); return
      }
      delay = ConnectionPolicy.retryMillis(failures++)
      update("连接中断 · 正在重连")
    } catch (_: Exception) {
      if (stopped || Vault(this).disconnected()) return
      connected = false; error = "网络暂不可用，正在自动重连"
      delay = ConnectionPolicy.retryMillis(failures++)
      update("连接中断 · 正在重连")
    }
    if (!stopped) worker.schedule({ tick() }, delay, TimeUnit.MILLISECONDS)
  }
  private fun update(text: String) {
    if (!stopped && notificationText != text) {
      notificationText = text
      getSystemService(NotificationManager::class.java).notify(ID, notification(text))
    }
  }
  private fun notification(text: String): Notification {
    val launch = packageManager.getLaunchIntentForPackage(packageName)!!
    val open = PendingIntent.getActivity(this, 0, launch, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    fun action(name: String, code: Int) = PendingIntent.getService(this, code,
      Intent(this, ConnectionService::class.java).setAction(name), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    return Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_notify_sync)
      .setContentTitle("Beacon 手机助手").setContentText(text).setContentIntent(open)
      .setOngoing(true).setOnlyAlertOnce(true)
      .addAction(Notification.Action.Builder(null, "暂停执行", action(PAUSE, 1)).build())
      .addAction(Notification.Action.Builder(null, "断开连接", action(DISCONNECT, 2)).build()).build()
  }
  override fun onDestroy() {
    stopped = true; active = false; connected = false; executionReady = false
    worker.shutdownNow(); PhoneService.instance?.pauseAutomatic()
    stopForeground(STOP_FOREGROUND_REMOVE); super.onDestroy()
  }
  companion object {
    private const val CHANNEL = "beacon-platform"
    private const val ID = 1801
    private const val PAUSE = "beacon.PAUSE"
    private const val DISCONNECT = "beacon.DISCONNECT"
    @Volatile var active = false
    @Volatile var executionReady = false
    @Volatile var connected = false
    @Volatile var lastContact = 0L
    @Volatile var error = ""
    fun isConnected(): Boolean = ConnectionPolicy.fresh(active, connected, lastContact, System.currentTimeMillis())
    fun unlocked(c: Context): Boolean = c.getSystemService(PowerManager::class.java).isInteractive && !c.getSystemService(KeyguardManager::class.java).isKeyguardLocked
    fun start(c: Context) {
      check(!Vault(c).disconnected() && !Vault(c).read()["token"].isNullOrBlank()) { "请先连接平台" }
      c.startForegroundService(Intent(c, ConnectionService::class.java))
    }
    fun stop(c: Context) { c.stopService(Intent(c, ConnectionService::class.java)) }
    fun disconnect(c: Context) {
      val credentials = Vault(c).read()
      PhoneService.instance?.pauseAutomatic(); Vault(c).setDisconnected(true); connected = false; error = ""
      stop(c)
      thread(name = "beacon-disconnect") {
        try { post(c, "/disconnect", JSONObject(), credentials) } catch (_: Exception) { /* Server expires stale presence if offline. */ }
      }
    }
    fun post(c: Context, path: String, payload: JSONObject, disconnectCredentials: Map<String, String>? = null): JSONObject {
      val v = Vault(c)
      check(!v.disconnected() || path == "/disconnect") { "平台连接已断开" }
      check(disconnectCredentials == null || path == "/disconnect")
      val cred = disconnectCredentials ?: v.read(); val base = cred["server"].orEmpty()
      check(validServer(base)) { "请检查平台地址" }
      val conn = URL(base + "/api/mobile/device" + path).openConnection() as HttpURLConnection
      try {
        conn.requestMethod = "POST"; conn.connectTimeout = 10000; conn.readTimeout = 15000; conn.doOutput = true
        conn.setRequestProperty("Authorization", "Bearer " + cred["token"])
        conn.setRequestProperty("Content-Type", "application/json")
        conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
        if (conn.responseCode !in 200..299) throw DeviceHttpError(conn.responseCode)
        return JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
      } finally { conn.disconnect() }
    }
  }
}
internal class DeviceHttpError(val code: Int) : Exception("HTTP $code")
