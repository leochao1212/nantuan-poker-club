# 現行 UI 交接

遊戲網站唯一樣式為 static/night.css；元件圖片由 static/ui-art.js 與 static/assets/ 提供。現行外觀延續奶油白、墨綠、酒紅與金框設計。原先的分散樣式、新圖蓋舊圖及整批預載後切換主題的做法已退役，歷史設計可從 Git 查閱。

| 元件 | 現行來源 |
| --- | --- |
| 遊戲封面 | covers/*.webp，直接 img，沒有下層舊 SVG |
| 拉霸／骰寶／礦區 | pieces/*.webp，單一圖片元素，解碼後開始視覺動畫 |
| 撲克牌 | 點數／花色與框線 CSS、J/Q/K 現行插畫；保留收藏牌背 |
| 麻將 | mj-tiles.svg 精靈圖與鳥／花牌 WebP，沒有舊文字牌／舊 SVG 畫法 |
| 按鈕／籌碼／框線 | buttons/*.webp 現行切片，HTML 文字與原操作目標保持 |
| 會所／員工 | 四級建築與手機來源、staff/*.webp 共用員工圖、既有 SVG 路徑動畫 |
| 稱號／頭像／收藏 | 既有裝備與動態效果，由現行 stylesheet 提供 |

圖片失敗只顯示同主題的占位／語意標籤，不回復舊設計。載入與動畫不得阻塞伺服器回執、操作、重連及下一局。

改動請直接修改現行元件，保留 data-action、data-card-key、data-mj-tile 等互動契約。執行 test:ui、test:layout 與 test:motion；手機／桌機、WebKit／Chromium、一般動畫／減少動畫與圖片慢載入／失敗均需確認。素材用途、來源與雜湊以 docs/ASSETS.md 和 docs/assets-manifest.json 為準。
