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
| 遊戲封面 ×11 | static/assets/covers/*.webp（德州、大老二、21 點、輪盤、百家樂、拉霸、礦區、骰寶、爬塔、射龍門、麻將） | 大廳遊戲卡封面，經 `.game-art::before` 疊上；需後端白名單放行 `/assets/covers/` |
| 遊戲零件 ×32 | static/assets/pieces/*.webp | 拉霸、骰面、礦區、人像牌、輪盤框／軸、莊家鈕、下注籌碼、21 點牌靴、麻將鳥與花牌插畫 |
| 麻將牌面精靈圖 ×1 | [mj-tiles.svg](../static/assets/pieces/mj-tiles.svg) | 43 種大牌面及 43 種小牌面；透過 gzip／ETag 傳送，與鳥圖載入後才切換，失敗保留文字牌 |
| 按鈕零件 ×28 | static/assets/buttons/*.webp | 主要／次要／危險牌匾切片、選中／未選分頁切片、牌桌／卡片框、四色籌碼及金幣；兩批各自預載，失敗保留原 CSS 按鈕 |
| 網站圖示 | [favicon.svg](../static/favicon.svg) | 瀏覽器標誌 |

## 新素材的來源（奶油白主題）

建築、遊戲封面與員工插畫的生成提示詞放在 [asset-prompts](design-proposals/asset-prompts/)。其他新增素材的用途與來源依 [設計交接](design-proposals/cream-theme/HANDOFF.md) 記錄；未隨程式庫提供的原始美術稿不宣稱可完整重現。本清單不推定生成工具的授權條款。

麻將精靈圖由字形路徑與程式繪圖組成，字型來源標示為「全字庫正楷體」。出處保留在 SVG 與麻將規則頁，不將它列為 AI 圖片。81 個實際素材檔的路徑、大小和 SHA256 均登錄於下方素材清單。

| 素材 | 檔案 | 生成方式 |
| --- | --- | --- |
| 大廳主圖 | static/assets/poker-night.webp | `hero-lobby` 提示詞，裁成 3:2，1400×933（原本是 1400×600，比例從 7:3 改成 3:2；畫面用 cover 裁切，只是裁切位置不同，左側留白給標題）|
| 遊戲封面 ×11 | static/assets/covers/*.webp | `cover-*` 提示詞，裁成 4:3，480×360 |
| 會所四級（桌機＋手機） | static/assets/clubhouse/tier-1～4(-small).webp | 同一街角場景；第 1 級先畫，第 2～4 級各以前一級為參考圖逐級升級；桌機 1200×800，手機 600×400 |
| 員工 3 人走路貼圖 | 內嵌在 static/clubhouse-scene.js（base64 webp，高 220） | `staff-*` 提示詞，純洋紅背景生成後色鍵去背；同一張圖也用在 profile.js 的員工卡半身像 |
| 牌背、絨布紋理 | 不是檔案，在 night.css 以內嵌 SVG 產生 | 手寫 |
| 拉霸符號、骰面、礦區寶石與地雷、狐狸、貓 | 內嵌 SVG（bonus.js、profile.js） | 手寫；部分遊戲零件解碼成功後使用 WebP，原 SVG 保留作退回樣式 |
| favicon | static/favicon.svg | 手寫 |

會所圖換了之後，員工走路起點在 clubhouse-scene.js 的 `routes` 重新對過。校準時可把四級圖輪流換上去、三位員工都顯示後截圖檢查。

## 程式生成視覺

- clubhouse-scene.js：依裝潢級別選圖，SVG 員工位置和路徑；CSS 控制步行、離屏／背景暫停。
- arcade.js：gameArt 的遊戲卡片 SVG；game.js 的 card 產生撲克牌 DOM。
- club.js／effects.css：頭像框、稱號、牌背與光效。
- arcade-motion.js／dealer.js：發牌與輪盤展示，不計算派彩。

完整圖片檔案大小與雜湊見 [素材清單](assets-manifest.json)。設計可換圖，但需保留版面比例、替代文字、手機來源、圖片預留空間與員工座標關係。新素材請附來源或生成紀錄；本清單不推定未提供的外部授權。

合成帳號的介面參考：[手機會所](screenshots/clubhouse-mobile.png)、[桌機 21 點](screenshots/blackjack-desktop.png)、[手機同桌手牌](screenshots/blackjack-peer-mobile.png)。這些截圖來自隔離的本機測試；正式玩家截圖與營運報告不包含在本程式庫。

第六輪新增輪盤／德州／21 點零件依出現的頁面載入；麻將精靈圖與鳥圖僅在麻將桌載入，花牌插畫出現時才下載。SVG 使用 no-cache＋gzip／ETag，WebP 使用 max-age=0,must-revalidate；兩者都需重新驗證。
