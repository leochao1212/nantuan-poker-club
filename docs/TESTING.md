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

`npm run test:cards` 使用隔離資料庫、合成帳號與真正的 `card()`／牌桌產生函式，在 Chromium／WebKit 的手機／桌機檢查：照片延遲與失敗只顯示素色底及正確角標、上一張照片晚到不覆蓋新牌、固定尺寸不跳動，及預設／翡翠／酒紅牌背在五款遊戲、牌堆與兩個動畫層一致。另測 21 點兩到五張、1／2／4 手分牌共144個版面，以及百家樂雙邊三張牌在12個視窗的邊界。截圖與資料在 artifacts/cards，CI 一併執行。

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

黃金魚場測試：有理數核對各炮價、倍率及3／5次寶藏的條件期望；檢查亂數邊界、連鎖唯一、技能庫存／重送／回滾、寶藏擁有人與不可變池快照、v3／v4已付款炮彈及v2–v4完成回執。瀏覽器測試三檔炮價、雷射幾何、丟失回覆重送、背景停射、8種視窗的可點區、30／20fps預算；以隔離資料庫插入ready寶藏，再走真實HTTP開箱，核對斷線恢復與唯一入帳。負載腳本`FISH_FAST=1 FISH_STAKE=1000`以20人／40SSE／800發量測，不連正式資料庫。


捕魚v6增加旋轉碰撞／凍結、炮價彈速與網徑、雷射連鎖總期望及唯一派彩、動態Boss捕獲時倍率、分房場景驗證。`npm run test:fishing`先執行[fishing-stream](../tests/browser/fishing-stream.cjs)假時鐘測試，驗證無事件重建、舊generation隔離、背景停射／回來不續射與完整清理；再跑真瀏覽器，包含40秒座位租約到期後重入、主動觀戰後可入座、同一魚場更換炮台圖示。

[二十一點公平性測試](../tests/python/test_blackjack_fairness.py)窮舉六副牌全部兩張組合，驗證4.74895%自然Blackjack基準；檢查安全亂數洗牌入口、依座位逐輪發牌、同牌靴延續、三張21點分類與籌碼守恆。


射龍門v4由[test_gate_refund.py](../tests/python/test_gate_refund.py)枚舉所有小牌靴排列及0／50／100%保護，核對實際柱牌率不變、保護即零扣款、只耗一張牌、普通／對子扣款免除、既有命中倍率與命中率不變、籌碼守恆及公開觸發者。既有v3補牌測試保留以驗證局中／歷史相容；回執測試驗證v4重送不重抽且profit=0。`LAYOUT_ONLY=gate,admin,blackjack`可只跑相關手機／桌機版面，包含姓名與免除金額提示。二十一點另驗證六副牌十點牌密度、20點後取牌和五張21點不算Blackjack、玩家自然Blackjack優先。


[test_blackjack_benefits.py](../tests/python/test_blackjack_benefits.py)驗證0／邊界／100%優待、同牌序與守恆、自然Blackjack例外、加倍／分牌逐手退注、舊快照、移轉只啟用一次、後台記錄及回執重送／離桌入帳。瀏覽器layout的admin／blackjack檢查覆蓋三個快捷設定、自訂、預覽取消、填預設後事件重綁、牌桌優待與逐手返還。可從根目錄執行[配對模擬](../scripts/bench-blackjack-benefits.py)，僅使用固定種子的合成牌局與虛擬點數，無資料庫或網路，結果存忽略的artifacts。

捕魚完整循環回歸另驗證每日補給的台灣午夜界線、同編號跨日重播／新編號領新一天、多人並發只發一份、故障回滾、停權與未知欄位拒絕、戰報所有權／連鎖去重／索引有界查詢。`npm run test:fishing`新增[fishing-bonus](../tests/browser/fishing-bonus.cjs)真瀏覽器延遲回應測試；手機／電腦實測補給已提交後回應遺失，再以原回執確認、不再增庫存，並檢查戰報在320px／橫向／桌機不溢出且按鈕可操作。測試均用合成資料。

張力動畫回歸：[fishing-tension](../tests/browser/fishing-tension.cjs)使用實際呈現模組與假時鐘，檢查50ms內插值、過期預演上限、伺服器校正不瞬移、60／20Hz HUD與30／20fps Canvas預算、背景取消RAF、換竿重設和網路未回時立即反映按住／放開。真瀏覽器以MutationObserver量測實際按鍵／滑桿釣獲期間的指針transform更新，要求達到瀏覽器實際可用幀率（上限60Hz）的72%以上且不超過66Hz，避免將瀏覽器背景／省電節流誤判為動畫缺陷；不把合成環境幀率當作所有實體手機的保證。

桌機放大牌面回歸另檢查1024／1366／1920px的大老二5張與13張手牌（兩引擎共12個版面）、13張在正常桌機寬度完整展開、至少40px牌角曝光、最後一張可選、五張桌面牌不溢出，以及實際牌數樣式符合CSP。牌桌版面測試驗證桌機德州公共牌／手牌放大而不與底池／其他座位重疊、手機仍為原尺寸。`CARDS_ENGINE=chromium|webkit`及`CARDS_DEVICE=phone|desktop`可縮小本機卡牌驗證範圍，CI預設全跑。

銀行：`python -m unittest tests.python.test_bank -v` 與 `npm run test:bank`。測試整數單利／零頭、調息分段、貸款快照、並行重送、失敗回滾、取整利息上限，以及手機／桌機存提借還、遺失回應後重載、輸入焦點與管理員條件版本鎖。參見 [銀行規格](BANK.md)。

釣魚效能：30／20fps Canvas 採相位累積，抖動 RAF 回歸避免漏幀；獨立魚場圖層維持原裁切與座標。原生瀏覽器測試換場景時驗證圖片解碼，允許瀏覽器從快取載入。量測環境、數字及限制見 [順暢度紀錄](design-proposals/fishing-performance-bank-20261027.md)。
