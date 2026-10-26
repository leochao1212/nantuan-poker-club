# 素材與畫面交接

目前沒有 WebGL 或即時 3D 引擎。會所是四套 WebP 建築插圖，加一層 SVG 員工動畫；卡牌、遊戲封面及稱號等主要由 HTML／CSS／內嵌 SVG 組合。

## 建築與封面

| 素材 | 檔案 | 用途 |
| --- | --- | --- |
| 會所 Lv.1 | [桌機圖片](../static/assets/clubhouse/tier-1.webp)／[手機圖片](../static/assets/clubhouse/tier-1-small.webp) | 私人包廂：路邊破舊鐵皮棚，3:2 展示區 |
| 會所 Lv.2 | [桌機圖片](../static/assets/clubhouse/tier-2.webp)／[手機圖片](../static/assets/clubhouse/tier-2-small.webp) | 暖燈小館：整修後的街角小店，3:2 展示區 |
| 會所 Lv.3 | [桌機圖片](../static/assets/clubhouse/tier-3.webp)／[手機圖片](../static/assets/clubhouse/tier-3-small.webp) | 尊爵會館，3:2 展示區 |
| 會所 Lv.4 | [桌機圖片](../static/assets/clubhouse/tier-4.webp)／[手機圖片](../static/assets/clubhouse/tier-4-small.webp) | 曜金行宮，3:2 展示區 |
| 大廳主圖 | [poker-night.webp](../static/assets/poker-night.webp) | 大廳主圖區（左側留白給標題） |
| 遊戲封面 ×11 | static/assets/covers/*.webp（德州、大老二、21 點、輪盤、百家樂、拉霸、礦區、骰寶、爬塔、射龍門、麻將） | 大廳遊戲卡封面，由 `.game-art` 的現行圖片元件直接顯示；需後端白名單放行 `/assets/covers/` |
| 遊戲零件 ×33 | static/assets/pieces/*.webp | 拉霸、骰面、礦區、人像牌、輪盤框／軸、莊家鈕、下注籌碼、21 點牌靴、麻將鳥與花牌插畫 |
| 麻將牌面精靈圖 ×1 | [mj-tiles.svg](../static/assets/pieces/mj-tiles.svg) | 43 種大牌面及 43 種小牌面；透過 gzip／ETag 傳送，直接顯示現行牌面，圖片依麻將頁載入 |
| 按鈕零件 ×28 | static/assets/buttons/*.webp | 主要／次要／危險牌匾切片、選中／未選分頁切片、牌桌／卡片框、四色籌碼及金幣；直接使用現行切片，不切換舊版按鈕 |
| 網站圖示 | [favicon.svg](../static/favicon.svg) | 瀏覽器標誌 |

## 新素材的來源（奶油白主題）

建築、遊戲封面與員工插畫的生成提示詞放在 [asset-prompts](design-proposals/asset-prompts/)。其他新增素材的用途與來源依 [設計交接](design-proposals/cream-theme/HANDOFF.md) 記錄；未隨程式庫提供的原始美術稿不宣稱可完整重現。本清單不推定生成工具的授權條款。

麻將精靈圖由字形路徑與程式繪圖組成，字型來源標示為「全字庫正楷體」。出處保留在 SVG 與麻將規則頁，不將它列為 AI 圖片。139 個實際素材檔的路徑、大小和 SHA256 均登錄於下方素材清單。

| 素材 | 檔案 | 生成方式 |
| --- | --- | --- |
| 大廳主圖 | static/assets/poker-night.webp | `hero-lobby` 提示詞，裁成 3:2，1400×933（原本是 1400×600，比例從 7:3 改成 3:2；畫面用 cover 裁切，只是裁切位置不同，左側留白給標題）|
| 遊戲封面 ×11 | static/assets/covers/*.webp | `cover-*` 提示詞，裁成 4:3，480×360 |
| 會所四級（桌機＋手機） | static/assets/clubhouse/tier-1～4(-small).webp | 同一街角場景；第 1 級先畫，第 2～4 級各以前一級為參考圖逐級升級；桌機 1200×800，手機 600×400 |
| 員工 3 人走路貼圖 | static/assets/staff/concierge.webp、host.webp、steward.webp（高 220，共用檔案） | `staff-*` 提示詞，純洋紅背景生成後色鍵去背；同一張圖也用在 profile.js 的員工卡半身像 |
| 收藏牌背、絨布紋理 | night.css 內嵌 SVG；預設牌背另見下方朋友牌組 | 手寫 |
| 拉霸符號、骰面、礦區寶石與地雷、狐狸、貓 | 現行 WebP 圖片與個人頭像元件 | 遊戲零件直接使用上方現行 WebP，已移除舊 SVG 備用畫法 |
| favicon | static/favicon.svg | 手寫 |

會所圖換了之後，員工走路起點在 clubhouse-scene.js 的 `routes` 重新對過。校準時可把四級圖輪流換上去、三位員工都顯示後截圖檢查。

## 程式生成視覺

- clubhouse-scene.js：依裝潢級別選圖，SVG 員工位置和路徑；CSS 控制步行、離屏／背景暫停。
- arcade.js：gameArt 的現行 WebP 封面；game.js 的 card 產生撲克牌 DOM。
- club.js／night.css：頭像框、稱號、牌背與光效。
- arcade-motion.js／dealer.js：發牌與輪盤展示，不計算派彩。

完整圖片檔案大小與雜湊見 [素材清單](assets-manifest.json)。設計可換圖，但需保留版面比例、替代文字、手機來源、圖片預留空間與員工座標關係。新素材請附來源或生成紀錄；本清單不推定未提供的外部授權。

合成帳號的介面參考：[手機會所](screenshots/clubhouse-mobile.png)、[桌機 21 點](screenshots/blackjack-desktop.png)、[手機同桌手牌](screenshots/blackjack-peer-mobile.png)。這些截圖來自隔離的本機測試；正式玩家截圖與營運報告不包含在本程式庫。

第六輪新增輪盤／德州／21 點零件依出現的頁面載入；麻將精靈圖與鳥圖僅在麻將桌載入，花牌插畫出現時才下載。圖片網址使用內容指紋 `?v=<sha256 前 12 碼>`；WebP 指紋吻合時可快取一年，原始網址用 no-cache／ETag，錯誤指紋回 404、no-store。SVG 仍使用 no-cache＋gzip／ETag。更新素材後執行 `python scripts/check-ui-assets.py --write`，同步版本表、CSS 網址和素材清單；CI 會檢查三者一致。

遊戲 UI 的圖片與樣式只保留一套現行版本。ui-art.js 管理圖片元素、解碼與失敗占位，按遊戲準備拉霸、骰子、人物牌、麻將素材；按鈕與框線由唯一的 night.css 直接使用現行切片。三張員工貼圖由會所與員工卡共用，不再內嵌於 JavaScript。

## 楠團朋友牌組（2026-10-25）

從使用者提供的 105 張照片選出 52 張不同照片，使用內建 imagegen 製作上下雙頭人物牌。每個點數與花色有獨立圖片；K♠、Q♥、J♣ 保留使用者已確認的三張正式素材，其餘 49 張沿用象牙白紙感、金色植物雕花與大幅人像。原始照片與高解析生成稿留在本機，不隨程式庫發布。

- 牌面：static/assets/cards/ 下 52 張 WebP，檔名使用小寫牌碼（例如 as.webp、2h.webp、tc.webp），384×576。僅做等比縮小與 WebP 編碼。
- 預設牌背：[card-back-friends.webp](../static/assets/pieces/card-back-friends.webp)，256×384；收藏牌背仍優先生效。
- [朋友牌組提示詞](design-proposals/asset-prompts/friends-deck.txt) 與 [牌碼／來源對照](design-proposals/friends-deck.json) 記錄選圖及製作方式。

人物圖滿版等比 cover，點數與花色由 HTML／CSS 繪製，J 的花色較小，10 的字級另調整以容納兩位數。圖片不內建點數，避免與牌局資料矛盾。各遊戲只預載牌背與實際呈現的牌面，不在開桌時一次解碼整副 52 張；失敗時仍保留文字角標，沒有舊人物圖切回。

實際卡牌元件驗收：[手機](screenshots/friends-cards-phone.png)、[桌機](screenshots/friends-cards-desktop.png)。

### 牌面載入與尺寸修正

人物牌由 `ui-art.js` 的共用解碼快取追蹤 `loading`／`ready`／`failed`。`card()` 產生 `data-face-state`；照片解碼前或失敗時僅保留素色紙面與即時點數／花色，沒有舊 SVG 牌框、中央花色或 A 勳章。晚到的解碼只更新相同牌碼，不能覆蓋已換牌的節點。牌面仍按實際出現的牌載入，不一次下載整副。

預設牌背、桌上的暗牌、牌堆與兩種發牌動畫共用同一個 `--card-back`，指向朋友牌背；收藏的翡翠／酒紅牌背由根節點切換，動畫同步沿用。已移除德州／21 點的另一套預設牌背覆寫。

牌面尺寸集中在 `night.css` 的卡牌區：21 點自己手牌桌機 96px、手機 64–78px，莊家桌機 84px、手機 60–72px；多張手牌保留大牌並按可用空間扇形重疊，分牌使用響應式網格。大老二、百家樂、射龍門、德州、紀錄與重播各按容器設定牌寬，保留 2:3 比例。這次沒有重新產生人物圖片或改變牌局規則。


## 楠團漁港

釣魚原創素材在 `static/assets/fishing/`：`shore.webp` 第一人稱海灣、`sea-board.webp` 俯視海底、`fish-atlas.webp` 八種一般魚、`boss-atlas.webp` 四種特殊魚，以及三套釣竿／魚炮的 `gear-atlas.webp`。五檔約1.66MiB；首進休閒只載入必要三檔，街機才補背景與特殊魚，全部使用SHA指紋快取。舊harbor／reef圖已移除，沒有舊場景回退。

場景與特殊魚由內建ImageGen生成、WebP保留alpha；提示詞和檔案對照見[固定參考素材](design-proposals/asset-prompts/fishing-fixed-references.json)。一般魚與釣具沿用原創圖集；魚尾、釣竿、浮標、釣線、捕網和連鎖由Canvas按事件動畫。美術不自行決定派彩，特殊魚結算由伺服器完成。固定對照來源見[設計規格](design-proposals/fishing-fixed-references.md)。
