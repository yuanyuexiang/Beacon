package com.beacon.executor
import org.junit.Assert.*
import org.junit.Test

class AccountIdentityPolicyTest {
  private fun f(id: String, text: String) = AccountIdentityPolicy.Field(id, text)
  @Test fun doesNotReadAnotherPersonsProfileOrChat() {
    assertNull(AccountIdentityPolicy.identity("instagram", listOf(f("profile_username", "@someone"))))
    assertNull(AccountIdentityPolicy.identity("facebook", listOf(f("message_text", "Tom"), f("button", "Edit profile"))))
  }
  @Test fun identifiesScopedOwnProfileFieldsOnly() {
    assertEquals("@beacon", AccountIdentityPolicy.identity("instagram", listOf(f("button", "编辑个人资料"), f("profile_username", "@beacon"), f("bio", "@another"))))
    assertEquals("Test Person", AccountIdentityPolicy.identity("facebook", listOf(f("button", "Edit profile"), f("profile_name", "Test Person"))))
  }
  @Test fun explicitSelfLinkCanIdentifyFacebookAccount() {
    assertEquals("Test Person", AccountIdentityPolicy.identity("facebook", listOf(f("self_profile_link", "View your profile, Test Person"))))
    assertNull(AccountIdentityPolicy.identity("facebook", listOf(f("self_profile_link", "Other profile, Test Person"))))
    assertNull(AccountIdentityPolicy.identity("instagram", listOf(f("self_profile_link", "View your profile, Test Person"))))
  }
  @Test fun ambiguousIdentityDoesNotReplaceAnExistingAccount() {
    assertNull(AccountIdentityPolicy.identity("instagram", listOf(f("button", "Edit profile"), f("profile_username", "@one"), f("profile_username", "@two"))))
    assertNull(AccountIdentityPolicy.identity("linkedin", listOf(f("button", "Edit profile"), f("profile_name", "One"), f("profile_name", "Two"))))
  }
  @Test fun whatsappRequiresOwnProfileFieldsAndInternationalPhone() {
    assertEquals("+447700900123", AccountIdentityPolicy.identity("whatsapp", listOf(f("profile_info_name", "Test"), f("profile_info_phone", "+44 7700 900123"))))
    assertNull(AccountIdentityPolicy.identity("whatsapp", listOf(f("message_text", "+447700900123"))))
    assertNull(AccountIdentityPolicy.identity("whatsapp", listOf(f("profile_info_name", "Test"), f("profile_info_phone", "07700900123"))))
  }
  @Test fun platformNamesAndUnknownChannelsAreNotIdentities() {
    assertNull(AccountIdentityPolicy.identity("x", listOf(f("button", "Edit profile"), f("profile_name", "Profile"))))
    assertNull(AccountIdentityPolicy.identity("other", listOf(f("button", "Edit profile"), f("profile_name", "Someone"))))
  }
  @Test fun facebookVirtualNameRowIgnoresFeedAndDuplicateWrapper() {
    val labels = listOf(
      AccountIdentityPolicy.PositionedText("Test Person\u00a0", 300, 960, 640, 1040),
      AccountIdentityPolicy.PositionedText("Test Person", 300, 960, 630, 1040),
      AccountIdentityPolicy.PositionedText("Suggested friend", 30, 1400, 600, 1450),
      AccountIdentityPolicy.PositionedText("Share a song", 300, 500, 600, 550)
    )
    assertEquals("Test Person", AccountIdentityPolicy.facebookNameRow(960, 958, 1042, labels))
    assertNull(AccountIdentityPolicy.facebookNameRow(960, 958, 1042, labels + AccountIdentityPolicy.PositionedText("Other", 20, 970, 200, 1020)))
    assertNull(AccountIdentityPolicy.facebookNameRow(0, 958, 1042, labels))
  }
}
