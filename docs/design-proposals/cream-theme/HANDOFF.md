# 奶油白主題 · 交接說明（給 leochao1212）

這個分支把全站手機／桌機畫面換成「奶油白底＋深綠絨布＋厚金邊」。只動外觀，沒動玩法、流程、資料、API、DOM 身分（id、`data-*`）。
改前改後對照圖：同資料夾 `*-before-after.jpg`（大廳、德州、會所、21 點、收藏、後台、拉霸、礦區、骰寶）。

## 一、要你做的事（只有一件）

`server.py` 的靜態圖白名單要多放行 11 個封面檔。大廳遊戲封面放在 `static/assets/covers/*.webp`，目前會 404。

在圖片放行那一行（`elif path=='/assets/poker-night.webp' or ...`）最後面，加上一個條件：

```text
or re.fullmatch(r'/assets/covers/(?:holdem|big2|blackjack|roulette|baccarat|slot|mines|dice|tower|inbetween|mahjong)\.webp', path)
```

刻意列出確切的 11 個檔名，不用萬用字元：這樣不存在的檔名仍然是 404，不會落到 `read_bytes()` 變成 500。完整補丁檔在 Steven 的工作台（`交接/server-放行封面圖.patch`）。

這是後端檔案，我們沒有放進任何 commit，等你確認要這樣改。沒放行之前，封面只會看到原本的線條圖，其他功能不受影響。這條路徑目前沒有測試，建議放行時順手補一個。

## 二、改了什麼

| 層級 | 檔案 | 說明 |
| --- | --- | --- |
| 自由改（CSS） | `static/night.css` | 尾端加了一段有開始／結束註解的主題區塊。用 `#app` `#modal` `#social-root` 前綴取得優先權。**有新增 2 個 `!important`**（`.account-delete` 的框色與字色，因為 `profile.css` 本來就用 `!important` 設定它）。注意：這份主題用全站通用選擇器，和 CONTRIBUTING 的「先以頁面根 class 限定」不同，是刻意的（整站換色）|
| 自由改（CSS） | `static/ledger.css`、`ledger.html` | 舊記帳頁同樣主題；`theme-color` 改為奶油色 |
| 自由改（CSS） | `static/index.html` | `night.css` 版本號、`<title>`、`theme-color`（#f6ecd9） |
| 自由改（圖） | `static/favicon.svg` | 墨綠盾牌＋金黑桃 |
| 自由改（圖） | `static/assets/poker-night.webp`、`clubhouse/tier-*.webp`、`covers/*.webp` | 大廳主圖、會所四級、11 款遊戲封面。無文字、無真人。大小：會所 8 張 709 KB → 762 KB（+7%）、主圖 68 → 78 KB、新增 11 張封面共 287 KB |
| 要回報（JS 模板） | `static/game.js` | 只有 3 個字串：`brand()` 的「楠團德州撲克／地下牌室」→「楠團牌室／私人牌室」；牌桌絨布浮水印；邀請複製文字（這一個在複製按鈕的點擊處理程式裡，只換字串，不是模板） |
| 要回報（JS 模板） | `static/clubhouse-scene.js` | 員工走路改成 3 張 2D 貼圖（base64 內嵌，不需放行；這個檔案因此從 3 KB 變 45 KB，每一頁都會載入。若介意，可改成獨立 webp 並加入白名單）；走路起點重設；新增 `sprite(key)` 給 profile.js 用 |
| 要回報（JS 模板） | `static/profile.js` | `portrait()` 優先用貼圖上半身，沒有貼圖就退回原本向量圖；`pet()` 重畫狐狸、貓（兩隻長得不一樣） |
| 要回報（JS 模板） | `static/bonus.js` | 拉霸符號（7、皇冠、寶石、鈴鐺、櫻桃、BAR）、骰面點數、礦區／爬塔的寶石與地雷，原本是文字字元，改成內嵌小 SVG。只換 span 裡的內容；`aria-label`、`data-*`、動畫作用的節點（`.slot-reel span`、`.die-face`）都沒變 |
| 文件 | `docs/ASSETS.md`、`docs/assets-manifest.json`、`docs/design-proposals/asset-prompts/` | 素材來源與提示詞（可重現） |

沒碰：事件綁定、狀態、請求、SSE、後端、玩法、派彩、`member_accounts.py`。

## 三、座位頭像（P06）

德州座位的頭像原本就有畫（`game.js` 座位模板呼叫 `avatar(seat)`），是 CSS 把它藏起來。現在只是拿掉那條隱藏，畫成蓋在名字牌上緣的小圓徽章。顯示的是玩家在「我的帳號」選的內建頭像或上傳的照片。

## 四、等級名稱（需要你配合，可以晚點）

會所四級建築圖已經是「路邊鐵皮棚 → 整修小店 → 正式會館 → 豪華行宮」，原本名稱「霓虹酒廊」跟新畫面不搭。名稱存在兩處，要一起改才對得上：`clubhouse.py` 第 17 行 `DECOR`、`static/clubhouse-scene.js` 的 `names`。新名字由 Steven 決定後再通知。

## 五、驗證

| 項目 | 結果 |
| --- | --- |
| `node scripts/check-js.cjs`、`check-docs.cjs` | 通過 |
| `python3 -m unittest discover` | 351 個測試全過 |
| `npm run test:ui`（瀏覽器流程） | 本機通過；CI 的 `pull_request` 那輪通過 |
| DOM 比對 | 改前改後 35 頁抓 DOM，id、`data-*` 沒有遺失（大老二一頁少了出牌按鈕，是這次輪到對手出牌） |
| 寬度 | 320／393／768／844×390／1366，47 張截圖全部 0 左右溢出 |
| 文字對比 | 腳本逐元素量（WCAG AA）。**限制：底圖是照片的元素（例如主圖上的字）量不到，那幾處是人工看圖修的** |
| 選中狀態 | 腳本檢查每組 `aria-pressed`／`aria-selected` 按鈕，按下與沒按下外觀不同：0 組相同（Opus 審查曾抓到 11 組，已修） |
| 點擊範圍 | 腳本量按鈕大小；仍有少數不到 44px：成員名字連結、麻將玩家名連結、後台房間連結、`#toggle-password`（58×42）、開桌視窗的私人包廂勾選框（20×20）、舊記帳頁 `select#unit`（60×34）。這些大多是原本的版面，沒有處理 |
| 沒測 | Safari 實機；低階手機上 `feTurbulence` 雜訊背景（牌桌絨布）的繪製效能 |

另外有一位獨立審查者（Opus 5.5）審過這批變更，意見與處理方式見 PR 留言。

## 六、已知限制

- 輪盤盤面沿用原本的 SVG（金框、酒紅與墨黑口袋，已經跟主題一致），沒有重畫。
- 外觀收藏 14 款都在「試看」舞台逐一截圖檢查過（舞台刻意保留深色，讓光效看得出來）；一款稱號牌（深夜常客）的字色已修。
- 沒有做深色模式切換：主題是整站奶油白，沒有保留舊深色版的開關。
- 伺服器對所有檔案送 `Cache-Control: no-store` 且不壓縮，所以封面與主圖每次進大廳都會重新下載（約 400 KB）。這是原本的設定，沒有動；之後若要改善，可以對 `/assets/` 開快取。
- 有用到 `:has()`（會所頁與牌桌頁的版面規則），不支援的舊瀏覽器那幾條規則會失效。
- `工具/套用主題.sh`（Steven 的工作台，不在 repo）每次從基準提交 `98efd44` 重建 `night.css`；`main` 之後若有人改了 `night.css`，需要先合併再重建。
- 第二審（Codex）的完整意見在 Steven 的工作台，主要是預覽圖與真實元件的差異，實作以真實元件為準。
