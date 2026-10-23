# 系統架構

更新：2026-10-23。本文件以此程式庫的程式為準，取代原先混合歷次更新的交接說明。

## 系統邊界

這是一個單程序、標準庫 Python 網站，搭配原生 JavaScript 單頁介面與 SQLite WAL。Docker 是執行封裝；Cloudflare Tunnel 提供正式 HTTPS/WSS 入口。GitHub 是協作與檢查入口，尚未接上自動正式部署。

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
static/                   不需打包的網站與素材
test_*.py                 40 個測試檔
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
