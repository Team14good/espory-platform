# 邱芯彤 的 AI 使用紀錄

格式與等級定義見 [README](README.md)。只在檔尾新增，最新的在最下面。

### 2026-10-30｜需求與設計／spec｜Story 3.2 選手填寫參賽資料（第一段 spec）

- Story／範圍：3.2 第一段（分支 story/3-2，尚未開 PR）
- 工具：Claude Code（Opus 5.5）＋ bmad-build（規劃步驟，前端與 UX 調查交給 Explore 子代理）
- 怎麼用：使用者要求 story/3-2 與 story/3-1 完全獨立；AI 調查後指出 3.2 的參賽資料存在 3.1 才建立的 team_member、入口在 3.1 的 S17，提出三種做法讓使用者選，再依選擇寫 spec
- AI 產出：spec 一份（I/O 與邊界情況表 8 列、驗收條件 4 條、任務 10 項），第二段（依賴 3.1 的部分）寫入 deferred-work
- 人做了什麼：選擇「先做與 3.1 無關的部分，3.1 合併後在同一分支 merge main 再接上」；決定保留約 2,700 tokens 的完整 spec；核准 spec
- 驗證：spec 經人審核後核准
- 問題與修正：AI 一開始直接從 story/3-1 開分支（因為 3.1 未合併），使用者要求獨立後才改從 origin/main 開；AI 調查發現 UX 文件沒有規定上傳進度的樣式、「上場時必須使用這個遊戲 ID」只出現在 epics，改寫進 spec 的設計說明而不是自行假設需求
- 成熟度：L4（固定流程產出 spec，人在 checkpoint 決定範圍與核准）
- 證據：_bmad-output/implementation-artifacts/spec-3-2-player-registration-info.md；commit 未記錄（尚未 commit）

### 2026-10-30｜程式／程式生成｜Story 3.2 選手填寫參賽資料（第一段實作）

- Story／範圍：3.2 第一段（分支 story/3-2，尚未開 PR）
- 工具：Claude Code（Opus 5.5）＋ bmad-build（實作子代理）
- 怎麼用：由不帶對話脈絡的子代理只依 spec 實作，主流程對照 diff 驗收每個任務、驗收條件與 I/O 表每一列的測試，並自己重跑全部測試
- AI 產出：後端 core.storage（存圖片時以 MIME 與檔頭驗證、5 MB 上限、防路徑穿越）、段位驗證函式 rank_score_for、UPLOAD_DIR 設定；前端 Screenshot uploader 元件、S18 參賽資料對話框（手機 Sheet、桌機 Dialog）、檔案檢查函式；新增 2 個後端測試檔、2 個前端測試檔
- 人做了什麼：未記錄（待使用者確認實作子代理自訂的介面文字，見 spec 的 Implementation Notes）
- 驗證：後端 289 個測試通過、覆蓋率 95%（新檔 100%）；mypy、ty、ruff 通過；前端 typecheck、biome 通過，單元測試 185 個通過
- 問題與修正：主流程更新 sprint-status 時用的 python 其實是 Windows Store 的空殼，指令沒有報錯也沒有改檔，主流程從 git diff 為空發現後改用 PowerShell 寫回；子代理發現開發用資料庫的 Alembic 版本停在 story/3-1 的遷移，本分支的 backend 容器起不來，沒有自行修改資料庫，回報給使用者決定
- 成熟度：L4（依 spec 由子代理實作，主流程對照 diff 驗收並自動測試）
- 證據：spec 同上；commit 未記錄（尚未 commit）

### 2026-10-30｜測試／程式審查｜Story 3.2 選手填寫參賽資料（第一段審查與測試）

- Story／範圍：3.2 第一段（分支 story/3-2，尚未開 PR）
- 工具：Claude Code（Opus 5.5）＋ bmad-build 審查步驟（Blind Hunter、Edge Case Hunter、Verification Gap 三個審查子代理）
- 怎麼用：三個審查者平行審 diff，主流程逐項查證後分類為修正、延後或駁回，記在 spec 的 Review Triage Log，修正交回原實作子代理
- AI 產出：審查發現共 27 項；修正 6 組（S18 只在重新開啟時重設表單並補測試、伺服器 415／413 改顯示在截圖欄、上傳中不能換檔、拖檔到預覽列不再讓瀏覽器離開頁面、拖曳外框閃爍、進度 NaN），延後 3 項寫入 deferred-work（更換截圖後刪舊檔、上傳請求大小上限、原始檔名規則），其餘查證後駁回
- 人做了什麼：未記錄（審查分類由 AI 完成，待使用者確認）
- 驗證：修正後後端 289 個測試、前端 190 個單元測試全數通過，lint、typecheck、biome 通過
- 問題與修正：Verification Gap 審查者指出 S18 的 10 個測試都只渲染一次，把重設表單的 effect 整個刪掉也會全部通過；Edge Case Hunter 指出檔案拖到已選取的預覽列時沒有處理，瀏覽器會直接開啟圖片、表單內容遺失；兩者都是實作子代理自己的測試沒抓到，補上修正與測試
- 成熟度：L4（多個獨立審查者加自動測試，主流程查證每項發現）
- 證據：spec 的 Review Triage Log；_bmad-output/implementation-artifacts/deferred-work.md；commit 未記錄（尚未 commit）