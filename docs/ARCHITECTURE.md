# 系統架構

更新：2026-10-24。本文件以此程式庫的程式為準，取代原先混合歷次更新的交接說明。

## 系統邊界

這是一個單程序、標準庫 Python 網站，搭配原生 JavaScript 單頁介面與 SQLite WAL。Docker 是執行封裝；Cloudflare Tunnel 提供正式 HTTPS/WSS 入口。GitHub 負責協作、自動測試與版本化映像建置；正式部署由 Actions 手動觸發，受限 runner 驗證同 SHA 的成功檢查後才更新。詳見 [CI/CD](CI-CD.md)。

~~~mermaid
flowchart LR
  B["電腦／手機瀏覽器"] -->|"HTTPS：頁面、API、SSE"| CF["Cloudflare／Tunnel"]
  B -->|"WSS：PCM 音訊"| CF
  CF --> HTTP["server.py：ThreadingHTTPServer"]
  HTTP --> W["WriteQueue：FIFO 寫入"]
  W --> O["online.py：交易與房間"]
  O --> E["四組遊戲規則引擎"]
  O --> D[("SQLite WAL")]
  HTTP --> R["唯讀快照／view_cache"]
  R --> D
  O -->|"commit 後喚醒"| H["realtime.Hub"]
  H -->|"分房間 SSE"| B
  HTTP --> V["voice_transport：有界音訊佇列"]
  V -->|"不寫 DB 的音訊傳送"| B
~~~

## 程式樹與責任

~~~text
server.py                 HTTP、登入、認證、排程、SSE、路由
online.py                 房間交易、操作回執、持久化、結算投影
realtime.py               FIFO WriteQueue、分頻道 Hub、串流替換租約
view_cache.py             有版本的公開唯讀模型快取
poker_engine.py           德州狀態機、座位／籌碼共用工具
arcade_engine.py          大老二、21 點、輪盤
bonus_engine.py           百家樂、拉霸、礦區、爬塔、骰寶、射龍門
mahjong_engine.py         台灣 16 張麻將與底／台結算
game_settings.py          設定驗證、版本快照、派彩／理論指標
wallet.py                 虛擬錢包、補給、入離桌移轉
transfers.py              帳號間點數轉帳
fishing.py                魚簍／圖鑑、歷史回執及舊竿遷移
fishing_gameplay.py       共享魚場、碰撞與單一／連鎖捕獲結算
fishing_tension.py        按鍵／滑桿張力收線、Combo與魚獲分數
clubhouse.py              被動收益、升級、員工、資金水位
rewards.py                任務、商品、裝備
member_accounts.py        暱稱、頭像、密碼／帳號狀態
club_admin.py             管理員權限、點數調整
club_features.py          私人包廂資格、牌局重播
social.py                 文字訊息、語音成員／頻道資格
voice_transport.py        WebSocket 音訊中繼
result_stats.py           歷史結算統計投影
backup.py                 SQLite Backup API
manage_admin.py           由主機操作者建立獨立管理員
static/                   不需打包的網站與素材；night.css 是唯一遊戲樣式，ui-art.js 管理現行圖片
tests/python/test_*.py    後端回歸測試（46 檔，使用套件相對引用）
tests/browser/            瀏覽器互動與排版測試
~~~

## 一次遊戲操作

~~~mermaid
sequenceDiagram
  participant U as 玩家
  participant F as game.js
  participant S as server.py
  participant Q as FIFO／SQLite
  participant E as online＋引擎
  participant P as 其他玩家 SSE
  U->>F: 點確認／下注／出牌
  F->>S: POST：operation_id、revision、手／回合識別
  S->>Q: 排隊並記錄伺服器接收時間
  Q->>E: 驗證資格、回合、餘額、合法動作
  E->>Q: 房間、扣點、結算、回執同筆交易
  Q-->>S: commit
  S->>P: Hub 發布該房間版本
  S-->>F: HTTP 回應與個人狀態
  P-->>F: SSE 也可確認同一 operation_id
  F->>U: 更新畫面，解除等待
~~~

operation_id 是耐久回執，不是一次 HTTP 連線的流水號。回應遺失時必須重用同一編號與相同意圖；不能換號「再下注一次」。回合操作另驗 hand_id／turn_id，避免上一回合的操作落在下一回合。

寫入佇列不負責對外傳送。HTTP 回覆與 SSE 狀態建構在 commit 後的唯讀快照進行，避免慢手機或大量觀戰者阻塞出牌。登入密碼雜湊也在遊戲寫入鎖外預先計算，入鎖後再驗憑證版本。

## 即時與恢復

| 通道 | 用途 | 目前實作 |
| --- | --- | --- |
| HTTP JSON | 明確操作、初始載入、恢復快照 | 原生 fetch，超時後核對原操作 |
| SSE | 大廳與單桌個人狀態 | EventSource，房間 channel 分流 |
| WSS | 語音音訊 | PCM16／16 kHz／每幀 640 samples（40ms） |
| HTTP presence | 可見狀態、座位恢復 | 與遊戲資料快照區分 |

SSE 房間快照節流間距為 20ms，大廳為 500ms；這是合併更新的最小間距，不代表端到端延遲保證。無變更時約 3 秒有 ping，完整快照最長約 15 秒刷新並重新驗證登入。房間、大廳和互動 HTTP 各有讀取並行上限。

前端在 visibility／pagehide／pageshow／online／freeze／resume 等事件收回舊請求與串流。恢復使用新的請求世代，舊回覆不能覆蓋新牌桌。每分頁保留 client 身分，新的 SSE 租約會取代自己的舊連線；不是把短暫收不到推播一律視為登出。

公開模型快取以同筆唯讀交易中的資料表版本作鍵；禁止快取未提交寫入、私牌、合法動作、回執或語音收件匣。不要把它改成所有使用者共用的整張個人快照快取。

## 語音生命週期

social-root 與 AudioWorklet 在 SPA 頁面切換外維持。第一次按頁首語音會加入所在牌桌／大廳，已加入後開控制面板；觀戰者也能加入。進出牌桌不應自動停止目前頻道，只有明確換頻道、離開、登出或失去資格才改變。

目前前端傳聲走 WSS 中繼，並非 WebRTC P2P。social.py 尚保留相容的舊訊號端點，不能因此把 TURN 當作現行語音必要條件。中繼只保留有界記憶體佇列；不保存音檔。

## 部署與擴充限制

目前是一個 Python 程序、一個 SQLite 資料卷和記憶體 Hub。直接起多副本會把 SSE 通知、語音成員連線及 FIFO 寫入順序分散，不能當作無狀態服務水平擴充。若要多節點，需另設共享事件匯流排、持久化策略、語音路由及跨節點回合順序設計。

既有正式服務以 1 CPU／256 MiB 為配置，並非容量承諾。大量使用者前應測 HTTP 操作 P95、SSE 落後、事件迴圈／CPU、資料庫等待與音訊佇列，不只看單次首頁載入。

### 共用下注設定與牌局快照

`game_settings` 的 `limits` 列保存 `max_bet`，與賠率設定共用管理員驗證、版本與 audit。每局的 `game_settings` 快照另攜帶 `bet_limit`／`bet_limit_revision`，不改寫既有賠率 params；舊手牌缺欄位時為 1,000，新預設為 10,000。建立房間與下一局使用目前設定，回合內的押注與 legal actions 使用當局快照。開局的 `expected_bet_limit_revision` 防止以過期提示扣點；前端將上限版本納入推播重繪判斷。

內部虛擬莊家備付在等待狀態、同一個資料庫交易中處理。`bet_limit_funded` 記錄歷來已備付的最高上限，只有更高上限才重新估算，玩家餘額和局中銀行不會因推播或設定修改而變動。

### 漁港

`#fishing` 採全畫面舞台，`fishing.js`管理回執、面板與結果；`fishing-play.js`分開處理錢包請求、控魚輸入與魚場SSE；`fishing-scene.js`繪製第一人稱釣魚和共享魚場。釣具與一般魚沿用圖集，場景與特殊魚改為固定參考版，移除舊場景檔。

`fishing_gameplay.py`處理入場、實際砲彈碰撞與唯一捕獲；`fishing_tension.py`以50ms固定步長處理張力、Combo、斷線與脫鉤。新魚獲原子地記錄圖鑑／結果並直接入帳；舊經典竿與魚簍保留原規則。通訊v5與DB竿version=2分開，舊操作回執仍可重送，舊畫面新操作會被版本檢查阻擋。

共享房間六間×四席、每場18隻魚，座標1000×600；畫面不再旋轉90度，魚體保持比例，點按與伺服器座標互為反函數。新`pricing=cannon-v1`炮彈以stake×倍率派彩，捕獲率分母含連鎖與寶藏期望，舊v3／v4已扣點炮彈保留各自算法。成功捕獲同一交易插入唯一capture、替換魚並記總派彩；零成本連鎖事件附source_id。`fishing_bonus.py`管理獨立寶藏及技能庫存兩表，bonus事件與wallet／operation共同提交；`fishing-bonus.js`只負責16格獎勵盤的結果演出。

魚場SSE頻道`-500-room`與牌桌／大廳分流，最多5Hz共用JSON快照，閒時2秒心跳，客戶端軌跡補間。120ms時鐘僅在有竿、魚場或砲彈活動時加入FIFO；本人錢包立即回應，共享大廳每750ms合併喚醒。發射回應只回錢包與發射統計的partial快照，前端合併原狀態，避免每批重算／重送圖鑑、房間列表與規則；近期砲彈依room／expires_at索引，Canvas30fps、減少動態20fps、手機DPR1.5。背景、斷線、慢確認停止連發，保存原回執，不追補未送砲彈。

完整玩法、公開機率、相容與端點見[漁港規格](FISHING.md)，固定參考見[對照設計](design-proposals/fishing-fixed-references.md)。

### 射龍門撞柱保護（規則 v3）

管理員「遊戲設定 → 射龍門」的 `post_protection_bps` 為 0–10000（0–100%，預設 5000），與既有權限、預覽、版本鎖、操作收據及變更紀錄共用流程。啟動時只為缺少此欄位的設定補入 5000 並遞增版本，不覆蓋自訂 `target_bps` 或其他遊戲。局中快照與已凍結報價不改寫；v1/v2 手牌不啟用保護。

抽中第一張柱牌時才獨立判定保護，成功則公開作廢柱牌，沿原牌靴順序補到非柱牌為止。作廢牌一律消耗並保存在 `protected_discards`，不放回、不重新洗牌；`post_protection_triggered` 記錄是否啟動。驗證下注、最大損失與莊家備付後才抽取保護結果。跳過不抽牌、不扣點；重送沿用原收據，不重抽、不再扣款。

設剩餘牌數 N、柱牌 m、命中牌 w、保護率 r、撞柱扣款倍數 L，保護後撞柱率為 `(m/N) × (1-r)`；命中率為 `w/N + r×m/N×w/(N-m)`。保留原含本金倍率，不以提高命中率為由降低派彩。因此整體理論返還率提高，依本局門柱和剩餘牌不同，可能超過 100%；前端按下注整數取整後的派彩與預期實際總扣款計算並公開。100% 保護時不會撞柱，只需保留一注資金；其他設定仍需普通兩注／對子三注擔保。
