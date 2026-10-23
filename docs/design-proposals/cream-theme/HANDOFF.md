# 奶油白主題 · 交接說明（給 leochao1212）

這個分支把全站手機與桌機畫面換成「奶油白底＋深綠絨布＋厚金邊」。

## 一、整合狀態（2026-10-24）

- 11 個遊戲封面的精確白名單已套用到 `server.py`，不存在的封面仍回 404。
- 公開 WebP 圖片使用 ETag 重新驗證；內容未變時回 304，避免再次下載圖片。每次都驗證版本，沒有舊圖停留問題。HTML、API、錢包、帳號和即時串流仍禁止快取。
- 已整合射龍門連續牌靴：每桌沿用 52 張牌，剩 13 張以下下一局重洗；倍率與機率依實際餘牌計算，免費略過只消耗兩張門柱。
- 手機德州增加中央資訊與手牌間距，右側頭像移入牌桌邊界；保留已裝備的翡翠／酒紅牌背。
- 第三輪（分支 `design/cream-round3`）：照設計稿再貼近一次，分四批做，每批後獨立審查並修正。幾乎全是 CSS，另有少數 JS 畫面字串（第三節「第三輪 JS 模板」）；後端只有第二節的小修。
  - 提交（依序）：`2805a4f`、`ad8fb39`、`2aa8f62`、`d872c85`、`e539175`、`a91354a`、`5979c28`、`924c78b`（修正 3）、`71379f0`（修正 4）、`6cdf62d`（交接文件）、`f778c8f`（修正 5）。

## 二、後端改了什麼

| 檔案 | 改動 | 為什麼 |
| --- | --- | --- |
| `server.py` 靜態圖白名單 | 多放行 11 個封面：`/assets/covers/(holdem\|big2\|blackjack\|roulette\|baccarat\|slot\|mines\|dice\|tower\|inbetween\|mahjong).webp` | 大廳遊戲封面。刻意列確切檔名、不用萬用字元，不存在的檔名維持 404，不會落到 `read_bytes()` 變成 500 |
| `server.py` `reply()` | 新增選用參數 `etag`。圖片回應改送 `Cache-Control: public, max-age=0, must-revalidate` 加 `ETag`；瀏覽器帶 `If-None-Match` 而且沒變時回 304 空內容。只在 GET、狀態 200 時判斷；`If-None-Match` 接受多行、`W/`、`*`；304 不帶 `Content-Type`、`Content-Length` | 原本每次進大廳都要重新下載封面和主圖，約 400 KB；現在沒變就不重傳 |
| `server.py` 品牌字 | 檔頭說明、命令列說明、啟動訊息的「楠團德州撲克／扑克」改為「楠團牌室」 | 品牌名統一（只剩歷史檔 `static/app.js` 還是舊名，它不是現行入口，沒動） |
| `clubhouse.py` `DECOR` | 第 2 級「霓虹酒廊」改為「暖燈小館」，前端 `clubhouse-scene.js` 的 `names` 同步改 | 新的第 2 級建築圖是暖燈小店，舊名不搭。只改顯示字串，等級是存數字，不影響資料 |
| `test_assets.py`（新增） | 6 個測試：11 張封面都回 200；刁鑽路徑都是 404；ETag 回 304；`If-None-Match` 的各種寫法（`W/`、逗號清單、`*`、多行標頭、錯的值）；304 不帶內容相關標頭；API 仍是 `no-store` | 白名單和快取原本沒有測試 |

**API 和其他端點的行為都沒變，仍是 `no-store`、不壓縮。**

## 三、前端改了什麼

| 層級 | 檔案 | 說明 |
| --- | --- | --- |
| CSS | `static/night.css` | 尾端加了一段主題區塊，有開始／結束註解。 |
| CSS（續） | `static/night.css` | 用 `:is(#app,#modal,#social-root)` 前綴取得優先權（原始檔寫 `#app `，建置時展開，見第六節）。 |
| CSS（續） | `static/night.css` | 新增了 2 個 `!important`，用在 `.account-delete` 的框色與字色。原因是 `profile.css` 本來就用 `!important` 設定它。 |
| CSS（續） | `static/night.css` | 這份主題用全站通用選擇器，和 CONTRIBUTING「先以頁面根 class 限定」不同。這是刻意的，因為要整站換色。 |
| CSS | `static/clubhouse-scene.css` | 刪掉已經沒有對應節點的舊員工小人規則：`.estate-leg-*`、`.estate-uniform-*`、`@keyframes estate-step`。 |
| CSS | `static/ledger.css` | 舊記帳頁換成同樣主題，焦點框與下拉選單也一起處理。 |
| HTML | `static/index.html` | 標題改成「楠團牌室」，`theme-color` 改成 `#f6ecd9`。 |
| HTML（續） | `static/index.html` | 主要版本號為 `?v=cream-20261023`，整合後 `night.css`、`bonus.js` 更新為 `?v=cream-gate-20261024`：`night.css`、`clubhouse-scene.css`、`clubhouse-scene.js`、`profile.js`、`bonus.js`、`game.js`。 |
| HTML／JS | `static/ledger.html`、`static/ledger.js` | 標題、說明、側欄品牌、首頁連結的 aria-label、頁尾改成「楠團牌室」；`theme-color` 換掉；`ledger.css`、`ledger.js` 加上版本號。 |
| 圖 | `static/favicon.svg` | 墨綠盾牌加金黑桃。 |
| 圖 | `static/assets/poker-night.webp` | 大廳主圖，68.9 → 78.8 KiB。 |
| 圖 | `static/assets/clubhouse/tier-*.webp` | 會所四級 8 張，709.1 → 762.8 KiB，增加 7.6%。 |
| 圖 | `static/assets/covers/*.webp` | 新增 11 張遊戲封面，合計 287.4 KiB。 |
| 圖（共通） | 上面所有新圖 | 無文字、無真人。 |
| JS 模板 | `static/game.js` | 只改 3 個字串：`brand()` 從「楠團德州撲克／地下牌室」改成「楠團牌室／私人牌室」。 |
| JS 模板（續） | `static/game.js` | 牌桌絨布浮水印改成新品牌名。 |
| JS 模板（續） | `static/game.js` | 邀請複製文字改成新品牌名。這一個在複製按鈕的點擊處理程式裡，只換了字串。 |
| JS 模板 | `static/clubhouse-scene.js` | 員工走路改成 3 張 2D 貼圖，以 base64 內嵌，所以不需要後端放行。 |
| JS 模板（續） | `static/clubhouse-scene.js` | 檔案因此從 3,155 B 變成 36,563 B，而且每一頁都會載入。 |
| JS 模板（續） | `static/clubhouse-scene.js` | 走路起點依新建築圖重新對過。 |
| JS 模板（續） | `static/clubhouse-scene.js` | 新增 `sprite(key)` 給 profile.js 用；第 2 級名稱同步改名。 |
| JS 模板 | `static/profile.js` | 員工卡半身像改用同一張貼圖；沒有貼圖時退回原本的向量圖。 |
| JS 模板（續） | `static/profile.js` | `key` 只接受小寫英文，並用 `hasOwnProperty` 取值。 |
| JS 模板（續） | `static/profile.js` | 狐狸和貓的頭像重畫。 |
| JS 模板 | `static/bonus.js` | 拉霸符號、骰面點數、礦區／爬塔的寶石與地雷，原本是文字字元，改成內嵌小 SVG。 |
| JS 模板（續） | `static/bonus.js` | 只換了 span 的內容，`aria-label` 與動畫節點都沒變。 |
| JS 模板（續） | `static/bonus.js` | 刪掉已經沒用到的 `glyphs` 表。 |

德州座位的頭像本來就有畫在模板裡，是 CSS 把它藏起來，這次只是拿掉那條隱藏規則。

**第三輪 JS 模板**（只動畫面字串，沒動事件、流程、狀態、API、既有 id／`data-*`／`aria-label`）：

| 檔案 | 改動 |
| --- | --- |
| `static/bonus.js` 骰寶 | 「小 4–10」「大 11–17」的數字範圍包進 `<small>`，320 寬可以分兩行。 |
| `static/bonus.js` 礦區 | 棋盤上新增「收手，領取 N 點」鈕：原本只給爬塔的條件 `kind==='tower'` 改成 `kind==='tower'\|\|kind==='mines'`。按鈕沿用既有的 `data-arcade-action="cashout"`，沒有新事件。 |
| `static/arcade.js` `blackjackBets` | 確認名單每列前加頭像 `window.ClubIdentity.avatar(s)`，再用正則把 `data-member-id="\d+"` 換成 `data-member-id="0"`。原因：`profile.js` 的 `observe()` 會把 `data-member-id` 大於 0 的頭像變成可點連結（`role="link"`、可 Tab），名單裡不要多出這些停點和誤點跳頁。 |
| `static/arcade.js` `blackjackBets`（續） | 暱稱拆成 `<span class="bj-nick">` 和 `<span class="bj-you"> · 你</span>`，長暱稱只省略名字，不會吃掉「· 你」。 |
| `static/arcade.js` `big2Board` | 新增 `aria-hidden="true"` 的 `.big2-opponents`：每位對手一疊牌背（最多 13 張）加「暱稱 剩 N 張」。資料用 `h.players` 原本就有的 `card_count`，純裝飾，報讀不重複。 |
| `static/club.js` `ClubRewards.view` | 頭框／特效的試看頭像從 `avatar_key:'crown'` 改成 `'initial'`，顯示自己的字。 |
| `static/admin.js` `paint` | 帳號卡標題前加頭像（從 `lobby.users` 找同 id 的資料），同樣用正則換成 `data-member-id="0"`，理由同上。 |
| `static/profile.js` 上傳鈕 | 「上傳自己的照片」包進 `<span id="photo-upload-text" aria-hidden="true">`，`<input id="profile-photo">` 新增 `aria-labelledby="photo-upload-text"`，避免報讀念兩次。input 本來沒有 `aria-label`，其他屬性不變。 |

**CSS 依賴你的文字**：骰寶開獎前的金色骰盅，選擇器是 `.die-face[aria-label="等待收注開獎"]`（`bonus.js` 骰面的 `aria-label`）。改這段文字，骰盅會消失（不影響玩法）。

**最後兩輪的 CSS 修正**（`71379f0`、`f778c8f`，只動 `night.css`）：
- 拉霸錯誤框（`.error`）：固定在頂部。解除你 `night.css:120` 對 `#action-feedback[data-slot-status]` 的 44px 鎖高，框依內容長高。
  - 文字區 `pointer-events:none`，最多 4 行（`-webkit-line-clamp`），超過以「…」截斷；框本身是 `role=alert`，報讀器照樣念全文。
  - 只有「確認這筆操作」鈕吃觸控（44px）。框內字級改用 rem，跟著使用者字級放大。
  - 有錯誤時 `#toast` 的 top 是 `env(safe-area-inset-top) + 36px + 4.9rem`（預設約 114px），「轉動拉霸」（`#deal-hand`）的 `scroll-margin-top` 用同一個算式。
- 收藏卡：≤400 寬標題 13px＋`word-break:keep-all`，不在字中間斷。
- 排行：≤400 寬標題區 `display:contents`，副標獨佔一列。
- `details.night-supply>summary` 補 14px 左右內距，大廳與排行的折疊列都受影響（高度不變）。

**主題守的互動規則**（你改畫面時也請留意）：
- 可點元素至少 44×44px。唯一例外：礦區／爬塔的停用格只在「從沒開過局」（盤面沒有 `.safe`／`.hazard`）時縮小；結算後不縮。
- 伺服器回應後，不能讓另一個可點元素移到使用者剛點的位置（例如剛按「收手」的地方變成「開下一局」，連點就會誤開新局）。

本輪沒有改 `index.html` 的 `?v=`。JS／CSS 目前是 `no-store`，所以不影響；若你之後開長快取，記得一起換版本號。

素材的來源與提示詞見 [ASSETS.md](../../ASSETS.md) 和 [asset-prompts](../asset-prompts/)。

## 四、驗證

| 項目 | 結果 |
| --- | --- |
| `node scripts/check-js.cjs` | 17 個檔案語法通過 |
| `node scripts/check-docs.cjs` | 33 個本機連結通過 |
| `python3 -m unittest discover` | 360 個測試全過（含 `test_assets.py`、`test_static_artwork.py` 與射龍門牌靴） |
| `npm run test:layout` | 19 頁、266 組畫面通過（細節見第五節下方） |
| `npm run test:ui` | 本機通過 |
| DOM 比對 | 改前改後比對 35 頁 DOM，id 與 `data-*` 沒有遺失。大老二那一頁少了出牌按鈕，是因為截圖時輪到對手出牌 |
| 版面位移 | 9 個頁面、31 組主要容器（頂欄、排行列、成員卡、麻將桌與名牌、會所卡、牌桌卡、桌名列）的高度和改前完全相同 |
| 版面位移（例外） | 刻意加金框與卡片內距造成的高度差：大廳主圖 +4px、遊戲卡 +12px、會所頁標 +4px、後台帳號卡 −4px、轉帳表單 −7px |

**自動檢查**：每種組合跑 47 頁（含互動後、空大廳、14 款收藏試看），每頁量 5 件事。

| 瀏覽器／寬度 | 左右溢出 | 文字對比不足 | 焦點框 < 3:1 | 選中與未選中相同 | 控制項 < 44px |
| --- | --- | --- | --- | --- | --- |
| Chromium 320×844 | 0 | 0 | 0 | 0 | 0 |
| Chromium 393×852 | 0 | 0 | 0 | 0 | 0 |
| Chromium 768×1024 | 0 | 0 | 0 | 0 | 0 |
| Chromium 844×390 | 0 | 0 | 0 | 0 | 0 |
| Chromium 1366×900 | 0 | 0 | 0 | 0 | 0 |
| WebKit 26.5 393×852 | 0 | 0 | 0 | 0 | 0 |
| WebKit 26.5 1366×900 | 0 | 0 | 0 | 0 | 0 |

這張表的範圍與限制：
- 文字對比依 WCAG AA。`aria-hidden` 的純裝飾字（牌桌浮水印）不算；疊在照片上的字量不到，那幾處是人工看圖修正。
- 焦點框：對 `#app`、`#modal`、`#social-root` 與開著的 dialog 裡每個可聚焦元素觸發 `:focus-visible`，量外框對背後底色的對比，每頁最多 400 個。
- 控制項大小把用 `::after` 放大的點擊區算進去；勾選框以整個標籤計算。
- 選中狀態檢查每組 `aria-pressed`／`aria-selected` 按鈕。麥克風與收聽鈕的 `aria-pressed` 代表「已關閉」，刻意改用酒紅框表示，不套金色選中樣式；截圖時語音沒有開啟，所以這兩顆沒有被自動檢查到。
- WebKit 是 Safari 的引擎，**但不是 iPhone 實機**，實機沒有測。

| 其他 | 結果 |
| --- | --- |
| 低階手機效能 | 牌桌絨布的 `feTurbulence` 雜訊只算一次（120×120 磚塊）。Chromium 降速 6 倍捲動時，開或關雜訊沒有差別。無頭瀏覽器沒有真機 GPU，所以只能說「沒發現問題」 |
| 獨立審查 | 前兩輪三次 Opus 5.5 唯讀審查：第一次審全部、第二次審第一次的修正、第三次審後端與第二次的修正。成立的意見都已修正，並加進上面的自動檢查 |
| 獨立審查（第三輪） | 第三輪共 6 次 Opus 5.5 唯讀審查：第 1 批、第 2 批、第 2 批修正＋第 3 批、第 4 批＋修正 3、修正 4（`71379f0`）、修正 5（`f778c8f`）。最後一次（`f778c8f`）無 H、無 M。成立的意見已修正，判定可接受、沒修的列在第六節 |
| 自動檢查（第三輪） | 上表 5 項再加 3 項：主要操作在首屏、點擊後同位置不換成別的可點元素、placeholder 對比 |
| 截圖檢查（第三輪，以 `最終4-*` 為準） | 393／375／320／1366／WebKit／ext 全 0；375×667 首屏外 10；844×390 首屏外 19、點擊後位移 2（礦區、爬塔按「開始遊戲」後落在錢包摺疊列，舊問題，見第六節） |

## 五、建議你評估（沒有改）

- **全站壓縮。** 伺服器目前不壓縮。`index.html` 與它載入的 25 個 CSS／JS 檔共 636.2 KiB，用 gzip（等級 6）實際算過會變 205.2 KiB（小 68%）。這會影響所有回應，所以留給你決定。
- **JS 和 CSS 的快取。** 它們已經有 `?v=` 版本號，理論上可以給長快取。
  - 目前仍是 `no-store`，因為這會影響你的部署習慣。
- **員工貼圖改成獨立檔案。** `clubhouse-scene.js` 現在是 36,563 B，若介意可以把 3 張貼圖改成獨立 webp。
  - 做法和封面一樣，加進白名單即可。
- **`npm run test:layout` 的溢出判斷有盲點。** `tests/browser/layout.cjs` 用 `scrollWidth > innerWidth` 判斷左右溢出，但手機模擬下 `innerWidth` 會跟著內容變寬，所以抓不到。改用 `document.documentElement.clientWidth` 才準（我們自己的檢查已改）。
- **`test:layout` 沒有「主要操作在首屏」的檢查。** 目前抓不到「下注／出牌鈕被推出首屏」「可點的那層在首屏外」。我們的檢查是：每個遊戲頁的主要操作（`#deal-hand`、`#table-controls` 第一個可用主按鈕、爬塔／礦區可點格）要在 393×852、375×812、320×800 首屏內。

整合驗證補充：`npm run test:layout` 以 Chromium、WebKit 兩個引擎檢查 19 個頁面、7 種尺寸（320、375、393、768、844 橫向、1366、1920），共 266 組畫面；手機德州間距與牌背另有 14 組針對性檢查。`npm run test:ui` 保留雙人 21 點確認及會所升級流程測試。這些是瀏覽器模擬，並非實體手機驗證。

## 六、已知限制

- 沒有保留舊深色版的切換，主題是整站奶油白。
- 輪盤盤面沿用原本的 SVG，它已經是金框加酒紅墨黑，和主題一致。
- 用了 `:has()`。WebKit 26.5 和 Chromium 都正常，不支援的舊瀏覽器那幾條規則會失效。
- 牌桌浮水印「楠團牌室／私人牌室」刻意做成淡色裝飾，有 `aria-hidden`。
- 建置方式：主題原始檔在 repo 外（Steven 工作台的 `主題原始檔/cream.css`、`ledger-cream.css`），用 `工具/套用主題.sh` 套進 repo。
  - `night.css`：把原始檔的 `#app ` 展開成 `:is(#app,#modal,#social-root) `，替換尾端兩個註解之間的主題區塊（含註解）：起點 `/*==== 奶油白主題（P01/P02/P08）開始`，終點 `/*==== 奶油白主題 結束 ====*/`。區塊外的內容原樣保留，可以重複執行；找不到唯一的起點／終點就停下、不改檔。
  - `ledger.css`：從 `/*==== 奶油白主題（P01/P02）：舊記帳頁` 這個註解替換到檔尾，註解之前的內容原樣保留。
  - 不再從舊提交重建，所以你在 `main` 改主題區塊以外的地方不會被蓋掉。**直接改主題區塊（或 `ledger.css` 那段之後）的話，下次建置會被覆蓋**，請改在區塊外，或告訴我們同步回原始檔。
- 844×390 橫向：礦區、爬塔按「開始遊戲」後，同一點會變成錢包摺疊列。這是最後一次修正之前就有的問題，後果只是展開摺疊、不動錢；要改橫向版面才修得掉。
- 375×667、844×390 有些頁面的主要按鈕要捲動才看得到，要改全站外框才能解決。
- 爬塔在手機上 1F 在下、6F 在上，視覺順序和 Tab 順序不一致。這是為了在 320 寬首屏放得下「開下一局」。
- 桌機礦區有兩顆收手鈕（棋盤上一顆、操作列一顆），和爬塔一致。
- 21 點 320 寬下注階段只剩約 3px 餘裕；6 人桌加分牌沒有實測。
- 拉霸「待確認」期間，「確認這筆操作」鈕本身會蓋住頂欄語音、頭像（字級 130% 時連「連線」也蓋到）；其他頂欄鈕點得到。
- 收藏卡預覽區稱號小牌 `.cosmetic-preview .identity-title` 5 個字時，在 320～414 寬會折行（舊問題：最寬 62px，放不下 65px）。
- `.night-supply` 折疊列用灰色「＋／−」，規則折疊列用金色箭頭，尚未統一。
- Cloudflare 邊緣對 `public, max-age=0, must-revalidate`＋`ETag` 的處理沒有實測。部署後可以對同一張封面打兩次 `curl -sI https://<你的網域>/assets/covers/holdem.webp`，看 `cf-cache-status`、`cache-control`、`etag`，再帶 `If-None-Match` 打一次，確認回 304。
