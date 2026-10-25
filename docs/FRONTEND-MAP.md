# 前端與頁面地圖

## 導航樹

~~~mermaid
flowchart TD
  A["登入／註冊"] --> S["shell：共用導航、錢包、連線、語音"]
  S --> L["#lobby 遊戲大廳／牌桌"]
  S --> T["#stats 排行"]
  S --> M["#members 成員"]
  M --> MP["#member/:id 公開名片與資金水位"]
  S --> C["#clubhouse 會所／升級／員工"]
  S --> RW["#rewards 補給與今日任務"]
  RW --> R["#collection 外觀收藏／特效"]
  S --> W["#wallet 轉帳與紀錄"]
  S --> P["#profile 個人設定／名片／資金"]
  S --> AD["#admin 管理後台"]
  L --> G["#table/:id 同頁牌桌"]
  G --> H["紀錄／重播 dialog"]
  G --> V["聊天／語音 dialog"]
~~~

/ledger 是仍保留的歷史記帳入口，使用 static/ledger.html、ledger.js、ledger.css。目前線上首頁入口是 index.html → game.js。無任何頁面引用的 static/app.js 與 style.css 已移除，舊內容仍可從 Git 歷史取得；不要把它們重新當成現行入口。

## 頁面到檔案

| 頁面／區塊 | 主要函式／模組 | 主要樣式 |
| --- | --- | --- |
| 殼層、登入、大廳、排行、成員 | game.js：shell、renderAuth、lobbyView、statsView、membersView | night.css |
| 德州牌桌與下注鍵盤 | game.js：tableView、actionControls、bindTable、openBetKeypad | night.css |
| 大老二／21 點／輪盤 | arcade.js：table、controls、blackjackBoard、blackjackBets | night.css |
| 拉霸／骰寶／射龍門／風險小遊戲 | bonus.js：board、controls、roundSettings、bindSettings | night.css |
| 台灣麻將 | mahjong.js | night.css |
| 會所、個人檔案、公開名片 | profile.js：ClubIncome、ClubProfile、ClubMember、ClubStaff | night.css |
| 會所圖與員工 | clubhouse-scene.js：ClubhouseScene | night.css |
| 任務、外觀收藏與動效 | club.js | night.css |
| 私人包廂、重播、診斷 | features.js | night.css |
| 全域聊天與語音 | social.js、voice-worklet.js | night.css |
| 管理帳號、籌碼 | admin.js | night.css |
| 遊戲設定與派彩說明 | game-settings.js | night.css |
| 點數轉帳 | transfers.js | night.css |
| 發牌、靜止輪盤 | dealer.js、arcade-motion.js | night.css |
| 輪盤／拉霸等待、轉動與揭曉 | round-presentation.js：ClubRoundPresentation | night.css |

## 單一樣式來源

遊戲網站只載入 night.css。原先十份分散樣式已合併，清掉重複設定與已退役元件；不要再建立另一層主題覆蓋檔。請在現行元件規則與響應式區段修改，先查 computed styles，並執行手機／桌機回歸。

ui-art.js 統一產生現行圖片元件，只準備目前遊戲需要的圖；CSS 按鈕直接使用現行切片。圖片載入中或失敗使用同主題的文字占位，不會切回舊 SVG。撲克牌保留點數／花色的語意與收藏牌背，麻將由現行精靈圖繪製。ledger.css 專供仍在使用的歷史記帳頁，沒有載入遊戲網站。

## DOM 與互動契約

game.js 的 patchNode 比對 id、data-seat、data-player、data-room、data-action、data-card-key 等識別欄位。這些屬性同時是事件綁定與增量 DOM 身分；改名須同步所有使用處，否則可能清掉輸入、選牌或點擊中的按鈕。

| 契約 | 用途 |
| --- | --- |
| #table-controls、#deal-hand | 共用操作區、開局／確認下注 |
| #round-stake、data-point-step、data-point-preset | 小遊戲與 21 點金額 |
| data-arcade-action、data-action | 遊戲合法動作 |
| data-card-key | 發牌動畫、卡牌節點穩定身分 |
| data-open-upgrades、#clubhouse-upgrades | 會所升級導覽 |
| data-social-toggle、data-global-voice | 聊天與全域語音 |
| data-preserve-open | 更新時保留展開狀態 |

不要在全域 render 時重建 social-root、關閉 AudioContext 或停止音軌。不要因推播直接重置尚未提交的表單草稿。不要以動畫完成時間解鎖遊戲操作；是否可操作由伺服器狀態與 pending receipt 決定。

## 現況與可整理處

game.js 仍包含頁面、狀態、路由、恢復與遊戲控制；樣式已統一為 night.css。後續協作宜一次處理一個現行元件，保留行為契約，直接修改既有規則並執行回歸，避免繼續追加覆蓋層。

21 點同桌手牌現已常駐顯示，手機先放自己的手牌、莊家和操作，再接同桌手牌。會所手機以標題、建築、升級入口分區。一般牌桌仍留在同一頁，不另開獨立桌頁視窗。

## 轉動與揭曉

round-presentation.js 只管理演出，game.js 仍立即處理伺服器回執與點數狀態。開始操作先建立等待演出；HTTP、推播、確認快照進同一 prepare，已確認的同一局只揭曉一次。輪盤約 4.5 秒、拉霸約 3.3 秒，未知結果持續等待，8 秒後暫停循環並保留確認狀態；收到結果再停止。快速演出與略過只影響本機呈現，不建立交易。分頁隱藏／離桌取消演出；回來依伺服器狀態顯示，不補播已退休的操作。

## Android 用戶端

[Flutter Android App](../mobile/nantuan_app/README.md) 共用本網站與後端。APK 建置使用獨立 Android workflow，不加入網站 Docker 映像；App 的帳號、遊戲規則與點數仍由相同服務管理。
