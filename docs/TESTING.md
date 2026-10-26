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
| 遊戲設定 | test_game_settings、test_bet_limits、test_payouts、test_fairness |
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

牌桌首屏回歸由 `tests/browser/layout.cjs` 載入 `table-controls.cjs`：驗證標題列離桌確認、說明對話框、骰寶／輪盤在深度捲動與慢回應期間保留底部操作列、空押注、選號及清除後確認鍵都留在同一位置，且只有一個確認鍵、重新同步的 44px 觸控範圍，以及拉霸錯誤提示保持在視窗內。射龍門另測 760／761／800／1000／1024px 斷點；溢出時保存截圖與元素尺寸。測試使用隔離資料庫與合成帳號，延遲情境攔截測試操作回傳錯誤，不接正式服務。

### 現行圖片與一般動畫

`npm run test:motion` 使用隔離帳號與實際畫面產生函式，開啟正常動畫，涵蓋 Chromium／WebKit 手機與桌機共 384 個動畫時間點，六種拉霸符號、六個骰面、連續相同結果、圖片延遲／失敗及恢復，另檢查礦區與爬塔 49 個圖格在每個瀏覽器／裝置組合內不溢出。檢查只有現行圖片、沒有下層舊 SVG，並保存代表截圖。畫面 fixture 不向正式牌局或點數資料寫入假結果。

`test:layout` 同時保存固定元件幾何尺寸，檢查圖片失敗時的現行占位，不再期待舊 SVG 備用圖。HTTP 靜態檔測試確認僅一份樣式、退役路徑回 404，以及圖片指紋、不可變快取與錯誤版本不進快取。`python scripts/check-ui-assets.py` 檢查圖片內容、版本表、素材清單及 CSS 網址一致；換圖時加 `--write` 更新。

### 輪盤／拉霸回執與揭曉

`npm run test:reveal` 在隔離資料庫執行真實操作，涵蓋 Chromium／WebKit 手機與桌機：點擊即轉、停止後才揭曉、1800ms 慢回應與推播中斷後確認快照先到、重複快照不重播、相同收據重送不扣第二次、略過及快速模式、連點防重送、背景返回不補播、兩人共用輪盤、8 秒未知結果暫停後用同一收據確認。截圖存 artifacts/round-presentation。`test:motion` 的拉霸 fixture 使用同一 presenter 檢查滾動中的現行素材，不保留舊滑入動畫。


### 人物牌比例

`test:layout` 透過 `tests/browser/court-checks.cjs` 檢查真實 `card()` 元件：德州自己／對手／公共牌、大老二、21 點、射龍門、紀錄與獨立卡牌共 8 種上下文，28／52／72／140px 牌寬、A～K 全點數與四花色，393／1366px 視窗。Chromium 與 WebKit 各 3,328 組檢查滿版等比人物圖、按牌寬縮放的角標、J 較小花色及無大片白底，並確認每張牌指向自己的圖片；既有全點數裁切測試另檢查角標不被裁掉。

`deck-checks.cjs` 另在獨立頁面確認 52 張圖片皆可解碼、牌碼與花色各有獨立圖片、只準備牌局時不預載整副、只顯示兩張時僅取兩張，以及未公開牌面不產生圖片網址。它會保存整副與手機八張的實際元件截圖。HTTP 測試另逐張驗證 52 個路徑與已退役的三個舊路徑。

### 共用下注上限

`test_bet_limits.py` 涵蓋預設／自訂值、越權與格式拒絕、合計上限、六人輪盤／骰寶最高派彩守恆、各遊戲初注、21 點加倍、射龍門擔保、局中快照與舊局相容、過期設定拒絕且不扣點、收據重送，以及莊家備付只在更高上限時處理。德州不建立額外莊家或全押限制。

`npm run test:limits` 啟動隔離資料庫，在 Chromium／WebKit 的手機與桌機實際操作管理員預覽／儲存，再檢查輪盤、骰寶、拉霸、21 點各 10,000 點的送出 payload、超額押注阻擋、每次一筆請求，以及設定推播後同頁輸入框上限更新。拒絕回應以測試攔截器產生，不扣實際玩家點數。截圖與結果在 artifacts/bet-limit-browser，CI 同步執行。

### 牌面顯示與可讀性

`npm run test:cards` 使用隔離資料庫、合成帳號與真正的 `card()`／牌桌產生函式，在 Chromium／WebKit 的手機／桌機檢查：照片延遲與失敗只顯示素色底及正確角標、上一張照片晚到不覆蓋新牌、固定尺寸不跳動，及預設／翡翠／酒紅牌背在五款遊戲、牌堆與兩個動畫層一致。另測 21 點兩到五張、1／2／4 手分牌共 96 個版面，以及百家樂雙邊三張牌在八個視窗的邊界。截圖與資料在 artifacts/cards，CI 一併執行。

既有整副牌與牌面展示截圖會等共用解碼狀態完成，再取圖；靜態牌面 fixture 暫停即時更新，避免伺服器推播移除正在驗收的測試區塊。輪盤位移取樣以動畫畫面同步，仍要求兩次取樣真正移動，沒有取消或放寬該斷言。

### 牌桌操作旅程

`npm run test:journeys` 使用隔離 SQLite、合成帳號與 Chromium／WebKit 手機／桌機，實際操作：唯一且有文字的離桌入口、房主管理選單、取消／Escape／預設安全焦點、回大廳及跨頁回桌不送離桌、成功離桌回大廳與等待桌退回全額帶入、慢回應期間連結／程式／hash 導航保留收據與按鈕位置、原收據重送不改資金、拒絕離桌不換頁、舊確認框不套用到別桌、結果未知的離桌收據稍後確認與房主結束回大廳，以及多人 21 點局中離桌停牌／結算釋放座位。局中離桌與點數均以真實測試 API 結算，不改測試引擎結果。CI 執行並保存失敗診斷於 artifacts/table-ux。

### 補給與 Android

`npm run test:rewards` 檢查四個手機／桌機引擎組合的補給入口、五項手機導航、每日／每小時領取、任務進度推播／領取、原收據重送、重載深層連結與收藏入口。重載前先隔離上一份文件的背景診斷，避免 WebKit 把卸載中的診斷 fetch 當作新頁面的例外。Android workflow 執行 [App 驗證](../mobile/nantuan_app/README.md)，使用模擬器及獨立資料庫，完全不接正式遊戲資料。

Android 原生排版：`tests/android/adaptive-layout.cjs` 只允許模擬器，檢查五種顯示尺寸、手勢／三鍵導覽、鍵盤關閉後視口恢復、大字體與整頁水平捲動，保存原生與 WebView 截圖、底部白帶像素量測及尺寸 JSON。清理失敗不覆蓋原始錯誤；模擬器結果不代表每個手機品牌。

### 釣魚雙模式

可選負載量測：從根目錄執行 `python scripts/bench-fishing.py`，`FISH_FAST=1` 切快炮。程式啟隔離loopback服務、限制單核心，建立20個合成帳號與40條SSE，送400批／800發後核對扣款流水及未結算數，結果存忽略的artifacts目錄；不碰正式服務。數值代表本機測試條件，不包含Cloudflare或行動網路。

`python -m unittest tests.python.test_fishing -v` 包含新張力按鍵／滑桿成功、過緊／過鬆失敗、即時入帳且重送不重複、魚餌精力與非法魚種、v2回執相容及舊畫面不扣點、特殊魚總倍率條件派彩與多人搶同魚／連鎖只結算一次，並保留原經典竿／舊可領竿、FIFO、批次、餘額、停權及20人並行驗證。

`npm run test:fishing` 在Chromium／WebKit手機／桌機，以實際按住放開、原生滑桿拖曳完成魚獲；檢查重載、即時點數、魚獲展示不多拋一竿、共享魚群與砲台座標、連發停止、遺失回應原回執核對、慢回應不補射、背景恢復不續射。另驗證八種尺寸的全畫面、無遮擋／溢出、主按鈕尺寸，透過瀏覽器performance時間戳核對30／20fps上限。輸出在 `artifacts/fishing/browser`，不使用正式帳號。結果不代表所有廠牌實體手機。

`test_gate_protection.py` 獨立枚舉小牌靴的所有排列與保護結果，核對命中率、撞柱率、派彩及點數守恆，並涵蓋 0／50／100% 與門檻邊界、連續柱牌消耗、歷史局相容、設定遷移、局中快照及重送不重扣。`test:layout` 的 `gate-protection-checks.cjs` 在隔離服務測試管理員欄位與預覽，以及手機／桌面 Chromium、WebKit 的保護資訊、作廋牌與機率顯示。


漁港素材服務測試檢查透明圖集、總體積預算、版本指紋快取與拒絕錯誤路徑；新增腳本使用版本查詢碼，HTML保持重新驗證。

黃金魚場火力測試：精確枚舉Binomial分布核對10／100／1,000點的捕獲機率單調增加與95%條件期望；檢查重擊只捕獲／入帳一次、管理員上限與已接受快照、雷射／冰凍獨立冷卻、四角砲台座位遷移及v3已付款砲彈。瀏覽器以三檔火力各發一發，核對cost、power與雷射彈速快照；負載腳本可加`FISH_STAKE=1000`量測重炮，合成錢包由測試資料庫注資。
