# 資料模型與點數

SQLite 以 foreign_keys=ON、journal_mode=WAL 執行。多數 schema 由各模組 initialize／schema 做可重入遷移；首次啟動會建立空資料庫。正式資料不在本程式庫。

## 關聯概觀

~~~mermaid
erDiagram
  users ||--o{ auth_sessions : authenticates
  users ||--o| wallets : owns
  users ||--o{ wallet_ledger : records
  users ||--o| member_profiles : displays
  users ||--o| account_states : moderates
  users ||--o{ poker_operations : deduplicates
  poker_rooms ||--o{ poker_hands : settles
  poker_hands ||--o{ poker_results : pays
  users ||--o{ poker_results : participates
  poker_rooms ||--o{ replay_steps : replays
  users ||--o| club_income : accrues
  users ||--o{ staff_roster : hires
  users ||--o{ staff_jobs : dispatches
  users ||--o{ point_transfers : transfers
~~~

poker_rooms.state 是房間 JSON 狀態，含當前手牌與伺服器私有牌堆；不是把座位逐一正規化成 SQL 表。poker_rooms 同時有 status／revision 等查詢欄位，由 online.save 同步。私人包廂與 21 點確認狀態也在房間 JSON。

## 表群與擁有模組

| 表群 | 主要表 | 模組 |
| --- | --- | --- |
| 登入與歷史帳本 | users、auth_sessions、settings、games、entries、audit | server.py |
| 房間、回執與歷史 | poker_rooms、poker_hands、poker_results、poker_sessions、poker_presence、poker_operations | online.py |
| 統計投影 | result_facts、player_result_totals | result_stats.py |
| 錢包與移轉 | wallets、wallet_meta、wallet_ledger、point_transfers | wallet.py、transfers.py |
| 個人資料與停用 | member_profiles、account_states、profile_operations、admin_account_events | member_accounts.py |
| 管理員 | club_admins、admin_grants、admin_adjustments | club_admin.py |
| 會所／資金軌跡 | club_income、income_claims、income_upgrades、wealth_accounts、wealth_events | clubhouse.py |
| 員工 | staff_roster、staff_jobs、staff_operations | clubhouse.py |
| 收藏與任務 | cosmetic_items、cosmetic_equipped 及任務資料 | rewards.py |
| 訊息與頻道 | room_chat、voice_members、voice_signals | social.py |
| 重播／快取版本 | replay_steps、view_versions | club_features.py、view_cache.py |
| 遊戲設定 | game_settings、game_settings_audit | game_settings.py |

## 錢包到牌桌

~~~mermaid
flowchart LR
  A["wallets.balance"] -->|"join／rebuy，同交易扣款"| B["seat.stack"]
  B -->|"行動扣點"| C["hand contribution／底池"]
  C -->|"規則結算"| B
  B -->|"離桌結算後退款一次"| A
  A -->|"配對流水"| D["另一帳號錢包"]
~~~

總點數的守恆檢查須合計：錢包餘額、未關閉桌的座位籌碼、進行中已投入金額及各桌虛擬莊家庫存。補給、管理員調整、會所收益等外部增減要能由流水解釋。只比錢包前後餘額會漏算桌上籌碼。

轉帳的扣款與入帳要同一交易，且共用轉帳識別；管理員不能直接拿走牌桌底池。會所收益與補給是資金流入，不應假裝成打牌淨獲利；資金百分比圖應保留這個區別。

## 隱私與回放

- 完整 state／牌堆只在伺服器；API 使用各引擎的 public_view 過濾。
- 德州只公開自己的底牌與規則允許的攤牌；大老二、麻將不公開他人未出的牌。
- 21 點玩家手牌本來就是同桌公開資訊，莊家未翻底牌維持 None。
- 重播分公共與玩家私有快照，只開放已結束牌局，讀取時仍按帳號過濾。
- 頭像由版本化受保護端點提供；推播不用把完整 PNG 重傳。
- 刪除帳號採停用與匿名化並保留交易稽核，不是直接 SQL DELETE 連帶刪掉結算。
- 語音資料表僅存資格與成員等 metadata，音訊幀不存入資料庫。

資料遷移應可重入、保留既有設定與餘額。協作者測試用自己的臨時資料，不能提交正式 DB、截圖玩家資訊或原始營運日誌。
