# 協作方式

## 開始前

讀 README、ARCHITECTURE、FRONTEND-MAP 與 PAGE-DESIGN-BRIEF，在自己電腦建立開發資料庫。正式環境的資料、密碼與伺服器權限不經由 GitHub 分享。

## 分支

~~~mermaid
flowchart LR
  M["main：可執行基準"] --> D["design/page-refresh：頁面設計"]
  M --> F["feat/具體功能"]
  M --> X["fix/具體問題"]
  D --> PR["Draft PR：稿件、截圖、討論"]
  F --> PR
  X --> PR
  PR --> R["測試＋擁有者 review"]
  R --> M2["合併 main"]
  M2 --> DEP["擁有者另行部署"]
~~~

main 保存可執行基準。design/page-refresh 是本次頁面設計工作分支；設計者可在該分支逐頁提交，或從最新 main 開 design/頁面名稱的短期分支。多人同時改動同一個 game.js／night.css 前，先在 Issue 註明負責頁面，減少彼此覆蓋。

~~~sh
git fetch origin
git switch design/page-refresh
git pull --ff-only
# 編輯後執行適當檢查
git add <明確檔案>
git commit -m "design: clarify clubhouse upgrade layout"
git push
~~~

不要 force push 別人的分支。主分支的 PR 流程是團隊約定；是否由 GitHub 規則強制執行，以 Settings 的實際設定為準，不把文件當成已啟用的保護規則。

## PR 必填

改了什麼頁面／問題、修改理由、桌機／手機截圖、使用的測試命令與結果、是否動到 DOM 識別、金額、遊戲規則或連線。只驗證 CSS 的修正不必宣稱跑過全套後端測試；修改交易邏輯就要驗證守恆與重送。

Draft PR 可以先放方案與待辦。變成 Ready for review 前應有可操作結果及必要測試。合併不等於部署；此 repo 不含正式主機金鑰，也不設定 push 即上線。

## 機密與素材

不要提交 .env、DB／WAL／SHM、備份、Cookie、登入 token、邀請碼、玩家名單、正式日誌及含真實帳號資料的截圖。測試資料用明確合成帳號。引用外部圖片、字型或套件時記錄來源與使用限制。

新增樣式先以頁面根 class 限定，不跨頁改通用 selector。交付時同步文件與資源版本 query，讓使用者重整能取得新 CSS／JS。
