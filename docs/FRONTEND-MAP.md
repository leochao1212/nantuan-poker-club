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
  S --> R["#collection 任務／收藏／特效"]
  S --> W["#wallet 轉帳與紀錄"]
  S --> P["#profile 個人設定／名片／資金"]
  S --> AD["#admin 管理後台"]
  L --> G["#table/:id 同頁牌桌"]
  G --> H["紀錄／重播 dialog"]
  G --> V["聊天／語音 dialog"]
~~~

/ledger 是舊記帳入口，使用 static/ledger.html、ledger.js、ledger.css。static/app.js 與 style.css 是歷史檔案；目前線上首頁入口是 index.html → game.js，不能只改 app.js 就預期全站改版。

## 頁面到檔案

| 頁面／區塊 | 主要函式／模組 | 主要樣式 |
| --- | --- | --- |
| 殼層、登入、大廳、排行、成員 | game.js：shell、renderAuth、lobbyView、statsView、membersView | casino.css、ui.css、night.css |
| 德州牌桌與下注鍵盤 | game.js：tableView、actionControls、bindTable、openBetKeypad | casino.css、night.css |
| 大老二／21 點／輪盤 | arcade.js：table、controls、blackjackBoard、blackjackBets | arcade.css、night.css |
| 拉霸／骰寶／射龍門／風險小遊戲 | bonus.js：board、controls、roundSettings、bindSettings | arcade.css、night.css |
| 台灣麻將 | mahjong.js | mahjong.css、night.css |
| 會所、個人檔案、公開名片 | profile.js：ClubIncome、ClubProfile、ClubMember、ClubStaff | profile.css、night.css |
| 會所圖與員工 | clubhouse-scene.js：ClubhouseScene | clubhouse-scene.css、night.css |
| 任務、外觀收藏與動效 | club.js | effects.css、arcade.css、night.css |
| 私人包廂、重播、診斷 | features.js | features.css、night.css |
| 全域聊天與語音 | social.js、voice-worklet.js | ui.css、night.css |
| 管理帳號、籌碼 | admin.js | casino.css、profile.css、night.css |
| 遊戲設定與派彩說明 | game-settings.js | game-settings.css |
| 點數轉帳 | transfers.js | transfers.css、night.css |
| 發牌與輪盤動畫 | dealer.js、arcade-motion.js | arcade.css、casino.css、night.css |

## CSS 載入順序

index.html 的順序是 casino → ui → mahjong → arcade → transfers → profile → effects → features → clubhouse-scene → night → game-settings。night.css 是目前全站整合覆寫層。修改前應用瀏覽器 computed styles 查實際規則來源，不能只讀第一個同名 selector。

主要設計 token 在 night.css 的 :root 覆寫；基礎按鈕、表單和牌桌樣式在 casino.css。新增樣式請限制在頁面根 class，避免無條件改 button、small、span 或 details。

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

game.js 混有頁面、狀態、路由、恢復與遊戲控制；CSS 也累積多層覆寫。設計分支宜先挑一頁，保留行為契約，再逐段抽出元件／token；不要一次替換整個前端框架與連線層。

21 點同桌手牌現已常駐顯示，手機先放自己的手牌、莊家和操作，再接同桌手牌。會所手機以標題、建築、升級入口分區。一般牌桌仍留在同一頁，不另開獨立桌頁視窗。
