package com.beacon.executor

import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
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
      mapOf("autoEnabled" to (PhoneService.instance?.autoEnabled ?: false), "autoError" to (PhoneService.instance?.autoError ?: ""), "autoLastContact" to (PhoneService.instance?.autoLastContact ?: 0L), "deviceName" to defaultName, "accessibility" to (PhoneService.instance != null), "whatsapp" to installed,
        "unlocked" to !c.getSystemService(KeyguardManager::class.java).isKeyguardLocked,
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
      NotificationMonitor.configure(context(), "[]"); Vault(context()).save(server, token); Vault(context()).setDisconnected(false)
    }
    Function("credentials") { Vault(context()).read() }
    Function("connectionPaused") { Vault(context()).disconnected() }
    Function("setConnectionPaused") { paused: Boolean -> Vault(context()).setDisconnected(paused) }
    Function("clearConnection") {
      check(PhoneService.instance?.running != true && Journal(context()).unfinished().isEmpty()) { "请先处理当前任务及未回填记录" }
      NotificationMonitor.configure(context(), "[]"); Vault(context()).clearConnection()
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
