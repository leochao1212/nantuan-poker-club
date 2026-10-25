# 測試目錄

| 目錄 | 內容 | 說明 |
| --- | --- | --- |
| [python/](python/README.md) | 46 個 Python 回歸測試檔與共用 fixture | 規則、HTTP、交易、點數、串流、恢復、語音、資源與部署保護；說明列出各檔用途 |
| browser/ | Playwright 操作與排版測試 | smoke.cjs 為會所／雙人 21 點操作，layout.cjs 為 Chromium／WebKit 全站排版，round4-checks.cjs 為大廳／牌角補充檢查，table-controls.cjs 為牌桌操作回歸，art-motion.cjs 檢查現行圖片、384 個一般動畫時間點與載入失敗／恢復 |

```sh
python -m unittest discover -s tests/python -t . -v
npm run test:ui
npm run test:layout
npm run test:motion
```

命令從程式庫根目錄執行；瀏覽器測試先 npm ci，並安裝 Chromium／WebKit。兩層 __init__.py 讓標準 unittest 能以套件探索，沒有額外測試框架或路徑修改。輸出位於忽略的 artifacts/，不屬發布原始碼。

完整驗證策略見 [docs/TESTING.md](../docs/TESTING.md)。

- `npm run test:reveal`：輪盤與拉霸的真實開局、慢回應確認、延後揭曉、收據重送、快速／略過。

- `test_fishing.py`：雙模式釣魚、公開機率、私人漁獲、帳本原子性與20人並行；瀏覽器配套為 `npm run test:fishing`。
