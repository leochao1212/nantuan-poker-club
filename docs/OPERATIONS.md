# 開發、部署與營運交接

## 2026-11-03 穩定性與操作改善

- 保留原 Tailscale 工作區及正式網路綁定。這輪不改伺服器管理網路。
- 寫入 FIFO 最多容納 64 筆（含執行中），等候超過 3 秒會在開始交易前拒絕；HTTP 回 503，前端繼續使用原操作回執確認。`/api/health` 檢查資料庫可讀、背景維護最近 30 秒內有成功完成，並提供匿名佇列統計。Docker healthcheck 改用此端點。
- 行情來源工作使用同一份 `market_data.PROVIDERS` 清單，包含 `TW_CALENDAR`，避免排程與來源定義不同步。股票來源延遲與成交規則不變。
- 行情頁切換標的或離開時中止過期讀取；正常每 5 秒同步，尚有委託每 2 秒同步，失敗退避至最多 30 秒。來源時間與網站同步時間分開標示，背景分頁停止自動讀取；保留輸入與未確認操作。
- 銀行、樂透、交易、管理程式按頁面載入，載入失敗可重試。部署公開資源比對也包含延遲載入模組。
- 射龍門的機率與派彩計算收進可展開明細；保護與下注最大得失仍在原處。會所待領收益移到場景前，派遣捷徑直接捲動到既有團隊區。
- 固定部署核對新增現貨／合約委託、做空／合約持倉與操作回執。允許未完成委託正常成交，禁止已完成歷史改寫、移除或轉移擁有人。

### 同機備份演練與健康監控

依站長決定，備份保留在原設備，未設定異機傳送。

`python3 ops/verify_restore.py /absolute/path/production.sqlite3 --temp-dir /existing/backup/directory`

只讀備份，還原到新的暫存檔，檢查完整性、主要資料表與非負錢包；結束後刪除本工具產生的暫存副本。正式 DB 不會被覆蓋。此為資料還原驗證，不等於主機全毀後的完整服務重建演練。

`python3 ops/service_health.py` 在伺服器檢查容器、本機 API 與公開入口，輸出 JSON 並以退出碼表示成功與否。`--watch` 每分鐘檢查，狀態改變及連續三次失敗輸出警示；不自動重啟、不傳送外部通知。需另由部署者安裝為常駐程序才會持續監控。

### 可重跑多人量測

`python scripts/bench-multiplayer.py --players 10 20 40`

啟動獨立 loopback 服務與臨時資料庫，建立多桌、SSE 訂閱，並行開局與 presence／銀行讀取。輸出延遲中位數、P95、全桌推播最慢值及失敗數。不能指定正式網址；結果不包含外網、語音、手機繪製，也不應直接當作正式服務容量承諾。

## 目前拓撲

正式入口為 Cloudflare HTTPS／WSS → Tunnel → 單台主機 Docker → Python／SQLite。正式網址為 https://poker.leoapi.dpdns.org/ 。

私有主機位址、SSH 憑證、Tunnel token、註冊邀請碼與管理員密碼由專案擁有者個別管理；本 repo 只給程式和開發環境。協作者不需要正式 DB 就能設計頁面。

## 開發 Compose 與正式環境的差異

本 repo 的 docker-compose.yml 使用開發專用 Compose project、映像與 managed volume，僅綁 127.0.0.1。現有正式服務使用不同名稱、既有 external volume 與主機網路綁定；不要把開發 Compose 整份覆蓋過去。

~~~sh
cp .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 poker
~~~

PowerShell 可用 Copy-Item .env.example .env。後端本機直接啟動時不會自動讀 .env，須在 shell 設環境變數；Compose 才自動代入 .env。

| 環境變數 | 用途 |
| --- | --- |
| POKER_DB | SQLite 路徑，容器用 /data/poker.sqlite3 |
| POKER_PORT | 開發 host 連接埠 |
| POKER_SECURE_COOKIE | 正式 HTTPS 為 1，本機 HTTP 為 0 |
| POKER_PUBLIC_ORIGIN | 正式來源驗證；本機可空 |
| POKER_REQUIRE_INVITE | 正式註冊要求邀請碼時設 1 |
| TZ | 容器顯示時區 Asia/Taipei |

POKER_TURN_SERVERS 是舊訊號相容設定，不是現行 PCM-WSS 語音的必要條件。WSS proxy 需允許 WebSocket upgrade，SSE 不應 buffer 或 cache。

Dockerfile 採非 root、唯讀檔案系統，資料與備份須寫入 /data。Docker build 使用 .dockerignore allowlist；新增後端執行檔時需同時更新 Dockerfile 和 allowlist。

## 備份與更新步驟

1. 確認本機測試、JS 檢查、受影響頁面與操作流程通過。
2. 核對部署來源與目前容器版本，保留舊 source／image。
3. 使用 SQLite Backup API 建立一致快照。可在目標容器執行 python backup.py；它使用當前 POKER_DB。
4. 遊戲仍在進行時先建新映像，等所有進行中手牌結束再切換；不要中斷下注或重設房間。
5. 啟動後檢查 health、54 個原始執行檔的版本基準（新增檔案要更新清單）、HTTPS 資源版本與登入保護。
6. 檢查資料庫 integrity_check、帳號／歷史保留、轉帳配對、餘額非負與總點數守恆。
7. 玩家等當手結束後重新整理。

GitHub Actions 的檢查及版本化封裝自動執行；正式部署採手動按鈕，先完成專用 runner 與受限閘道設定。流程與使用方式見 [CI/CD](CI-CD.md)。

## 回滾

先保存新版本上線後的資料快照，再回到舊映像。不要直接拿更新前 DB 覆蓋仍有新交易的資料卷，否則會遺失玩家後續操作。若資料 schema 已變動，需先確認舊程式相容性或制定 forward fix。

## 連線問題的觀測

server 日誌含 request_id、receive／queue／db_wait／process／snapshot／encode 時間及 stream_open／close／error。前端連線診斷可下載白名單報告。這些營運輸出可能含帳號識別，分享前只保留必要統計。

觀察 CPU、記憶體、SSE 最後更新、HTTP P95、資料庫等待與音訊佇列。高 CPU 不等於一定是抽牌或 Python 運算；先區分公開模型重算、讀鎖、網路回傳、裝飾動畫和手機背景恢復。

## 共用下注上限

管理員 → 遊戲設定 → 共用下注上限，可調整「每人每局下注上限（點）」，預設 10,000，可設定 20–1,000,000 的整數。沿用設定預覽、變更原因、版本衝突檢查與重送收據；一般玩家沒有修改權限。

輪盤／骰寶以每人所有押注的合計計算；21 點限制初始下注，加倍與分牌仍依原玩法追加；射龍門另保留撞柱最大扣款擔保。大老二適用每張牌底分上限，實際結算仍依剩牌加倍；德州全押、麻將底台沿用各自桌規。

新值從下一局生效，進行中的局使用開局快照。設定變更會推播至大廳與牌桌；舊畫面若尚未看到新版本，開局請求會先要求同步，不扣點或發牌。早期缺少上限欄位的手牌仍沿用 1,000。既有房間的固定底分若高於調低後的上限，需改開符合上限的新桌。

提高上限時，電腦莊家的虛擬備付額在開桌／下一局前按公開賠率與滿桌人數補足，僅增加房間內部的 bank，不改玩家錢包、桌上籌碼或機率。房間記錄歷來已備付的最高上限；重複送出、或調低再調回同一上限，不會藉此重補已輸掉的備付額。原有最大派彩不足檢查繼續有效。

## 步步為營：持久化、部署與籌碼

- blocade_rooms 保存 9×9 棋盤、2／4 人座位、牆壁、回合與機器人，blocade_entries 保存每人入場／派彩，blocade_operations 保存重送回執。只新增資料表，不改寫既有玩家錢包或牌局。
- 機器人按同一合法走法計算最短路徑，每個維護週期最多推進 2 個機器人回合，輪流處理最久未更新的桌；不讀玩家的本機操作預覽。系統出資／收回金額記在結算棋桌。
- 每回合 45 秒，前 2 次連續逾時代走最短路，第 3 次認輸。開局前 15 分鐘取消全退，對局 30 分鐘或 400 回合和局全退。所有點數為站內虛擬籌碼。
- 沿用 deploy_pause_until：封鎖新開桌／加入／開始，現有棋桌暫停計時，解除後補回暫停時間。棋桌不需等 30 分鐘才部署；資料持久化後接續。意外重啟也保留棋局並重新給當前玩家 45 秒，避免停機造成自動認輸。
- 固定部署稽核會核對新棋桌、原入場資料、操作回執與已完成對局不可被修改，容許正常未結算 → 結算。備份仍用完整 SQLite Backup API，位置沿用原機。
- 驗證：`python -m unittest tests.python.test_blocade -v`、`npm run test:blocade`。瀏覽器測試只使用臨時 DB、合成帳號，包含 Chromium／WebKit 的手機、桌機、回執重送、雙人與四人、機器人輪流行動與棋盤預覽。
