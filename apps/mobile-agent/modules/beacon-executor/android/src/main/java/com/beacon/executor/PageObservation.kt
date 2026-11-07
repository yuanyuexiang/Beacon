package com.beacon.executor

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/** Stable IDs refer only to this observation, never to a future accessibility tree. */
object PageObservation {
  fun label(n: AccessibilityNodeInfo) = listOf(n.text, n.contentDescription, n.hintText).mapNotNull { it?.toString()?.trim()?.takeIf(String::isNotBlank) }.firstOrNull().orEmpty().take(200)
  fun json(root: AccessibilityNodeInfo, width: Int, height: Int): JSONObject {
    val nodes = JSONArray()
    PlatformAdapters.flatten(root).forEachIndexed { index, node ->
      val b = Rect().also { node.getBoundsInScreen(it) }
      val l = b.left.coerceAtLeast(0); val t = b.top.coerceAtLeast(0)
      val r = b.right.coerceAtMost(width); val bottom = b.bottom.coerceAtMost(height)
      if (nodes.length() < 160 && r > l && bottom > t && (label(node).isNotBlank() || node.isClickable || node.isEditable)) {
        nodes.put(JSONObject().put("id", index).put("text", label(node)).put("clickable", node.isClickable).put("editable", node.isEditable)
          .put("bounds", JSONArray(listOf(l, t, r, bottom))))
      }
    }
    val value = JSONObject().put("package", root.packageName.toString()).put("width", width).put("height", height).put("nodes", nodes)
    val hash = MessageDigest.getInstance("SHA-256").digest(value.toString().toByteArray()).joinToString("") { "%02x".format(it) }
    return value.put("screen_id", hash)
  }
}
