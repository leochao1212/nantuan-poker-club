# 測試與驗證

Python 測試已集中至 tests/python/，與 tests/browser/ 分開。整理時完整保留 45 個檔案、386 個測試案例；之後以每次 CI 的實際結果為準。

## 後端

~~~sh
python -m unittest discover -s tests/python -t . -v
~~~

45 個 tests/python/test_*.py 包含規則、API、交易、SSE、語音、資金守恆與恢復。每個檔案的用途與共用 fixture 見 [Python 測試清單](../tests/python/README.md)。測試使用 TemporaryDirectory 與獨立 SQLite，會在 loopback 啟動測試服務，不接正式資料。

| 修改面向 | 先跑的檔案 |
| --- | --- |
| 德州規則與資金 | test_poker、test_rules、test_transactions、test_funding |
| 21 點下注／多人 | test_blackjack_confirmation、test_gate_blackjack、test_arcade |
| 房間推播、離線恢復 | test_realtime、test_presence、test_mobile_recovery、test_connection_review、test_push_views |
| 遊戲設定 | test_game_settings、test_payouts、test_fairness |
| 會所與員工 | test_income、test_upgrades、test_clubhouse_speed、test_staff |
| 語音 | test_voice |
| 個人資料／管理／轉帳 | test_profiles、test_admin、test_transfers |

從根目錄單跑檔案：`python -m unittest tests.python.test_transfers -v`；單跑類別／案例可接續 `.TransferRules` 或方法名。不要直接執行資料夾內的 .py 檔。

測試包含固定時間與效能閾值；若 CI 在共用 runner 超時，先看程序與網路等待，不以放寬規則或移除守恆斷言解決。可重跑有證據的資源競爭失敗。

## JavaScript 與瀏覽器

~~~sh
node scripts/check-js.cjs
npm ci
npx playwright install chromium
npm run test:ui
~~~

check-js 檢查 static 所有 JavaScript 語法。browser smoke 會啟動隔離伺服器，註冊合成帳號，檢查頁面、手機會所不遮圖、升級入口與兩人 21 點確認／手牌顯示。它不是實體 iPhone／Android、所有遊戲派彩或真實麥克風音質認證。

若使用已安裝的 Chrome／Edge，可設定 PLAYWRIGHT_EXECUTABLE_PATH；Python 不在 PATH 時設定 PYTHON。測試輸出放 artifacts/ 並由 .gitignore 排除。

## 手動頁面驗收

- 320、393、768、1366px 與手機橫向；長名稱、最低／高點數、空桌／滿桌。
- 在開始鍵上連按，送出狀態與結果不能讓按鈕位移。
- 修改未提交金額或選牌後讓另一個玩家行動，草稿仍保留。
- 手機切其他 App 再回來，連線恢復且原操作不重複扣點。
- 語音加入後切大廳／觀戰／牌桌，不重建通話；麥克風與只聽不說可用。
- 回放不公開未允許的手牌；管理員按鈕不只是前端隱藏，API 也要拒絕越權。
- 降低動態與鍵盤焦點仍能完成流程，底部導航不蓋住最後一個可操作項目。

GitHub Actions 執行程式庫內的檢查。正式部署前還需在部署目標檢查容器、版本、資料備份、歷史保留與點數守恆。

牌桌首屏回歸由 `tests/browser/layout.cjs` 載入 `table-controls.cjs`：驗證標題列離桌確認、說明對話框、骰寶／輪盤在深度捲動與慢回應期間保留底部操作列、清除押注後解除浮動、重新同步的 44px 觸控範圍，以及拉霸錯誤提示保持在視窗內。射龍門另測 760／761／800／1000／1024px 斷點；溢出時保存截圖與元素尺寸。測試使用隔離資料庫與合成帳號，延遲情境攔截測試操作回傳錯誤，不接正式服務。

### 現行圖片與一般動畫

`npm run test:motion` 使用隔離帳號與實際畫面產生函式，開啟正常動畫，涵蓋 Chromium／WebKit 手機與桌機共 384 個動畫時間點，六種拉霸符號、六個骰面、連續相同結果、圖片延遲／失敗及恢復，另檢查礦區與爬塔 49 個圖格在每個瀏覽器／裝置組合內不溢出。檢查只有現行圖片、沒有下層舊 SVG，並保存代表截圖。畫面 fixture 不向正式牌局或點數資料寫入假結果。

`test:layout` 同時保存固定元件幾何尺寸，檢查圖片失敗時的現行占位，不再期待舊 SVG 備用圖。HTTP 靜態檔測試確認僅一份樣式、退役路徑回 404，以及圖片指紋、不可變快取與錯誤版本不進快取。`python scripts/check-ui-assets.py` 檢查圖片內容、版本表、素材清單及 CSS 網址一致；換圖時加 `--write` 更新。

### 輪盤／拉霸回執與揭曉

`npm run test:reveal` 在隔離資料庫執行真實操作，涵蓋 Chromium／WebKit 手機與桌機：點擊即轉、停止後才揭曉、1800ms 慢回應與推播中斷後確認快照先到、重複快照不重播、相同收據重送不扣第二次、略過及快速模式、連點防重送、背景返回不補播、兩人共用輪盤、8 秒未知結果暫停後用同一收據確認。截圖存 artifacts/round-presentation。`test:motion` 的拉霸 fixture 使用同一 presenter 檢查滾動中的現行素材，不保留舊滑入動畫。
