# API 導覽

這是程式碼導覽，不宣稱是完整 OpenAPI schema。精確欄位與錯誤請以 server.py、各模組驗證及 test_*.py 為準。

所有寫入使用 JSON、Content-Type: application/json 與 X-Requested-With: PokerClub；伺服器檢查 Origin。登入採 HttpOnly Cookie，正式環境啟用 Secure、SameSite=Strict，不把登入 token 存進 localStorage。

## 主要入口

| 方法 | 路徑 | 作用 |
| --- | --- | --- |
| GET | /api/bootstrap | 公開啟動資訊 |
| POST | /api/register、/api/login、/api/logout | 帳號工作階段 |
| GET | /api/online/lobby | 登入者的大廳模型 |
| GET | /api/online/rooms/:id | 含個人私有視圖的房間 |
| GET | /api/online/events?presence=client&client=:client&room=:id | 房間 SSE；大廳省略 room |
| POST | /api/online/rooms | 建桌並入座 |
| POST | /api/online/rooms/:id/join | 自訂 buy_in 入座 |
| POST | /api/online/rooms/:id/start | 開局；21 點為當局確認下注 |
| POST | /api/online/rooms/:id/action | 帶 hand_id／turn_id 的合法遊戲動作 |
| POST | /api/online/rooms/:id/leave、rebuy、return、close | 座位與桌生命週期 |
| POST | /api/online/rooms/:id/invite | 兌換私人包廂資格 |
| POST | /api/online/rooms/:id/wager | 21 點修改下注並取消確認 |
| POST | /api/online/presence | 在線與自動回桌 |
| GET | /api/online/rooms/:id/replay/:number | 已結束手牌的可見重播 |
| GET | /api/profile、/api/members/:id | 個人設定／公開名片 |
| POST | /api/profile、/api/profile/password | 修改個資／密碼 |
| GET | /api/profile/avatar/:id/:revision.png | 受保護頭像 |
| GET／POST | /api/wallet/transfers | 轉帳歷史／點數轉帳 |
| GET | /api/wallet/recipients?search=:query | 搜尋可收款帳號 |
| POST | /api/wallet/claim、/api/wallet/hourly | 每日／每小時補給 |
| POST | /api/wallet/passive、/api/wallet/clubhouse-upgrade | 收會所收益／升級 |
| GET | /api/clubhouse/staff | 員工與任務狀態 |
| POST | /api/clubhouse/hire、dispatch、collect | 僱用、派遣、收取 |
| POST | /api/club/buy、/api/club/equip | 收藏購買／裝備 |
| POST | /api/social/rooms/:id/chat | 席外也可發送桌內文字 |
| POST | /api/social/rooms/:id/voice/join、leave、ping | 語音頻道工作階段 |
| GET | /api/social/voice/state?room=:id | 語音成員和連線狀態 |
| GET upgrade | /api/social/voice/socket?room=:id&session=:session | WSS PCM 音訊 |
| GET | /api/admin/accounts、/api/admin/game-settings | 管理員讀取 |
| POST | /api/admin/adjustments、/api/admin/account-action | 點數增減／帳號狀態 |
| POST | /api/admin/game-settings、/api/admin/game-settings/preview | 發布／試算遊戲設定 |

/ready 路由為舊版相容入口，會明確拒絕；不要在設計新按鈕時重新使用。

## 範例：21 點確認下注

~~~json
{
  "stake": 100,
  "expected_hand_number": 1,
  "expected_settings_revision": 0,
  "operation_id": "example_blackjack_confirm_0001",
  "revision": 3
}
~~~

以上只是合成範例；hand_number、設定版本、房間 revision 應取最新狀態。第一位確認只登記，不先扣點；最後一位有效參與者確認後才發牌。下一局需重新確認。修改下注會取消自己的確認。

## 範例：回合動作

~~~json
{
  "action": "stand",
  "hand_id": "current-hand-id",
  "turn_id": "current-turn-id",
  "operation_id": "example_blackjack_stand_000001",
  "revision": 5
}
~~~

operation_id 限 16–80 字元英數、底線或連字號。網路逾時應確認原編號，不能自行產生新操作。不是每個端點都用相同回執表：轉帳、頭像、會所與收藏各有自己的資料契約。

SSE 的 state 是個人化 JSON；ping 只是保活，不得把它當新一手。auth 事件表示登入失效。HTTP 回覆和 SSE 誰先到都可能，畫面需以 revision／世代避免倒退，並核對 accepted_operations。

## 步步為營棋桌

登入後 GET `/api/blocade` 回傳目前棋桌、大廳、最近 20 桌、錢包；`?room=桌號` 可觀戰與查看已結束對局。

POST `/api/blocade/{create,join,start,act,leave}` 全部需要 operation_id。create 另需 capacity（2／4）、stake（0–10,000 整數）及 bots（boolean）；其餘需 room_id。act 還需目前 ply，以及 action：`{"kind":"move","pos":[列,欄]}`、`{"kind":"wall","wall":["h或v",列,欄]}`；全部從 0 起算。暫無合法移動時可送 `{"kind":"wait"}`。不得自行送 winner、payout 或棋子座標覆蓋狀態。

create／join 當下扣除同額入場籌碼並納入 in_play。start 只有桌主可做：允許 bots 時才會以系統出資補滿空位；不允許時需真人到齊。開局前 leave 全退，桌主退出由下一位真人接任；開局後 leave 認輸、移除棋子但保留牆。冠軍取整池，未抽水，派彩與狀態同一 SQLite 交易提交。機器人獲勝由系統收回獎池。

操作回執保存在 blocade_operations，同編號同內容重送只回傳既有結果；舊 ply、錯誤玩家、非法牆與逾時回合均拒絕。前端預覽不送出動作，網路結果不明時持續保存原回執並停用新操作。棋局讀取每 2 秒一次，等候大廳每 5 秒，無重疊讀取，切頁或操作會取消舊讀取。

步步為營 `POST /api/blocade/rematch` 接受 `room_id` 與 `operation_id`。僅原桌成員可於結束後發起；同一原桌只連到同一張新桌，沿用人數、賭注與機器人設定。每人點擊才保留自己的入場點數，重送不重扣；不自動開始。GET 的 `room.rematch` 提供下一桌 id/status/count/joined，原桌歷史不修改。
