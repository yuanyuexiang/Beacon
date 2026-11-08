package com.beacon.executor

import org.junit.Assert.*
import org.junit.Test

class NavigationFeedbackTest {
  @Test fun contactEntrySurvivesLargePageSelection() {
    val candidates = (1..200).map { Pair("article $it", NavigationFeedback.priority("article $it", false, false, true)) } +
      Pair("Message", NavigationFeedback.priority("Message", false, true, true))
    assertTrue(candidates.sortedByDescending { it.second }.take(160).any { it.first == "Message" })
    assertEquals(0, NavigationFeedback.priority("Message", false, true, false))
  }
  @Test fun unchangedControlsAreNotReportedAsProgress() {
    val before = listOf("button|more", "title|venue")
    assertEquals(Pair(emptyList<String>(), emptyList<String>()), NavigationFeedback.delta(before, before.reversed()))
    assertEquals(listOf("input|message"), NavigationFeedback.delta(before, before + "input|message").first)
  }
  @Test fun repeatedActionIsSharedByRulesAndAiButDifferentTargetsRemainAvailable() {
    val tried = mutableSetOf<String>()
    val key = NavigationFeedback.actionKey("page", "open_more", "menu|left", "down")
    assertTrue(tried.add(key))
    assertFalse(tried.add(NavigationFeedback.actionKey("page", "open_more", "menu|left", "up")))
    assertTrue(tried.add(NavigationFeedback.actionKey("page", "open_more", "menu|right", "down")))
    assertTrue(tried.add(NavigationFeedback.actionKey("new-page", "open_more", "menu|left", "down")))
    assertNotEquals(NavigationFeedback.actionKey("page", "scroll", "", "up"), NavigationFeedback.actionKey("page", "scroll", "", "down"))
  }
  @Test fun editableMessageFieldsAndDisabledButtonsAreNotNavigationEntrances() {
    assertNull(NavigationFeedback.ruleAction("Message", true, true))
    assertNull(NavigationFeedback.ruleAction("Message", false, false))
    assertEquals("open_messages", NavigationFeedback.ruleAction("Message", false, true))
    assertNull(NavigationFeedback.ruleAction("Send", false, true))
  }
  @Test fun summariesHaveBoundedSize() {
    val delta = NavigationFeedback.delta((1..30).map { "old$it" }, (1..30).map { "new$it" })
    assertEquals(8, delta.first.size); assertEquals(8, delta.second.size)
  }
}
