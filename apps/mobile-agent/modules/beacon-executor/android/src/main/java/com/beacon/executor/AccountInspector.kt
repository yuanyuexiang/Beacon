package com.beacon.executor

import android.accessibilityservice.AccessibilityService
import android.app.KeyguardManager
import android.content.Intent
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit

/** Foreground, user-triggered profile inspection. Never enters editors or messaging controls. */
class AccountInspector(private val service: AccessibilityService) {
  private fun <T> ui(fn: () -> T): T {
    if (Looper.myLooper() == Looper.getMainLooper()) return fn()
    val task = FutureTask(fn)
    Handler(Looper.getMainLooper()).post(task)
    return task.get(5, TimeUnit.SECONDS)
  }
  fun inspect(channel: String): String {
    val packages = PlatformAdapters.packages[channel] ?: error("尚未支持此渠道")
    check(!service.getSystemService(KeyguardManager::class.java).isKeyguardLocked) { "请先解锁手机" }
    val pkg = packages.firstOrNull { service.packageManager.getLaunchIntentForPackage(it) != null } ?: error("未安装对应的社媒 App")
    ui { service.startActivity(service.packageManager.getLaunchIntentForPackage(pkg)!!.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    val visited = mutableSetOf<String>()
    try {
      repeat(40) {
        Thread.sleep(600)
        val result = ui {
          val root = service.rootInActiveWindow ?: return@ui null
          if (root.packageName?.toString() !in packages) return@ui null
          val nodes = PlatformAdapters.flatten(root)
          val fields = nodes.filter { !it.isEditable && !it.isPassword }.map {
            val text = it.text?.toString()?.trim()?.takeIf(String::isNotEmpty) ?: it.contentDescription?.toString()?.trim().orEmpty()
            val id = if (channel == "facebook" && Regex("^(View your profile|Your profile|查看你的个人主页|你的个人主页)[,，:：].+", RegexOption.IGNORE_CASE).matches(text)) "self_profile_link" else it.viewIdResourceName?.substringAfter(":id/") ?: ""
            AccountIdentityPolicy.Field(id, text)
          }.toMutableList()
          if (channel == "facebook" && AccountIdentityPolicy.ownProfile(channel, fields)) {
            val switchers = nodes.filter { it.contentDescription?.toString()?.trim() in setOf("打开主页切换工具", "Open profile switcher") }
            val avatar = nodes.any { it.contentDescription?.toString()?.trim() in setOf("头像", "Profile picture", "Profile photo") }
            val rows = switchers.map { node -> android.graphics.Rect().also { node.getBoundsInScreen(it) } }.distinctBy { Triple(it.left, it.top, it.bottom) }
            if (avatar && rows.size == 1) {
              val row = rows.single()
              val labels = nodes.filter { !it.isEditable && !it.isPassword }.mapNotNull { node ->
                val text = node.text?.toString()?.takeIf(String::isNotBlank) ?: return@mapNotNull null
                val b = android.graphics.Rect().also { node.getBoundsInScreen(it) }
                AccountIdentityPolicy.PositionedText(text, b.left, b.top, b.right, b.bottom)
              }
              AccountIdentityPolicy.facebookNameRow(row.left, row.top, row.bottom, labels)?.let { fields.add(AccountIdentityPolicy.Field("profile_name", it)) }
            }
          }
          AccountIdentityPolicy.identity(channel, fields)?.let { return@ui JSONObject().put("channel", channel).put("identity", it).put("source", "own_profile").put("observed_at", System.currentTimeMillis()).toString() }
          // Own-profile proof present but identity ambiguous: do not navigate away or guess.
          if (AccountIdentityPolicy.ownProfile(channel, fields)) return@ui null
          val explicit = setOf("Your profile", "View your profile", "查看你的个人主页", "你的个人主页", "查看个人主页")
          val bottom = when (channel) {
            "facebook" -> setOf("Profile", "个人主页", "Menu", "菜单")
            "instagram" -> setOf("Profile", "个人主页")
            "linkedin" -> setOf("Me", "我")
            "tiktok" -> setOf("Profile", "Me", "我", "个人主页")
            "youtube" -> setOf("You", "你", "我的")
            else -> emptySet()
          }
          val screen = android.graphics.Rect().also { root.getBoundsInScreen(it) }
          val options = nodes.filter { node ->
            val label = node.contentDescription?.toString()?.trim()?.takeIf(String::isNotEmpty) ?: node.text?.toString()?.trim().orEmpty()
            val bounds = android.graphics.Rect().also { node.getBoundsInScreen(it) }
            label !in visited && (label in explicit || (label in bottom || bottom.any { label.startsWith(it + ",") || label.startsWith(it + "，") }) && bounds.top > screen.top + screen.height() * .72)
          }
          val labels = options.map { it.contentDescription?.toString()?.trim()?.takeIf(String::isNotEmpty) ?: it.text?.toString()?.trim().orEmpty() }.distinct()
          if (labels.size == 1 && visited.size < 3) {
            visited.add(labels.single()); PlatformAdapters.click(options.first())
          }
          null
        }
        if (result != null) return result
      }
      error("未能明确识别本方账号。请在该社媒打开自己的个人资料页，确保能看到“编辑个人资料”，再回 Beacon 重试；本次未保存账号。")
    } finally {
      ui { service.packageManager.getLaunchIntentForPackage(service.packageName)?.let { service.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)) } }
    }
  }
}
