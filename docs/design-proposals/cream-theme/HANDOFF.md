# 奶油白主題 · 交接說明（給 leochao1212）

這個分支把全站手機／桌機畫面換成「奶油白底＋深綠絨布＋厚金邊」。只動外觀，沒動玩法、流程、資料、API、DOM 身分（id、`data-*`）。
改前改後對照圖：同資料夾 `*-before-after.jpg`。

## 一、要你做的事（只有一件）

`server.py` 的靜態圖白名單要多放行一個資料夾。大廳遊戲封面放在 `static/assets/covers/*.webp`，目前會 404。

```diff
-            elif path=='/assets/poker-night.webp' or re.fullmatch(r'/assets/clubhouse/tier-[1-4](?:-small)?\.webp',path):
+            elif path=='/assets/poker-night.webp' or re.fullmatch(r'/assets/clubhouse/tier-[1-4](?:-small)?\.webp',path) or re.fullmatch(r'/assets/covers/[a-z0-9-]+\.webp',path):
```

這是後端檔案，我們沒有放進任何 commit，等你確認要這樣改。沒放行之前，封面只會看到原本的線條圖，其他功能不受影響。

## 二、改了什麼

| 層級 | 檔案 | 說明 |
| --- | --- | --- |
| 自由改（CSS） | `static/night.css` | 尾端加了一段有開始／結束註解的主題區塊。用 `#app` `#modal` `#social-root` 前綴取得優先權，沒有新增 `!important` |
| 自由改（CSS） | `static/ledger.css`、`ledger.html` | 舊記帳頁同樣主題；`theme-color` 改為奶油色 |
| 自由改（CSS） | `static/index.html` | `night.css` 版本號、`<title>`、`theme-color`（#f6ecd9） |
| 自由改（圖） | `static/favicon.svg` | 墨綠盾牌＋金黑桃 |
| 自由改（圖） | `static/assets/poker-night.webp`、`clubhouse/tier-*.webp`、`covers/*.webp` | 大廳主圖、會所四級、11 款遊戲封面。無文字、無真人。大小比原本小 |
| 要回報（JS 模板） | `static/game.js` | 只有 3 個字串：`brand()` 的「楠團德州撲克／地下牌室」→「楠團牌室／私人牌室」；邀請複製文字；牌桌絨布浮水印 |
| 要回報（JS 模板） | `static/clubhouse-scene.js` | 員工走路改成 3 張 2D 貼圖（base64 內嵌，不需放行）；走路起點重設；新增 `sprite(key)` 給 profile.js 用 |
| 要回報（JS 模板） | `static/profile.js` | `portrait()` 優先用貼圖上半身，沒有貼圖就退回原本向量圖 |
| 文件 | `docs/ASSETS.md`、`docs/assets-manifest.json`、`docs/design-proposals/asset-prompts/` | 素材來源與提示詞（可重現） |

沒碰：事件綁定、狀態、請求、SSE、後端、玩法、派彩、`member_accounts.py`。

## 三、座位頭像（P06）

德州座位的頭像原本就有畫（`game.js` 座位模板呼叫 `avatar(seat)`），是 CSS 把它藏起來。現在只是拿掉那條隱藏，畫成蓋在名字牌上緣的小圓徽章。顯示的是玩家在「我的帳號」選的內建頭像或上傳的照片。

## 四、等級名稱（需要你配合，可以晚點）

會所四級建築圖已經是「路邊鐵皮棚 → 整修小店 → 正式會館 → 豪華行宮」，原本名稱「霓虹酒廊」跟新畫面不搭。名稱存在兩處，要一起改才對得上：`clubhouse.py` 第 17 行 `DECOR`、`static/clubhouse-scene.js` 的 `names`。新名字由 Steven 決定後再通知。

## 五、驗證

| 項目 | 結果 |
| --- | --- |
| `node scripts/check-js.cjs` | 通過（17 個檔） |
| `node scripts/check-docs.cjs` | 通過 |
| `python3 -m unittest discover` | 351 個測試全過 |
| `npm run test:ui`（瀏覽器流程） | 通過，無錯誤 |
| 結構比對 | 改前改後 35 頁抓 DOM，id、`data-*` 一個都沒少（德州頁多出的差異是動態 class） |
| 寬度 | 320／393／768／844×390／1366：全部 0 頁左右溢出 |
| 對比 | 腳本逐元素量文字與底色對比（WCAG AA）；手機 41 頁剩 1 種不足，已記錄 |
| 點擊範圍 | 腳本量按鈕大小；剩少數行內連結（成員名字連結、麻將玩家名）不到 44px，是原本的版面 |

## 六、已知限制

- 遊戲專屬圖形（拉霸符號、骰面、礦區寶石、輪盤盤面）還是原本的程式圖形，只換了顏色。立體符號要改 JS，另案。
- 外觀收藏的 7 款頭像特效、3 款稱號沒有逐一驗證新底色上的效果。
- 沒有做深色模式切換：主題是整站奶油白，沒有保留舊深色版的開關。
- 第二審（Codex）的完整意見在 Steven 的工作台，主要是預覽圖與真實元件的差異，實作以真實元件為準。
