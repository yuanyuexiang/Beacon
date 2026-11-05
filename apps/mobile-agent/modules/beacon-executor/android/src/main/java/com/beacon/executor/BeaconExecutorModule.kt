package com.beacon.executor

import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
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
      mapOf("accessibility" to (PhoneService.instance != null), "whatsapp" to installed,
        "unlocked" to !c.getSystemService(KeyguardManager::class.java).isKeyguardLocked,
        "running" to (PhoneService.instance?.running ?: false), "journal" to Journal(c).latest(),
        "history" to Journal(c).recent(), "savedAccount" to Vault(c).account())
    }
    Function("permissions") {
      context().startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
    Function("configure") { server: String, token: String ->
      check(Journal(context()).unfinished().isEmpty()) { "请先恢复未回填记录" }
      Vault(context()).save(server, token)
    }
    Function("credentials") { Vault(context()).read() }
    Function("rememberAccount") { account: String -> Vault(context()).rememberAccount(account) }
    Function("stage") { raw: String ->
      val j = org.json.JSONObject(raw)
      check(Journal(context()).unfinished().isEmpty()) { "请先恢复未回填记录" }
      j.put("phase", "claimed"); Journal(context()).save(j)
    }
    Function("execute") { job: String ->
      (PhoneService.instance ?: error("请先开启 Beacon 无障碍服务")).execute(job)
    }
    Function("pause") { PhoneService.instance?.stopRequested = true }
    Function("recover") { (PhoneService.instance ?: error("请先开启无障碍服务")).recover() }
  }
}
