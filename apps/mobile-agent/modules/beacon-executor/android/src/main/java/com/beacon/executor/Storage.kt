package com.beacon.executor

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

// Device token is encrypted with a non-exportable Android Keystore key.
class Vault(val c: Context) {
  private val prefs = c.getSharedPreferences("beacon-device", Context.MODE_PRIVATE)
  private fun key(): SecretKey {
    val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (store.getKey("beacon-device", null) as? SecretKey)?.let { return it }
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
      init(KeyGenParameterSpec.Builder("beacon-device", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
    }.generateKey()
  }
  fun save(server: String, token: String) {
    val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
    val encrypted = cipher.doFinal(token.toByteArray())
    check(prefs.edit().putString("server", server).putString("token", Base64.encodeToString(encrypted, Base64.NO_WRAP))
      .putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP)).commit())
  }
  fun read(): Map<String, String> {
    val encoded = prefs.getString("token", null) ?: return mapOf("server" to "", "token" to "")
    val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
      init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP)))
    }
    return mapOf("server" to (prefs.getString("server", "") ?: ""), "token" to String(cipher.doFinal(Base64.decode(encoded, Base64.NO_WRAP))))
  }
  fun rememberAccount(account: String) {
    check(account.matches(Regex("^\\+[1-9][0-9]{6,14}$"))) { "请输入完整国际电话号码" }
    check(prefs.edit().putString("account", account).commit())
  }
  fun account(): String = prefs.getString("account", "") ?: ""
}

class Journal(c: Context) : SQLiteOpenHelper(c, "beacon-execution.db", null, 1) {
  override fun onCreate(db: SQLiteDatabase) { db.execSQL("CREATE TABLE journal (id TEXT PRIMARY KEY, value TEXT NOT NULL)") }
  override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) {}
  fun save(j: JSONObject) {
    writableDatabase.execSQL("INSERT OR REPLACE INTO journal (id,value) VALUES (?,?)", arrayOf(j.getString("id"), j.toString()))
  }
  fun latest(): String = readableDatabase.rawQuery("SELECT value FROM journal ORDER BY rowid DESC LIMIT 1", null).use { if (it.moveToFirst()) it.getString(0) else "" }
  fun recent(): List<String> = readableDatabase.rawQuery("SELECT value FROM journal ORDER BY rowid DESC LIMIT 20", null).use {
    val rows = mutableListOf<String>(); while (it.moveToNext()) rows.add(it.getString(0)); rows
  }
  fun unfinished(): List<JSONObject> = readableDatabase.rawQuery("SELECT value FROM journal", null).use {
    val rows = mutableListOf<JSONObject>()
    while (it.moveToNext()) { val j = JSONObject(it.getString(0)); if (!j.optBoolean("reported")) rows.add(j) }
    rows
  }
  fun contains(id: String): Boolean = readableDatabase.rawQuery("SELECT id FROM journal WHERE id=?", arrayOf(id)).use { it.moveToFirst() }
}
