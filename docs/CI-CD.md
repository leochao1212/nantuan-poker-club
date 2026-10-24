# CI/CD：自動檢查、建置與手動部署

## 使用方式

1. 開 PR：Checks 自動執行完整 Python 回歸、JS 語法、文件連結、雙人 21 點／會所操作，以及 Chromium 和 WebKit 的手機／桌面排版檢查。失敗時在 Actions 下載 synthetic-browser-diagnostics 截圖及日誌。
2. 合併 main：上述檢查全部成功後才建置 Docker。release-完整SHA artifact 保存 image.tar.gz、source.tar.gz、release.json，保留 7 天。只有程式與靜態素材，沒有資料庫或 .env。
3. 更新網站：GitHub → Actions → Deploy production → Run workflow，選 main。工作會等待同一提交的 Checks/build 成功，再呼叫部署端。不是每次 push 自動更新。
4. 過期封裝：重新執行 main 的 Checks，再按 Deploy production。main 在等待中更新時，本次部署會拒絕，需對最新 main 重跑。

## 部署保護

- 執行程式 [deploy.py](../ops/deploy.py) 是主機上 root 擁有的受信任閘道；部署 workflow 不 checkout 程式、不執行 PR 中的腳本。
- 主機再次向 GitHub 核對執行中的 workflow_dispatch、main SHA、成功的 Checks 執行及 artifact 名稱。只讀取該次工作的短效 GITHUB_TOKEN，不保存 PAT。
- 下載驗證 SHA256，拒絕壓縮包路徑穿越與連結，檢查映像 ID 與 commit label，先啟動不掛正式資料的候選容器。
- 排空時建立 120 秒租約、持續續期；拒絕新桌與新手，既有行動、結算、離桌、同一 operation_id 重送仍可完成。資料庫觸發器亦保護升級前的舊服務。10 分鐘仍未打完則取消，恢復開局。
- 備份舊 source／image／SQLite，保留正式 Compose、.env 與資料卷。切換使用已測試的映像，不在正式主機重新建置。
- 檢查來源雜湊、HTTP、私有 API 登入保護、SQLite 完整性、帳號／歷史／操作紀錄數與外網實際內容。
- 失敗回到舊映像與 source；**不拿舊資料庫覆蓋目前資料**。結構不相容的資料移轉應另行設計，不能靠舊 DB 回復。
- 同時只允許一筆部署；完成的 run ID 有收據，重複呼叫不再部署。取消／失敗會解除排空；程序突然消失時租約最多 120 秒後失效。

## 部署 runner 的安裝範圍與維護

目標是 leoserver 現有主機。新增 nantuan-ci 系統帳號及 nantuan-deploy 專用 runner，作為 systemd 常駐服務；重的測試和建置留在 GitHub-hosted runner。

runner 不加入 docker 群組，不能讀 leoserver 私有家目錄及正式 .env。它只能透過受限 sudo，以 leoserver 身分、不帶命令列參數執行 /usr/local/lib/nantuan/deploy.py；不開放任意 sudo 或 root shell。部署閘道本身由 root 擁有，runner 不能修改。runner 服務限制記憶體／CPU，使用私有暫存目錄。GitHub 官方提醒自託管 runner 可能被工作流程程式持久入侵，因此不能把一般 PR 測試搬到這台機器；受限閘道必須獨立維護。

參考：[GitHub runner 安全性](https://docs.github.com/en/actions/reference/security/secure-use)、[Linux runner 服務](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application?platform=linux)。

主機閘道由擁有者用既有 SSH 個別安裝／更新，不讓應用程式的部署自行覆寫權限規則。註冊只使用 GitHub API 產生的一次性 runner registration token。

擁有者已於 2026-10-24 確認此安裝範圍；主機已安裝 runner 2.338.1，並驗證 Docker／任意 sudo／正式環境檔讀取均被拒絕。安裝來源為 [install_runner.py](../ops/install_runner.py)，註冊 token 由標準輸入傳入。完成主機安裝與權限驗證後，才把 repository variable PRODUCTION_DEPLOY_ENABLED 設為 true。未開啟時，Deploy production 會明確顯示尚未設定，不排入離線 runner 無限等待。

## 正式環境與回復

- 正式來源：main。Compose 和 .env 沿用主機設定，不能覆蓋為 repo 的開發版 docker-compose.yml。
- 備份：~/backups/boyband-poker/ci-RUN_ID/。
- 舊映像：boyband-poker:rollback-RUN_ID。
- 部署收據／鎖：~/.local/state/nantuan-deploy/。
- 閘道與 runner 的更新需主機管理者操作，應用程式 PR 不會改動主機上的受信任副本。
- 停用部署：將 PRODUCTION_DEPLOY_ENABLED 改為 false；CI 仍會測試與產出 main 封裝。

本版 CI/CD 測試包含部署授權拒絕、封裝竄改／連結拒絕、跨主機下載不轉送 token、排空與租約過期、重送不重複扣點，以及回復舊程式仍保留最新資料庫。


### 擁有者重新安裝／更新

用既有 SSH 上傳審查過的 ops/install_runner.py 與 ops/deploy.py 到同一個私有暫存目錄。從 GitHub 官方 actions/runner release 取得 Linux x64 封裝並核對其 SHA256；放在 ~/.cache/nantuan-runner-VERSION.tar.gz。以 sudo python3 install_runner.py 執行，stdin 是包含 token、version、digest 的 JSON（token 使用一次性 runner registration token）。不要把 token 寫進 repo 或 shell 歷史。既有 runner 會檢查 repo 是否相同；閘道副本固定 root 擁有。首次安裝後若更改 service drop-in，需要 systemctl restart 對應 runner 服務才套用新限制，且應先確認沒有部署正在執行。

Docker 封裝以整個壓縮檔的 SHA256 作為傳輸完整性依據；classic/containerd 儲存可能顯示不同本機 ID，匯入後從固定 SHA tag 重新核對版本、linux/amd64 平台及全部來源檔，收據同時記錄建置端與部署端映像 ID。
