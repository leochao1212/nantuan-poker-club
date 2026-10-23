# 素材與畫面交接

目前沒有 WebGL 或即時 3D 引擎。會所是四套 WebP 建築插圖，加一層 SVG 員工動畫；卡牌、遊戲封面及稱號等主要由 HTML／CSS／內嵌 SVG 組合。

## 建築與封面

| 素材 | 檔案 | 用途 |
| --- | --- | --- |
| 會所 Lv.1 | [桌機圖片](../static/assets/clubhouse/tier-1.webp)／[手機圖片](../static/assets/clubhouse/tier-1-small.webp) | 私人包廂：路邊破舊鐵皮棚，3:2 展示區 |
| 會所 Lv.2 | [桌機圖片](../static/assets/clubhouse/tier-2.webp)／[手機圖片](../static/assets/clubhouse/tier-2-small.webp) | 整修後的街角小店（名稱見後端 DECOR），3:2 展示區 |
| 會所 Lv.3 | [桌機圖片](../static/assets/clubhouse/tier-3.webp)／[手機圖片](../static/assets/clubhouse/tier-3-small.webp) | 尊爵會館，3:2 展示區 |
| 會所 Lv.4 | [桌機圖片](../static/assets/clubhouse/tier-4.webp)／[手機圖片](../static/assets/clubhouse/tier-4-small.webp) | 曜金行宮，3:2 展示區 |
| 大廳主圖 | [poker-night.webp](../static/assets/poker-night.webp) | 大廳主圖區（左側留白給標題） |
| 遊戲封面 ×11 | static/assets/covers/*.webp（德州、大老二、21 點、輪盤、百家樂、拉霸、礦區、骰寶、爬塔、射龍門、麻將） | 大廳遊戲卡封面，經 `.game-art::before` 疊上；需後端白名單放行 `/assets/covers/` |
| 網站圖示 | [favicon.svg](../static/favicon.svg) | 瀏覽器標誌 |

## 新素材的來源（奶油白主題）

所有新圖是 AI 生成的視覺素材（不含文字、不含真人），提示詞原文放在 [asset-prompts](design-proposals/asset-prompts/)，一圖一檔，可重現。會所四級用同一個街角場景、前一級當參考逐級升級。員工 3 人的走路貼圖用純洋紅背景生成後去背，縮成小圖內嵌在 clubhouse-scene.js（不需要額外放行）。本清單不推定生成工具的授權條款。

## 程式生成視覺

- clubhouse-scene.js：依裝潢級別選圖，SVG 員工位置和路徑；CSS 控制步行、離屏／背景暫停。
- arcade.js：gameArt 的遊戲卡片 SVG；game.js 的 card 產生撲克牌 DOM。
- club.js／effects.css：頭像框、稱號、牌背與光效。
- arcade-motion.js／dealer.js：發牌與輪盤展示，不計算派彩。

完整圖片檔案大小與雜湊見 [素材清單](assets-manifest.json)。設計可換圖，但需保留版面比例、替代文字、手機來源、圖片預留空間與員工座標關係。新素材請附來源或生成紀錄；本清單不推定未提供的外部授權。

合成帳號的介面參考：[手機會所](screenshots/clubhouse-mobile.png)、[桌機 21 點](screenshots/blackjack-desktop.png)、[手機同桌手牌](screenshots/blackjack-peer-mobile.png)。這些截圖來自隔離的本機測試；正式玩家截圖與營運報告不包含在本程式庫。
