package com.beacon.executor

/** Semantic summaries detect lack of progress; they never authorize a click on an old tree. */
object NavigationFeedback {
  fun priority(text: String, editable: Boolean, clickable: Boolean, enabled: Boolean): Int = when {
    !enabled -> 0
    editable -> 4
    NavigationPolicy.navigationLabel(text) != null -> 5
    clickable -> 3
    text.isNotBlank() -> 1
    else -> 0
  }
  fun ruleAction(text: String, editable: Boolean, enabled: Boolean): String? =
    if (editable || !enabled) null else NavigationPolicy.navigationLabel(text)
  fun actionKey(page: String, action: String, target: String, direction: String): String =
    listOf(page, action, target, if (action == "scroll") direction else "").joinToString("\u001e")
  fun delta(before: List<String>, after: List<String>): Pair<List<String>, List<String>> =
    Pair((after.toSet() - before.toSet()).take(8), (before.toSet() - after.toSet()).take(8))
}
