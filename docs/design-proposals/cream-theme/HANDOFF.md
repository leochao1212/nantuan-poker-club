# 奶油白主題 · 交接說明（給 leochao1212）

這個分支把全站手機與桌機畫面換成「奶油白底＋深綠絨布＋厚金邊」。

## 一、整合狀態（2026-10-24）

- 11 個遊戲封面的精確白名單已套用到 `server.py`，不存在的封面仍回 404。
- 公開 WebP 圖片使用 ETag 重新驗證；內容未變時回 304，避免再次下載圖片。每次都驗證版本，沒有舊圖停留問題。HTML、API、錢包、帳號和即時串流仍禁止快取。
- 已整合射龍門連續牌靴：每桌沿用 52 張牌，剩 13 張以下下一局重洗；倍率與機率依實際餘牌計算，免費略過只消耗兩張門柱。
- 手機德州增加中央資訊與手牌間距，右側頭像移入牌桌邊界；保留已裝備的翡翠／酒紅牌背。

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
| CSS（續） | `static/night.css` | 用 `#app`、`#modal`、`#social-root` 前綴取得優先權。 |
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

素材的來源與提示詞見 [ASSETS.md](../../ASSETS.md) 和 [asset-prompts](../asset-prompts/)。

## 四、驗證

| 項目 | 結果 |
| --- | --- |
| `node scripts/check-js.cjs`、`check-docs.cjs` | 通過 |
| `python3 -m unittest discover` | 整合版完整 358 個測試（含 `test_assets.py`、`test_static_artwork.py` 與射龍門牌靴） |
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
| 獨立審查 | 三次 Opus 5.5 唯讀審查：第一次審全部、第二次審第一次的修正、第三次審後端與第二次的修正。成立的意見都已修正，並加進上面的自動檢查 |

## 五、建議你評估（沒有改）

- **全站壓縮。** 伺服器目前不壓縮。`index.html` 與它載入的 25 個 CSS／JS 檔共 636.2 KiB，用 gzip（等級 6）實際算過會變 205.2 KiB（小 68%）。這會影響所有回應，所以留給你決定。
- **JS 和 CSS 的快取。** 它們已經有 `?v=` 版本號，理論上可以給長快取。
  - 目前仍是 `no-store`，因為這會影響你的部署習慣。
- **員工貼圖改成獨立檔案。** `clubhouse-scene.js` 現在是 36,563 B，若介意可以把 3 張貼圖改成獨立 webp。
  - 做法和封面一樣，加進白名單即可。

整合驗證補充：`npm run test:layout` 以 Chromium、WebKit 兩個引擎檢查 19 個頁面、7 種尺寸（320、375、393、768、844 橫向、1366、1920），共 266 組畫面；手機德州間距與牌背另有 14 組針對性檢查。`npm run test:ui` 保留雙人 21 點確認及會所升級流程測試。這些是瀏覽器模擬，並非實體手機驗證。

## 六、已知限制

- 沒有保留舊深色版的切換，主題是整站奶油白。
- 輪盤盤面沿用原本的 SVG，它已經是金框加酒紅墨黑，和主題一致。
- 用了 `:has()`。WebKit 26.5 和 Chromium 都正常，不支援的舊瀏覽器那幾條規則會失效。
- 牌桌浮水印「楠團牌室／私人牌室」刻意做成淡色裝飾，有 `aria-hidden`。
- 建置方式：主題原始檔在 Steven 的工作台，建置時會從基準提交 `98efd44` 重新產生 `night.css`。
  - 如果你之後在 `main` 改了 `night.css`，請告訴 Steven 先合併再重建。
- Cloudflare 邊緣對 `public, max-age=0, must-revalidate`＋`ETag` 的處理沒有實測。部署後可以對同一張封面打兩次 `curl -sI https://<你的網域>/assets/covers/holdem.webp`，看 `cf-cache-status`、`cache-control`、`etag`，再帶 `If-None-Match` 打一次，確認回 304。
