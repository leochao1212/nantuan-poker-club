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
| `server.py` `reply()` | 新增選用參數 `etag`。圖片回應改送 `Cache-Control: public, max-age=0, must-revalidate` 加 `ETag`；瀏覽器帶 `If-None-Match` 而且沒變時回 304 空內容 | 原本每次進大廳都要重新下載封面和主圖，約 400 KB；現在沒變就不重傳 |
| `server.py` 命令列說明 | 「楠團德州撲克 · 六人私人線上牌室」改為「楠團牌室 · 私人線上牌室」 | 品牌名統一 |
| `clubhouse.py` `DECOR` | 第 2 級「霓虹酒廊」改為「暖燈小館」，前端 `clubhouse-scene.js` 的 `names` 同步改 | 新的第 2 級建築圖是暖燈小店，舊名不搭。只改顯示字串，等級是存數字，不影響資料 |
| `test_assets.py`（新增） | 4 個測試：11 張封面都回 200、刁鑽路徑都是 404、圖片的 ETag 會回 304、API 仍是 `no-store` | 白名單和快取原本沒有測試 |

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
| HTML | `static/ledger.html` | 標題改成「楠團牌室 · 歷史帳本」，`theme-color` 換掉，`ledger.css` 加上版本號。 |
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
| 寬度 | 320、393、768、844×390、1366 共 5 種寬度，每種 47 張截圖，全部沒有左右溢出 |
| 文字對比 | 腳本逐元素量 WCAG AA，0 處不足。**限制：疊在照片上的字量不到，那幾處是人工看圖修正** |
| 焦點框 | 腳本對每個可聚焦元素觸發 `:focus-visible`，量外框對背景的對比，0 處低於 3:1 |
| 選中狀態 | 每組 `aria-pressed`／`aria-selected` 按鈕，按下和沒按下的外觀都不同，0 組相同 |
| 點擊範圍 | 0 個控制項小於 44×44 |
| 點擊範圍（做法） | 文字連結用絕對定位的 `::after` 放大點擊區，不改 display、padding、margin |
| 點擊範圍（勾選框） | 勾選框 24px，但整個標籤有 44px 高可以點 |
| 版面位移 | 和改前比對主要容器高度：排行列、成員卡、頂欄、麻將名牌都完全一樣 |
| 版面位移（例外） | 因為刻意加了金框和卡片內距，有幾處高度不同：大廳主圖 +4px、遊戲卡 +12px、會所頁標 +4px、後台帳號卡 −4px、轉帳表單 −7px |
| Safari 引擎 | 用 Playwright WebKit 26.5 跑同樣 47 頁，結果和 Chromium 一致。**這不是 iPhone 實機，實機沒有測** |
| 低階手機效能 | 牌桌絨布的 `feTurbulence` 雜訊只算一次，是 120×120 的磚塊。Chromium 降速 6 倍捲動時，開或關雜訊都沒有差別 |
| 低階手機效能（限制） | 無頭瀏覽器沒有真機 GPU，所以只能說「沒發現問題」 |
| 獨立審查 | 兩次 Opus 5.5 唯讀審查，第二次專門審第一次的修正。成立的意見都已修正，並加進上面的自動檢查 |

## 五、建議你評估（沒有改）

- **全站壓縮。** 伺服器目前不壓縮。首頁載入的 CSS／JS／HTML 用 gzip（等級 6）實際算過可以從 638 KB 變 206 KB（小 68%）。這會影響所有回應，所以留給你決定。
- **JS 和 CSS 的快取。** 它們已經有 `?v=` 版本號，理論上可以給長快取。
  - 目前仍是 `no-store`，因為這會影響你的部署習慣。
- **員工貼圖改成獨立檔案。** `clubhouse-scene.js` 現在是 36 KB，若介意可以把 3 張貼圖改成獨立 webp。
  - 做法和封面一樣，加進白名單即可。

整合驗證補充：`npm run test:layout` 以 Chromium、WebKit 兩個引擎檢查 19 個頁面、7 種尺寸（320、375、393、768、844 橫向、1366、1920），共 266 組畫面；手機德州間距與牌背另有 14 組針對性檢查。`npm run test:ui` 保留雙人 21 點確認及會所升級流程測試。這些是瀏覽器模擬，並非實體手機驗證。

## 六、已知限制

- 沒有保留舊深色版的切換，主題是整站奶油白。
- 輪盤盤面沿用原本的 SVG，它已經是金框加酒紅墨黑，和主題一致。
- 用了 `:has()`。WebKit 26.5 和 Chromium 都正常，不支援的舊瀏覽器那幾條規則會失效。
- 牌桌浮水印「楠團牌室／私人牌室」刻意做成淡色裝飾，有 `aria-hidden`。
- 建置方式：主題原始檔在 Steven 的工作台，建置時會從基準提交 `98efd44` 重新產生 `night.css`。
  - 如果你之後在 `main` 改了 `night.css`，請告訴 Steven 先合併再重建。
