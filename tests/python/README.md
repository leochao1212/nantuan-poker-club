# Python 回歸測試（46 個檔案）

這裡集中所有 Python 測試。整理時移動前後均為 386 個測試案例，案例名稱及次數一致；後續數量以當次 CI 為準。

## 執行方式

以下命令都從程式庫根目錄執行，使用 Python 3.14 作驗證基準，僅需標準庫。

```sh
# 完整回歸（CI 使用同一入口）
python -m unittest discover -s tests/python -t . -v

# 只跑一個檔案
python -m unittest tests.python.test_transfers -v

# 只跑一個類別或案例
python -m unittest tests.python.test_transfers.TransferRules -v
python -m unittest tests.python.test_transfers.TransferRules.test_conservation_receipt_restart_and_privacy -v
```

`python -m unittest discover -v` 仍可從根目錄探索到完整測試；CI 明確指定資料夾與根目錄。請使用套件命令，不要直接執行 `python tests/python/test_xxx.py` 或切進測試資料夾執行，以免破壞相對 import。

## 安全與共用 fixture

- 使用記憶體 SQLite 或臨時目錄，API 測試另啟 loopback 伺服器，不使用正式帳號或資料庫。
- 測試共用工具仍在原測試檔內；同資料夾引用使用 `from .test_app import Client` 或 `from . import test_club as fixtures`。不要把測試模組加回根目錄，也不需要修改 sys.path。
- `test_app.py` 的 ROOT 指向程式庫根目錄，測試伺服器與管理員 CLI 都從該根目錄定位。
- 效能、串流和語音測試含時間限制；失敗時先檢查日誌與環境，不移除斷言、放寬安全條件或用重試掩蓋問題。
- 瀏覽器測試另在 [../browser/](../browser/)，完整策略見 [測試與驗證](../../docs/TESTING.md)。

## 每個檔案的用途

### 網站、帳號與虛擬點數

| 檔案 | 用途 |
| --- | --- |
| [test_app.py](test_app.py) | HTTP 登入／註冊及完整牌局流程；提供隔離伺服器 ServerTestCase、Client 共用 fixture。 |
| [test_admin.py](test_admin.py) | 管理員權限、建立管理員 CLI、點數調整；提供 AdminRules 共用 fixture。 |
| [test_auth_review.py](test_auth_review.py) | 登入驗證、Session 與安全邊界的回歸。 |
| [test_club.py](test_club.py) | 帳號錢包、補給與共用 WalletRules fixture。 |
| [test_hourly.py](test_hourly.py) | 每小時補給資格、金額與重複領取防護。 |
| [test_transfers.py](test_transfers.py) | 轉帳守恆、權限、並行請求、收據與交易回滾。 |
| [test_profiles.py](test_profiles.py) | 個人資料、頭像、名稱與帳號管理。 |
| [test_cosmetics.py](test_cosmetics.py) | 外觀商品購買、擁有權、裝備與重複扣點防護。 |

### 德州與共用資金規則

| 檔案 | 用途 |
| --- | --- |
| [test_poker.py](test_poker.py) | 牌力、德州狀態機、底池、座位；提供 room_with_players fixture。 |
| [test_rules.py](test_rules.py) | 下注、All-in、邊池、領牌及儲存規則的回歸。 |
| [test_transactions.py](test_transactions.py) | HTTP 操作收據、交易原子性及重送防護。 |
| [test_funding.py](test_funding.py) | 入桌、補碼、離桌退款與錢包／桌上點數移轉。 |

### 各款遊戲、設定與公平性

| 檔案 | 用途 |
| --- | --- |
| [test_arcade.py](test_arcade.py) | 大老二、21 點、輪盤與保存／恢復；提供 room、shoe、points fixture。 |
| [test_big2_review.py](test_big2_review.py) | 大老二壓牌、回合及排隊處理的回歸。 |
| [test_big2_taiwan.py](test_big2_taiwan.py) | 台灣大老二牌型、流程、特殊限制與剩牌計分。 |
| [test_blackjack_confirmation.py](test_blackjack_confirmation.py) | 多人 21 點各自確認、一起發牌與扣點時機。 |
| [test_bonus.py](test_bonus.py) | 百家樂、拉霸、礦區、爬塔等規則與儲存；提供小遊戲 room、points fixture。 |
| [test_dice_multiplayer.py](test_dice_multiplayer.py) | 多人骰寶共享開獎、收注、逾時與各自結算。 |
| [test_dice_tower_modes.py](test_dice_tower_modes.py) | 骰寶押法、爬塔難度／倍率及原子開局。 |
| [test_gate_blackjack.py](test_gate_blackjack.py) | 射龍門與 21 點下注邊界；提供固定牌序 fixture。 |
| [test_gate_shoe.py](test_gate_shoe.py) | 射龍門連續牌靴、剩牌與洗牌時機。 |
| [test_gate_taiwan.py](test_gate_taiwan.py) | 射龍門對子拆方向、撞柱、牌靴與交易。 |
| [test_mahjong.py](test_mahjong.py) | 台灣麻將台數、四人流程、點數及操作收據。 |
| [test_payouts.py](test_payouts.py) | 各遊戲派彩與資金守恆。 |
| [test_fairness.py](test_fairness.py) | 受控亂數／牌序下的公平性、分布與結算檢查。 |
| [test_game_settings.py](test_game_settings.py) | 管理員賠率／機率設定、驗證與當局快照。 |
| [test_result_stats.py](test_result_stats.py) | 結算紀錄及統計投影。 |

### 即時連線、恢復與延遲

| 檔案 | 用途 |
| --- | --- |
| [test_realtime.py](test_realtime.py) | SSE、事件通知與 HTTP 並行；提供 Stream 共用 fixture。 |
| [test_presence.py](test_presence.py) | 逾時、暫離、離線移除、回頁恢復及座位處理。 |
| [test_connection_review.py](test_connection_review.py) | 唯讀串流、連線替換、快照與隔離；提供 ReadOnlyStreams fixture。 |
| [test_mobile_recovery.py](test_mobile_recovery.py) | 手機恢復、連線診斷與重送安全。 |
| [test_push_views.py](test_push_views.py) | 牌桌／大廳推播分流、公開模型快取與個人資料隔離。 |
| [test_tower_connections.py](test_tower_connections.py) | 爬塔四選一、操作收據及串流租約。 |
| [test_action_latency.py](test_action_latency.py) | 操作延遲與持續推播的回歸。 |
| [test_game_latency.py](test_game_latency.py) | 牌局操作、資料庫及串流並行延遲。 |
| [test_voice.py](test_voice.py) | 語音頻道資格、WebSocket 協定與有界音訊佇列。 |

### 會所與任務

| 檔案 | 用途 |
| --- | --- |
| [test_income.py](test_income.py) | 被動收益累積、領取與個人資金水位。 |
| [test_upgrades.py](test_upgrades.py) | 會所／設施升級、成本與收益邊界。 |
| [test_clubhouse_speed.py](test_clubhouse_speed.py) | 建築等級帶來的速度加成及上限。 |
| [test_staff.py](test_staff.py) | 員工派遣、領取、時間與重複結算防護。 |
| [test_features.py](test_features.py) | 好友包廂、牌局重播與權限。 |

### 靜態資源與部署保護

| 檔案 | 用途 |
| --- | --- |
| [test_assets.py](test_assets.py) | 圖片白名單、內容雜湊、ETag／304 與非法路徑。 |
| [test_static_artwork.py](test_static_artwork.py) | 插畫白名單、前端展示與靜態路由回歸。 |
| [test_static_cache.py](test_static_cache.py) | CSS／JS／SVG 的 gzip、ETag、重新驗證、退役 URL 與 HTML／API 不快取。 |
| [test_deployment.py](test_deployment.py) | 部署授權、封裝驗證、安全排空、資料保留與回復邊界。 |

- `test_fishing.py`：雙模式釣魚、公開機率、私人漁獲、帳本原子性與20人並行；瀏覽器配套為 `npm run test:fishing`。
