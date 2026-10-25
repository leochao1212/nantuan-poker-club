# 開發、部署與營運交接

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
