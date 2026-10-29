# 蘇采羚 的 AI 使用紀錄

格式與等級定義見 [README](README.md)。只在檔尾新增，最新的在最下面。

### 2026-10-29｜需求／設計｜Story 2.1 spec：拆出後端第一階段

- Story／範圍：2.1（PR #9）
- 工具：Claude Code（Opus 5.5）＋ bmad-build
- 怎麼用：以 bmad-build 讀 epic-2-context 與既有程式，產生 spec，列出需要人決定的問題
- AI 產出：`spec-2-1-game-settings-and-school-list.md`（I/O Matrix 10 列）；`deferred-work.md` 新增 2 筆（第二階段畫面、移到 2.2 的快照驗收）
- 人做了什麼：回答 2 個 Open Questions：後台版面（A 的 1.8）還沒好，決定先做後端、畫面等 1.8；需要 Tournament 的兩條 AC 移到 2.2 驗收
- 驗證：spec 經人核准後鎖定 `<frozen-after-approval>`
- 問題與修正：第一版 spec 把前後端一起寫，約 3400 tokens，超過 bmad-build 建議的 1600；AI 依 SCOPE STANDARD 指出後，配合人的決定改成只做後端，約 2200 tokens
- 成熟度：L3（AI 依 epic context 與既有程式產出 spec，範圍與驗收由人決定）
- 證據：`_bmad-output/implementation-artifacts/spec-2-1-game-settings-and-school-list.md` 的 Decisions

### 2026-10-29｜程式／程式生成｜Story 2.1 第一階段：遊戲設定與學校清單的後端

- Story／範圍：2.1（PR #9）
- 工具：Claude Code（Opus 5.5）＋ bmad-build（實作子代理）
- 怎麼用：核准 spec 後，由不帶對話脈絡的實作子代理只依 spec 實作
- AI 產出：`game_title`、`rank_tier` 兩張表與遷移檔；遊戲 API 4 支（`/admin/games`）、學校 API 2 支（`/admin/schools`）；公開函式 `tournaments.service.get_game()` 供 2.2 使用；共用測試工具 `tests/helpers.py`；重新產生 `frontend/src/client`
- 人做了什麼：核准 spec；決定分兩階段
- 驗證：後端 319 個測試全過、覆蓋率 95%；`scripts/lint.sh`（mypy、ty、ruff）、前端 build 與 typecheck 通過
- 問題與修正：子代理第一次執行時對話中斷，沒有寫出任何程式，以 `git status` 確認後讓它接續完成。另外 uv 在 Windows 安裝 Python 3.14 時回報連結錯誤，AI 確認直譯器本身可用後改以 `UV_PYTHON` 指定，bmad-build 才能執行
- 成熟度：L4（固定流程：spec → 子代理實作 → 自動測試，人只在 checkpoint 決策）
- 證據：PR #9、spec 的 Implementation Notes、commit 未記錄

### 2026-10-29｜測試／程式審查｜Story 2.1 三個審查者審查與修正

- Story／範圍：2.1（PR #9）
- 工具：Claude Code（Opus 5.5）＋ bmad-build（Blind Hunter、Edge Case Hunter、Verification Gap 三個審查子代理）
- 怎麼用：三個審查者各自只看 diff 審查，主代理逐筆查證後分類為 patch、defer 或不處理
- AI 產出：17 筆發現（Blind Hunter 14、Edge Case Hunter 3、Verification Gap 0）；4 筆修正、1 筆延後、12 筆不處理（逐筆理由記在 spec 的 Review Triage Log）；新增 4 個測試
- 人做了什麼：未記錄（審查分類由 AI 完成，待人在 PR 審查時確認）
- 驗證：修正後後端測試由 315 個增為 319 個，全部通過，覆蓋率 95%
- 問題與修正：審查抓到實作的錯誤：段位名稱的驗證不分大小寫，但資料庫唯一限制區分大小寫，繞過 API 的寫入可存入「Diamond」與「diamond」，改成 `lower(btrim(name))` 唯一索引；重名判斷以錯誤訊息字串比對索引名稱，前綴相同的索引也會命中，改成比對 `diag.constraint_name`；競態與 404 測試沒有檢查錯誤代碼與「沒有寫入操作紀錄」。另有 1 筆既有問題（Pydantic 內建 422 訊息是英文）記進 `deferred-work.md`
- 成熟度：L4（多個審查者＋主代理查證＋測試驗證，人只在 PR 決策）
- 證據：spec 的 Review Triage Log、`deferred-work.md`