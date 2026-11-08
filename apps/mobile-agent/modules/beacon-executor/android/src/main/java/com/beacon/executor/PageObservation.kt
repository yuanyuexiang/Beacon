package com.beacon.executor

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/** Stable IDs refer only to this observation, never to a future accessibility tree. */
object PageObservation {
  fun label(n: AccessibilityNodeInfo) = listOf(n.text, n.contentDescription, n.hintText).mapNotNull { it?.toString()?.trim()?.takeIf(String::isNotBlank) }.firstOrNull().orEmpty().take(200)
  fun keys(page: JSONObject): List<String> {
    val rows = page.getJSONArray("nodes")
    return (0 until rows.length()).map { rows.getJSONObject(it) }.filter {
      it.optBoolean("clickable") || it.optBoolean("editable") || NavigationPolicy.navigationLabel(it.optString("text")) != null
    }.map { "${it.optString("role")}|${it.optString("resource_id")}|${it.optString("text")}" }.sorted()
  }
  fun signature(page: JSONObject): String =
    page.optString("package") + ":" + page.optInt("window_id", -1) + ":" + keys(page).joinToString("\u001f")
  fun json(root: AccessibilityNodeInfo, width: Int, height: Int): JSONObject {
    val nodes = JSONArray()
    PlatformAdapters.flatten(root).withIndex().sortedByDescending { (_, node) ->
      NavigationFeedback.priority(label(node), node.isEditable, node.isClickable, node.isEnabled)
    }.forEach { (index, node) ->
      val b = Rect().also { node.getBoundsInScreen(it) }
      val l = b.left.coerceAtLeast(0); val t = b.top.coerceAtLeast(0)
      val r = b.right.coerceAtMost(width); val bottom = b.bottom.coerceAtMost(height)
      if (nodes.length() < 160 && r > l && bottom > t && (label(node).isNotBlank() || node.isClickable || node.isEditable)) {
        nodes.put(JSONObject().put("id", index).put("text", label(node)).put("clickable", node.isClickable).put("editable", node.isEditable)
          .put("enabled", node.isEnabled).put("role", node.className?.toString().orEmpty().take(100))
          .put("resource_id", node.viewIdResourceName.orEmpty().take(200)).put("scrollable", node.isScrollable)
          .put("bounds", JSONArray(listOf(l, t, r, bottom))))
      }
    }
    val value = JSONObject().put("package", root.packageName.toString()).put("width", width).put("height", height).put("nodes", nodes).put("window_id", root.windowId)
    val hash = MessageDigest.getInstance("SHA-256").digest(value.toString().toByteArray()).joinToString("") { "%02x".format(it) }
    return value.put("screen_id", hash)
  }
}
