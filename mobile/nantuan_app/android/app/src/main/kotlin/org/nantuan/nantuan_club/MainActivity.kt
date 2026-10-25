package org.nantuan.nantuan_club

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var microphoneResult: MethodChannel.Result? = null
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "org.nantuan.club/device")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "requestMicrophone" -> {
                        if (Build.VERSION.SDK_INT < 23 || checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                            result.success(true)
                        } else if (microphoneResult != null) {
                            result.success(false)
                        } else {
                            microphoneResult = result
                            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 701)
                        }
                    }
                    "openSettings" -> {
                        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
                        result.success(null)
                    }
                    "openBrowser" -> {
                        val uri = Uri.parse(call.argument<String>("url") ?: "")
                        if (uri.scheme != "https" || uri.host.isNullOrEmpty()) {
                            result.error("invalid_url", "HTTPS required", null)
                        } else {
                            try { startActivity(Intent(Intent.ACTION_VIEW, uri)); result.success(null) }
                            catch (_: Exception) { result.error("no_browser", "No browser available", null) }
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 701) {
            microphoneResult?.success(grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED)
            microphoneResult = null
        }
    }
    override fun onDestroy() {
        microphoneResult?.success(false)
        microphoneResult = null
        super.onDestroy()
    }
}
