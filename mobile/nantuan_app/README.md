# 楠團牌室 Android 試用版

Flutter 3.44.0／Dart 3.12，Android 7.0（API 24）以上。這是共用正式網站的 WebView App，不另外複製遊戲引擎。網頁版照常使用；App 用相同帳號登入同一組牌桌與籌碼。App 與 Chrome 的登入 Cookie 各自保存在自己的沙箱。

## 行為

- WebView 保持同一實例，站內換頁不重建語音或遊戲畫面。
- Android 返回鍵在牌桌回大廳並保留座位，結果未確認時保留原操作；根頁退出 App 需確認。
- 切回 App 呼叫既有連線恢復，沒有自動重新下注／重送表單。
- 正式版僅載入 `https://poker.leoapi.dpdns.org`。外站 HTTPS 需確認後交給瀏覽器；不忽略 TLS 憑證錯誤，不開放檔案、任意協定或 HTTP。
- 僅宣告網路和麥克風權限；麥克風由使用者加入語音時才請求，拒絕時可改用只聽不說。不在 Dart 保存網站密碼，也沒有給網頁任意原生功能的 JS bridge。
- 網頁首載失敗時提供重試；重試只 GET 入口，不重播 POST。

## 建置

標準 Android 專案已提交，直接使用指定的 Flutter SDK 建置。

```sh
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
```

正式版需私有環境變數 `ANDROID_KEYSTORE_PATH` 與 `ANDROID_KEYSTORE_PASSWORD`，alias 為 `nantuan`。缺少簽章時拒絕 release 建置，不用臨時 debug key 冒充正式版。通過 PR 模擬器驗證後，正式簽章只在 main 的手動 Android workflow 取得 GitHub Secrets；不要提交 keystore、密碼或 key.properties。此版本供直接安裝試用，尚未發佈 Google Play。

## 驗證

PR 的 Android workflow 先 analyze／unit test，再用 Android 35 模擬器及實際 WebView 操作登入、補給、拉霸開局與收據、原生返回鍵、背景返回、麥克風權限與版面。使用隔離 SQLite，`APP_ORIGIN=http://localhost:8765` 只在 debug 編譯支援，正式版禁止明文連線。

輸出 APK、SHA256、模擬器截圖及紀錄於 workflow artifact。模擬器不能代表所有真實裝置的雙向語音、藍牙耳機或長時間背景限制，交付時需標明實際驗證範圍。
