# 楠團牌室 · Nantuan Poker Club

私人多人網頁遊戲與會所。這個程式庫供 leochao1212 與 livangvang 協作程式、介面和頁面設計。

唯一正式程式目錄是本程式庫；桌面外層的歷史修補副本與測試報告不屬於發布來源。目錄責任與封存原則見 [專案結構](docs/PROJECT-STRUCTURE.md)。初次交接的歷史雜湊保留在 [2026-10-23 來源基準](docs/source-baseline.json)，它不是目前版本清單；目前發布內容以 Git 提交與 CI release manifest 為準。

## 先讀這裡

| 想做的事 | 文件 |
| --- | --- |
| 看懂系統、遊戲和即時連線 | [系統架構](docs/ARCHITECTURE.md) |
| 找到頁面對應程式與樣式 | [前端與頁面地圖](docs/FRONTEND-MAP.md) |
| 開始畫頁面、改風格或做響應式 | [設計規格](docs/DESIGN-SYSTEM.md)、[頁面設計工作單](docs/PAGE-DESIGN-BRIEF.md) |
| 理解資料、籌碼與 API | [資料模型](docs/DATA-MODEL.md)、[API 導覽](docs/API.md) |
| 開分支、提交 PR | [協作流程](CONTRIBUTING.md) |
| 檢查牌桌操作與協作互動約定 | [操作流程審查](docs/UX-REVIEW.md) |
| 執行回歸、操作測試 | [測試方法](docs/TESTING.md) |
| Docker、備份與更新 | [部署與營運](docs/OPERATIONS.md)、[CI/CD](docs/CI-CD.md) |
| 圖片、SVG、動畫來源檔 | [素材清單](docs/ASSETS.md) |

## 本機啟動

使用 Python 3.14 作為驗證基準；後端只用標準庫。前端是原生 HTML/CSS/JavaScript，沒有 React、Vite 或打包步驟。

~~~sh
python server.py --host 127.0.0.1 --port 8765
~~~

開啟 http://127.0.0.1:8765 。首次啟動建立本機 data/poker.sqlite3；本機資料與正式服務分開。註冊自己的開發帳號；第一位註冊後可在大廳取得本機邀請碼。不要使用正式帳密測試。

Docker 開發環境：

~~~sh
docker compose up --build -d
docker compose logs -f poker
~~~

本程式庫的 Compose 特別採用開發專用名稱與資料卷，只綁 localhost。它不是既有正式服務的 Compose，不能直接覆蓋正式主機設定。

## 功能範圍

十一款遊戲：德州撲克、大老二、21 點、台灣 16 張麻將、歐式輪盤、百家樂、Dice 骰寶、拉霸、射龍門、尋寶礦區、爬塔。另有錢包轉帳、每日／每小時補給、資金水位、排行榜、個人資料、稱號特效、每日任務、會所收益、員工派遣、好友包廂、重播、文字與語音、管理後台。

只使用遊戲虛擬點數。帳號數不限；牌桌容量依遊戲設定，並非全站只有六個帳號。

會所的營運、金庫及裝潢最高皆為十級；[完整等級、費用與圖片說明](docs/CLUBHOUSE.md)。

## 目前的重要行為

- 大老二每局均由持有梅花 3 的玩家先出，第一手必須包含梅花 3；不沿用上局贏家的先手權。

- UI 僅載入 night.css，圖片直接使用現行素材；ui-art.js 按遊戲準備圖片，不再切換新舊樣式。
- 操作經 HTTP POST，遊戲／大廳狀態經 SSE；語音另走 WSS PCM 中繼，沒有把音訊放進 SQLite。
- 一般牌桌已取消通用「全員準備」步驟。21 點另有每局各自確認下注，最後一人確認即一起發牌。
- 同桌 21 點手牌直接顯示；莊家底牌仍依規則隱藏。
- 切換 App 後會重新同步；短暫離開保留座位 120 秒，回頁面會自動恢復。
- 手機會所的名稱／等級在圖片上方，升級按鈕在圖片下方；不要重新疊回房子上。
- 派彩與部分機率可由管理員設定，開局保存當局設定快照。舊回合按舊快照結算。

## 測試

Python 測試集中在 tests/python/，瀏覽器測試在 tests/browser/；各檔用途與單跑方式見 [測試目錄](tests/README.md)。

~~~sh
python -m unittest discover -s tests/python -t . -v
node scripts/check-js.cjs
~~~

選用的瀏覽器 smoke test：

~~~sh
npm ci
npx playwright install chromium
npm run test:ui
~~~

瀏覽器測試只用臨時 SQLite 與合成帳號。PR 自動檢查，main 通過後建置版本化 Docker 封裝；正式更新由 Actions 的 Deploy production 手動觸發，主機設定完成後啟用。詳見 [CI/CD](docs/CI-CD.md)。

金融功能：[楠團銀行與點數現貨交易所](docs/MARKET.md)。免費股票採每日收盤委託，加密貨幣約十秒更新；美股需在伺服器設定免費行情 Key。所有交易僅使用遊戲點數。
