# 專案結構與整理原則

更新：2026-10-24。此文件區分目前程式、開發工具與歷史資料，避免再從舊副本修改或部署。

## 唯一程式來源

`github-collaboration/` 是 Git 程式庫。`main` 是已合併基準，功能和修正透過分支／PR 整合；正式更新另外由 Deploy production 手動觸發。

| 位置 | 責任 |
| --- | --- |
| 根目錄 `server.py`、其餘執行用 `.py` | HTTP、交易、遊戲引擎、帳號、語音、備份與管理工具 |
| 根目錄 `test_*.py` | Python 回歸測試；保留現有位置，避免破壞 unittest 探索與測試共用 fixture |
| `static/index.html`、`static/game.js` | 現行網站入口與頁面協調 |
| `static/` 其餘 JS／CSS、`assets/` | 遊戲、帳號、會所、聊天、語音及素材；對應關係見 [前端地圖](FRONTEND-MAP.md) |
| `static/ledger.html`、`ledger.js`、`ledger.css` | 仍保留的 `/ledger` 記帳功能；不是廢棄副本 |
| `tests/browser/` | 隔離帳號／資料庫的互動與響應式檢查 |
| `scripts/` | JS／文件檢查與 CI 發布封裝 |
| `ops/` | 受限部署閘道與 runner 安裝工具，並非一般應用入口 |
| `.github/` | CI、手動部署、Issue 與 PR 範本 |
| `docs/` | 架構、資料、API、營運與協作文件 |
| `docs/design-proposals/`、`docs/releases/` | 保留設計決策、素材來源與歷史發布說明 |

目前的 21 個後端執行模組，都可由 `server.py`、`backup.py` 或 `manage_admin.py` 的依賴到達；沒有只憑檔名刪除後端模組。

## 不屬於發布來源的檔案

| 位置 | 處理方式 |
| --- | --- |
| `data/`、備份、`.env`、SQLite／WAL／SHM | 本機或正式資料，不進 Git；不因整理而重設、合併或刪除 |
| `artifacts/`、瀏覽器測試輸出 | 可重建的開發產物，已由 Git 與 Docker 排除；有問題調查價值時保留 |
| `node_modules/`、`__pycache__/` | 可重建的依賴與快取，不列為程式來源、不發布 |
| 桌面外層 `.qa/`、`.codex-remote-attachments/` | 私有營運收據、診斷及原始附件，不上傳 GitHub |
| 桌面外層 `archive/` | 舊工作副本、舊測試、報告與原始啟動器的可復原封存；不作部署來源 |

桌面外層舊 `data/` 保留原地。新的本機啟動器切到本程式庫，以 `github-collaboration/data/` 作為預設開發資料位置，不把舊資料匯入，也不連正式資料庫。

## 本次移除的內容

- `static/app.js`、`static/style.css`：現行首頁與 `/ledger` 均未引用，屬早期前端副本。從程式和公開白名單移除，內容仍可由 Git 歷史還原。
- 快取測試改驗證現行 `game.js`，並確認兩個退役 URL 回 404；未刪除任何 Python 測試檔。
- 更新 README 與架構文件中過期的入口、檔案數和 CI/CD 狀態。

歷史雜湊 `source-baseline.json` 明確保留為 2026-10-23 交接快照。現在版本的雜湊應以該 Git 提交的 CI `release.json` 為準，不能用舊快照驗證新版本。

## 後續整理邊界

先找頁面引用、Python import、HTTP 白名單、Docker COPY、發布腳本和測試 fixture，再判斷是否移除。設計圖、生成提示詞、發布收據與測試不因「不是執行檔」就視為垃圾。

本次不搬動後端套件或合併大型 CSS。這些會牽動 import、樣式權重、測試及部署閘道，應以獨立變更處理，避免讓檔案整理同時改變遊戲行為。
