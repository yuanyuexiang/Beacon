package com.beacon.executor

import android.content.Context
import android.content.Intent
import android.os.PowerManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class BeaconExecutorModule : Module() {
  private fun context(): Context = appContext.reactContext ?: error("手机页面尚未就绪")
  override fun definition() = ModuleDefinition {
    Name("BeaconExecutor")
    Function("status") {
      val c = context()
      val installed = try { c.packageManager.getPackageInfo("com.whatsapp", 0); true } catch (_: Exception) { false }
      val model = Build.MODEL.orEmpty().trim()
      val brand = Build.MANUFACTURER.orEmpty().trim()
      val deviceName = try { Settings.Global.getString(c.contentResolver, "device_name")?.trim() } catch (_: Exception) { null }
      val defaultName = deviceName?.takeIf { it.isNotBlank() && !it.equals("Android", true) }
        ?: (if (model.startsWith(brand, true)) model else "$brand $model").trim().ifBlank { "Android 手机" }
      mapOf("connectionService" to ConnectionService.active, "platformConnected" to ConnectionService.isConnected(),
        "connectionError" to ConnectionService.error, "connectionLastContact" to ConnectionService.lastContact,
        "batteryUnrestricted" to c.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(c.packageName),
        "notificationPermission" to c.getSystemService(android.app.NotificationManager::class.java).areNotificationsEnabled(),
        "autoEnabled" to (PhoneService.instance?.autoEnabled ?: false), "autoError" to (PhoneService.instance?.autoError ?: ""), "autoLastContact" to ConnectionService.lastContact, "deviceName" to defaultName, "accessibility" to (PhoneService.instance != null), "whatsapp" to installed,
        "unlocked" to ConnectionService.unlocked(c),
        "running" to (PhoneService.instance?.running ?: false), "journal" to Journal(c).latest(),
        "history" to Journal(c).recent(), "savedAccount" to Vault(c).account(), "savedAccounts" to Vault(c).accounts(),
        "installed" to PlatformAdapters.packages.filterValues { pkgs -> pkgs.any { try { c.packageManager.getPackageInfo(it, 0); true } catch (_: Exception) { false } } }.keys.toList())
    }
    AsyncFunction("inspectAccount") { channel: String -> (PhoneService.instance ?: error("请先在设备页开启 Beacon 无障碍服务")).inspectAccount(channel) }
    Function("notificationStatus") { NotificationMonitor.status(context()) }
    Function("notificationSettings") { context().startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    Function("notificationChannels") { raw: String -> NotificationMonitor.configure(context(), raw) }
    AsyncFunction("syncNotifications") { NotificationMonitor.flush(context()) }
    Function("permissions") {
      context().startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
    Function("configure") { server: String, token: String ->
      check(Journal(context()).unfinished().isEmpty()) { "请先恢复未回填记录" }
      PhoneService.instance?.pauseAutomatic(); ConnectionService.stop(context())
      NotificationMonitor.configure(context(), "[]"); Vault(context()).save(server, token); Vault(context()).setDisconnected(false)
    }
    Function("updateAddress") { server: String, previous: String ->
      val c = context(); val old = Vault(c).read()
      check(old["server"] == previous) { "连接已改变，请重新检查" }
      check(validServer(server)) { "请检查平台地址" }
      check(PhoneService.instance?.running != true && Journal(c).unfinished().isEmpty()) { "请先处理当前任务及未回填记录" }
      PhoneService.instance?.pauseAutomatic(); ConnectionService.stop(c)
      Vault(c).save(server, old["token"] ?: error("请先配对")); Vault(c).setDisconnected(false)
      ConnectionService.start(c)
    }
    Function("credentials") { Vault(context()).read() }
    Function("connectionPaused") { Vault(context()).disconnected() }
    Function("startConnection") { ConnectionService.start(context()) }
    Function("backgroundSettings") { context().startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + context().packageName)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    Function("notificationPermission") {
      if (Build.VERSION.SDK_INT >= 33) appContext.currentActivity?.requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1801)
    }
    Function("setConnectionPaused") { paused: Boolean ->
      if (paused) ConnectionService.disconnect(context()) else Vault(context()).setDisconnected(false)
    }
    Function("clearConnection") {
      check(PhoneService.instance?.running != true && Journal(context()).unfinished().isEmpty()) { "请先处理当前任务及未回填记录" }
      ConnectionService.stop(context()); NotificationMonitor.configure(context(), "[]"); Vault(context()).clearConnection()
    }
    Function("rememberAccounts") { raw: String -> Vault(context()).rememberAccounts(raw) }
    Function("rememberAccount") { account: String -> Vault(context()).rememberAccount(account) }
    Function("stage") { raw: String ->
      val j = org.json.JSONObject(raw)
      check(Journal(context()).unfinished().isEmpty()) { "请先恢复未回填记录" }
      j.put("phase", "claimed"); Journal(context()).save(j)
    }
    Function("execute") { job: String ->
      (PhoneService.instance ?: error("请先开启 Beacon 无障碍服务")).execute(job)
    }
    AsyncFunction("captureReplies") { raw: String -> (PhoneService.instance ?: error("请先开启无障碍服务")).captureReplies(raw) }
    Function("openTarget") { raw: String ->
      check(PhoneService.instance?.running != true) { "正在执行，请稍后打开" }
      PlatformAdapters.open(context(), org.json.JSONObject(raw).getJSONObject("snapshot"))
    }
    Function("copyMessage") { body: String ->
      val clipboard = context().getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
      clipboard.setPrimaryClip(android.content.ClipData.newPlainText("Beacon 消息", body))
    }
    Function("startAutomatic") { (PhoneService.instance ?: error("请先开启 Beacon 无障碍服务")).startAutomatic() }
    Function("pause") { PhoneService.instance?.pauseAutomatic() }
    Function("recover") { (PhoneService.instance ?: error("请先开启无障碍服务")).recover() }
  }
}
