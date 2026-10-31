# 邱芯彤 的 AI 使用紀錄

格式與等級定義見 [README](README.md)。只在檔尾新增，最新的在最下面。

### 2026-10-30｜需求／驗收條件｜Story 3.1 建立隊伍與邀請隊員（spec）

- Story／範圍：3.1（分支 story/3-1，尚未開 PR）
- 工具：Claude Code（Opus 5.5）＋ bmad-build
- 怎麼用：以 bmad-build 讀 epic-3 context、tournaments／competition 介面約定與期中文件 B 的資料表，派子代理調查程式碼後產生 spec
- AI 產出：spec 一份（I/O 與邊界情況表 11 列、驗收條件 6 條、任務 11 項），並整理出 3 個需要人決定的問題
- 人做了什麼：決定建隊入口只做 Dialog 元件、「我的隊伍」對所有登入帳號顯示、隊名 1～30 字且同賽事不可重複、保留超長 spec；開工前決定不合併 story/2-2、改用約定介面與測試替身、不用 factory／seed
- 驗證：spec 經人審核後核准
- 問題與修正：AI 調查時發現 tournament 資料表尚未存在（2.2 未合併）、identity 不能呼叫 registration，這兩點規劃文件沒寫，改列為決策題讓人選擇，沒有自行假設
- 成熟度：L4（固定流程產出 spec，人只在 checkpoint 決策）
- 證據：_bmad-output/implementation-artifacts/spec-3-1-create-team-and-invite-members.md；commit 未記錄（尚未 commit）

### 2026-10-30｜程式／程式生成｜Story 3.1 建立隊伍與邀請隊員（實作）

- Story／範圍：3.1（分支 story/3-1，尚未開 PR）
- 工具：Claude Code（Opus 5.5）＋ bmad-build（實作子代理）
- 怎麼用：由不帶對話脈絡的子代理只依 spec 實作，主流程再對照 diff 驗收每個任務與驗收條件
- AI 產出：後端 registration 三張資料表與一支遷移檔、5 個 API、報名狀態轉換、4 個公開函式；前端 4 個元件（Invite link field、Roster list、Registration status card、建立隊伍 Dialog）與 3 個頁面（S17、S19、S12）；身分切換器加入「我的隊伍」
- 人做了什麼：審核 spec 決策；確認動到 A 的 identity 模組只新增不改既有邏輯，需在 PR 說明列出
- 驗證：後端 369 個測試通過、覆蓋率 95%；mypy、ty、ruff 通過；前端 typecheck、biome、build 通過，單元測試 184 個通過
- 問題與修正：主流程驗收時發現子代理做的 TeamRead 少了期中設計文件要求的「隊員帳號與角色」（其他模組靠它判斷隊長），由主流程補上並加測試；子代理自行發現 S12 路由若照 spec 命名會因 /me 沒有 Outlet 而不顯示，改用 me_.teams.tsx
- 成熟度：L4（依 spec 由子代理實作，主流程對照 diff 驗收並自動測試）
- 證據：spec 同上；commit 未記錄（尚未 commit）

### 2026-10-30｜測試／程式審查｜Story 3.1 建立隊伍與邀請隊員（審查與測試）

- Story／範圍：3.1（分支 story/3-1，尚未開 PR）
- 工具：Claude Code（Opus 5.5）＋ bmad-build 審查步驟（Blind Hunter、Edge Case Hunter、Verification Gap 三個審查子代理）
- 怎麼用：三個審查者平行審 diff，主流程逐項查證後分類為修正、延後或駁回，記在 spec 的 Review Triage Log
- AI 產出：審查發現共約 35 項；修正 5 項（隊名查重改由資料庫轉小寫、補「先鎖賽事再檢查」順序與使用鎖定值的測試、補我的隊伍排序與系統操作者測試、S19 已在隊伍時加「查看我的隊伍」、加入後更新邀請預覽），延後 2 項寫入 deferred-work（2.4 的建隊入口與回賽事頁連結、2.2 合併後移除 raising=False 替身），其餘查證後駁回
- 人做了什麼：未記錄（審查分類由 AI 完成，待使用者確認）
- 驗證：修正後後端 369 個測試、前端 184 個單元測試全數通過，lint 與 build 通過
- 問題與修正：主流程誤判報名狀態圖沒有「已參賽 → 取消資格」，要求子代理移除；子代理查證期中文件 B 第 590 行後拒絕修改，主流程重新查證確認是自己只讀到第 589 行而漏看，改判為誤報並刪除錯誤的 deferred 項目。另外，Verification Gap 審查者指出測試替身只記錄「有呼叫鎖」，順序寫錯也不會被抓到，因此補了測試
- 成熟度：L4（多個獨立審查者加自動測試，主流程查證每項發現）
- 證據：spec 的 Review Triage Log；_bmad-output/implementation-artifacts/deferred-work.md；commit 未記錄（尚未 commit）
