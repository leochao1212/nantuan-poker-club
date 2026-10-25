# 牌桌操作流程審查與修正

本次保留現行金色牌室、美術、人物牌與遊戲規則，改善已存在的導航、確認與回饋。範圍為十一款遊戲共用介面，以及保留座位後的大廳／功能頁回桌入口。

## 方法與來源

已安裝至本機 git 忽略的 .agents/skills，不加入正式網站或部署映像：

- [Anthropic Design Critique](https://github.com/anthropics/knowledge-work-plugins/tree/33d3dea41a341b341d4f5da2e8801ae0c89be2b8/design/skills/design-critique)：可用性、層級、步驟、一致性。
- [Anthropic UX Copy](https://github.com/anthropics/knowledge-work-plugins/tree/33d3dea41a341b341d4f5da2e8801ae0c89be2b8/design/skills/ux-copy) 與同版本 design-system：動作名稱、後果、狀態與元件契約。
- [Impeccable](https://github.com/pbakaus/impeccable/tree/936867543ac2576920d663cc9803597f6044f3ac/.agents/skills/impeccable)：採現有產品的 Operate／Clarify／Harden／Adapt 指引，已執行 context 與機械 detector；本次不是其獨立 critique 命令。
- [Vercel Web Design Guidelines](https://github.com/vercel-labs/agent-skills/tree/063bee94c3f4df8453406c830b0a7df0f2860278/skills/web-design-guidelines)：採實際操作連結、可讀名稱、安全確認、焦點與手機觸控規範；審查時重新取得 [規範](https://github.com/vercel-labs/web-interface-guidelines/blob/main/command.md)。
- 現有 UI/UX Pro Max 的 navigation/back behavior 查詢補充導航一致性。

## 主要發現

| 原問題 | 影響 | 修正 |
| --- | --- | --- |
| 手機工具鈕全部縮成圖示，離桌也看不到文字 | 不易發現，可能誤認登出 | 離桌固定有文字；回大廳也改為文字連結 |
| 頂端與底部重複離桌，底部混有結束牌桌 | 玩家需分辨相似操作 | 共用標題列唯一離桌；房主結束收進管理選單 |
| 回大廳不等於離桌，功能頁缺少保留座位提示 | 不知道自己是否仍在玩或如何回桌 | 共用目前牌桌提示與回桌／查看結算入口 |
| 多款遊戲共用一段離桌警語，混列其他遊戲後果 | 難以判斷自己的局會如何處理 | 依當下遊戲／是否局中顯示精確後果 |
| 收據未確認時仍可離開原畫面 | 原操作留在另一桌，無法清楚恢復 | 導航暫留原桌、確認同一收據；不改後端交易 |
| 提示插在主動作前、手機押注提示遠離固定按鈕 | 等待時按鈕移位、回饋不易找到 | 回饋移到動作後；固定押注列預留狀態區 |

保留現有優點：同頁路由、背景恢復、共享語音、冪等收據、圖像按需解碼、手牌辨識、各遊戲合法動作均沿用。

## 已完成元件狀態

- TableHeading：觀戰、入座、離桌結算中、等待中的房主、送出中。
- CurrentTableNotice：保留座位／安排離桌；各功能頁可回桌。
- ConfirmDialog：取消與 Escape、明確動作、預設安全焦點、確認前驗證當下桌號。
- ActionFeedback：送出、成功、拒絕、結果未知與同收據確認；按鈕位置保留。

## 驗證與界線

使用 tests/browser/table-journeys.cjs 的完整旅程，以及現行 layout、cards、reveal、motion、limits、smoke 回歸；全部為合成帳號與隔離資料。至少 320／393／768／844 橫向／1366px，含 Chromium 與 WebKit；不宣稱實體手機或真人麥克風測試。

Impeccable 機械掃描提出的米色背景、跑馬燈、光暈與紋理屬既有美術建議，保留已核准風格與使用者要求的可暫停警語，不為通過偏好掃描而改主題。此掃描不代表操作旅程或所有無障礙規範自動合格。

後續頁面設計沿用 DESIGN-SYSTEM 的同一組狀態與用語，不增加另一層主題 CSS 或通用準備步驟。派彩、點數、回合規則、後端與連線傳輸不在本次修改範圍。
