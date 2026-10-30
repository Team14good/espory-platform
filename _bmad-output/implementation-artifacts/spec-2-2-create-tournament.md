---
title: 'Story 2.2（第一階段）：建立賽事的後端'
type: 'feature'
created: '2026-10-30'
status: 'done'
baseline_commit: 'f64474cf73b26840e5386cb5a5b26514bedc76ff'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/contracts/tournaments.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 還沒有 Tournament 資料表，C 的報名（3.x）與 D 的對戰表、賽程（4.x、5.x）都無法接上真資料；主辦方也無法建立賽事。

**Approach:** 建立 Tournament（含遊戲設定快照）、建立賽事 API 與驗證、worker 到時自動開放報名，並依 `contracts/tournaments.md` 提供 2.2 負責的公開函式。

## Boundaries & Constraints

**Always:**
- 只有主辦方（`Account.is_organizer`）能建立賽事；主辦方只能讀自己的賽事（以 `core.authz.ensure_tournament_owner` 判斷）。
- 欄位：名稱、遊戲、名額、報名開始、報名截止、優先期長度、開賽時間、每輪間隔、棄權時限、申訴期、先發人數、替補人數、BO、直播連結（選填）。
- 預設值：棄權 15 分鐘、申訴 30 分鐘、優先期 24 小時；先發、替補、BO 未填時帶入遊戲的值。
- 拒絕並指出欄位（422）：報名開始晚於（含等於）報名截止；報名截止晚於開賽時間；優先期結束（報名開始＋優先期）晚於報名截止；名額 < 2；棄權 < 15；申訴 < 30；BO 不是 1、3、5、7；每輪間隔 < 棄權＋BO × 每局預估時間＋申訴（訊息寫出最小間隔，例：「每輪間隔至少 85 分鐘」）；直播連結不是 http／https。遊戲不存在回 404 `GAME_NOT_FOUND`。
- 建立時把遊戲的名稱、每局預估時間、比分型態、段位對照表與（可能被修改過的）先發、替補、BO 複製進賽事快照；之後只讀快照（AD-12）。
- 期中一律存 `mode=campus`，API 不接受模式欄位；`invite_token` 不建立。
- 報名開始已到 → `open`，否則 `upcoming`。寫 `tournament.created` 操作紀錄（`tournament_id` 為新賽事）。
- worker 工作：找一筆 `upcoming` 且報名開始已到的賽事，`lock_tournament` 後重新檢查，經 `transition_tournament` 轉 `open`，操作者為 system（`actor_id=None`）；重複執行沒有副作用。
- 狀態只能經 `transition_tournament` 改，允許的轉換依 `contracts/tournaments.md`〈三〉；非法轉換 409 `TOURNAMENT_INVALID_TRANSITION`。
- `audit_log.tournament_id` 加上外鍵到 `tournament.id`。

**Never:**
- 不做 S25、S26、S27 畫面（第二階段，見 Decisions）。
- 不做賽事模式選項、自訂模式、賽事報名連結（3.10）、分輪 BO（2.3）、修改與取消賽事（2.5、2.6）。
- 程式中不依遊戲名稱或 id 寫分支（AD-18）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 建立（報名已開始） | 合法表單，報名開始 ≤ 現在 | 201，`status=open`，快照與遊戲一致；寫 `tournament.created` | N/A |
| 建立（報名未開始） | 報名開始 > 現在 | 201，`status=upcoming` | N/A |
| 虛構第三款遊戲 | 先發 3、替補 0、BO 7、`win_loss` 的遊戲 | 快照的值與該遊戲一致（2.1 移來的 AC） | N/A |
| 改遊戲預設值 | 建立後平台管理員修改遊戲 | 既有賽事快照不變（2.1 移來的 AC） | N/A |
| 主辦方改人數與 BO | 先發 4、BO 5 | 快照存修改後的值 | N/A |
| 每輪間隔不足 | 每局 40、BO1、棄權 15、申訴 30、間隔 80 | 拒絕 | 422「每輪間隔至少 85 分鐘」 |
| 日期順序錯 | 報名截止晚於開賽 | 拒絕 | 422，`registration_end` |
| 優先期超過截止 | 報名開始＋優先期 > 報名截止 | 拒絕 | 422，`priority_hours` |
| 直播連結不合法 | `ftp://…` | 拒絕 | 422，`livestream_url` |
| 開賽在過去 | 開賽時間 ≤ 現在 | 拒絕 | 422，`start_at` |
| 報名截止在過去 | 報名截止 ≤ 現在 | 拒絕 | 422，`registration_end` |
| 名額超過 128 | 名額 200 | 201，照常建立（提醒由第二階段畫面處理） | N/A |
| 名額過大 | 名額 > 2147483647 | 拒絕 | 422，`capacity` |
| 非主辦方 | 一般帳號建立賽事 | — | 403 `ORGANIZER_REQUIRED` |
| 讀別人的賽事 | 主辦方 A 讀主辦方 B 的賽事 | — | 403 `TOURNAMENT_OWNER_REQUIRED` |
| worker 開放報名 | `upcoming`，報名開始已到 | 轉 `open`，寫 `tournament.status_changed`（actor 空） | 再執行一次不變、不重複寫紀錄 |
| 非法轉換 | `upcoming` → `finished` | — | 409 `TOURNAMENT_INVALID_TRANSITION` |

## Decisions

- 2026-10-30（使用者）：本 Story 拆兩階段。第一階段只做後端，10/31 前合併讓 C、D 接上；S25、S26、S27 畫面等 A 的 1.8 合併後在第二階段完成。
- 2026-10-30（使用者）：開賽時間與報名截止必須晚於現在（422，指出欄位）；報名開始可以是過去，建立後立即為 `open`。
- 2026-10-30（使用者）：名額 128 是「提醒門檻」不是上限。後端只檢查 ≥ 2 與不超過資料庫整數上限（超過回 422，不是 500）；S26 畫面（第二階段）在名額超過 128 時彈出「名額超過 128 隊，請確認沒有輸入錯誤」，主辦方確認後仍可建立。（同日先改為上限 128，再改為本條）

</frozen-after-approval>

## Code Map

- `backend/app/modules/tournaments/models.py` -- 已有 `ScoreType`、`TournamentMode`、`TournamentStatus`、`GameTitle`、`RankTier`、`GameRead`；新增 `Tournament`（`__tablename__="tournament"`，`game_snapshot` JSONB：`game_name`、`starters`、`substitutes`、`bo`、`game_minutes`、`score_type`、`rank_tiers`）、`TournamentCreate`、`TournamentRead`（欄位照 `contracts/tournaments.md`〈一〉，快照欄位攤平）
- `backend/app/modules/tournaments/{repository,service,router}.py` -- 2.1 的寫法（router commit、`_flush_*` savepoint、只記變動欄位的 audit）；`service.get_game` 讀遊戲
- `backend/app/core/audit.py:22-23` -- `tournament_id` 外鍵由本 Story 補上；`actor_id=None` 表示系統
- `backend/app/core/` -- 新增 `authz.py`：`ensure_tournament_owner(tournament, account_id)`，不查資料庫（AD-10）
- `backend/app/modules/identity/deps.py:49-60` `require_platform_admin`／`PlatformAdmin` -- 照寫 `require_organizer`／`Organizer`（403 `ORGANIZER_REQUIRED`）；只新增，不改既有函式
- `backend/app/worker/jobs.py:15-33` -- `Job = Callable[[Session], bool]`，一次處理一筆、不 commit；新工作加進 `JOBS`；`tests/worker/test_email_pipeline.py:27` 檢查註冊順序，要一起更新
- `backend/app/core/events.py:58` `publish` -- 本 Story 不發事件
- `backend/tests/conftest.py:92,111,125` -- `session_factory`、`FrozenClock`、`frozen_clock`（2026-10-18 11:00 UTC）
- `backend/tests/helpers.py` -- `make_account(admin=)`；需要建主辦方帳號時加 `organizer` 參數
- `backend/app/alembic/versions/c2a7d4e9f1b3_story_2_1_game_title.py` -- 新遷移的 `down_revision`。A 的 1.7（`c7e2a4d9b8f1`）也接在 1.5 之後，後合併者要改 `down_revision`
- `contracts/tournaments.md` -- 函式名稱、簽名、錯誤代碼、狀態轉換表的依據

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/tournaments/models.py`、`backend/app/alembic/versions/<rev>_story_2_2_tournament.py` -- Tournament 表（含 `mode`、`status` 字串欄位、`game_id` FK、`organizer_id` FK、`game_snapshot` JSONB）；`audit_log.tournament_id` 外鍵
- [x] `backend/app/core/authz.py`、`backend/app/modules/identity/deps.py` -- `ensure_tournament_owner`、`Organizer`
- [x] `backend/app/modules/tournaments/{repository,service}.py` -- `create_tournament`、`get_tournament`、`lock_tournament`、`transition_tournament`、`ensure_accepting_registrations`、`ensure_accepting_scores`、`bo_for_round`、`list_organizer_tournaments`、`open_due_registration`（worker 用）
- [x] `backend/app/modules/tournaments/router.py` -- `GET /games`（主辦方選遊戲用，`Organizer`）、`POST /organizer/tournaments`、`GET /organizer/tournaments`、`GET /organizer/tournaments/{tournament_id}`
- [x] `backend/app/worker/jobs.py` -- `open_registrations` 工作加進 `JOBS`
- [x] `backend/tests/tournaments/test_tournaments.py`、`backend/tests/tournaments/test_transitions.py`、`backend/tests/worker/test_open_registration.py` -- I/O Matrix 每列至少一個測試
- [x] `frontend/src/client/` -- `bash scripts/generate-client.sh`
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- 刪除 2.1 移來的「快照 AC」那一項（本 Story 處理完）

**Acceptance Criteria:**
- Given 主辦方建立的賽事，when 其他模組呼叫 `get_tournament`、`lock_tournament`，then 回傳的欄位與 `contracts/tournaments.md` 的 `TournamentRead` 一致
- Given 本 spec，when 執行 Verification 的所有指令，then 全部通過

## Implementation Notes

## Spec Change Log

## Review Triage Log

第一輪（2026-10-30）：Blind Hunter 13 筆、Edge Case Hunter 9 筆、Verification Gap 1 筆。

| # | 來源 | 發現 | 判定 | 處理 |
|---|------|------|------|------|
| 1 | Gap、Blind | worker 鎖定後重新檢查（候選已不是 `upcoming`）的分支沒有測試 | medium：拿掉重新檢查也不會有測試失敗；真的競態時第二個 worker 會拋 409、中斷該輪 | patch |
| 2 | Blind | 沒有任何工作把 `open` 轉成 `closed`，`ensure_accepting_registrations` 只看狀態 | medium：依介面約定〈三〉由 C 的 3.6 在截止時轉換；3.6 完成前截止後仍可報名 | defer |
| 3 | Blind | 建立賽事以 `FOR UPDATE` 鎖遊戲，同一款遊戲的建立互相排隊 | low：改成 `FOR SHARE` 是直接修正 | patch |
| 4 | Blind | 主辦方的遊戲清單在 `GET /games`，2.4 可能要公開的同名路徑 | low：2.4 公開的是賽事列表，不是遊戲；路徑是 spec 定的 | 不處理 |
| 5 | Blind | `audit_log.tournament_id` 外鍵在既有資料庫可能升級失敗 | false：2.2 之前正式程式不寫 `tournament_id`，只有每次重建的測試資料庫有；開發資料庫查詢為 0 筆 | 不處理 |
| 6 | Blind、Edge | 資料表沒有 CHECK（狀態、模式、名額、時間順序） | low：只有繞過 service 的寫入會遇到；與 2.1 的判斷一致 | 不處理 |
| 7 | Blind | 產生的 client 沒有 403、404 的錯誤型別 | low：既有 API 都是同樣寫法，第二階段畫面以 `detail.code` 處理 | 不處理 |
| 8 | Blind | 建立時優先期可能已經結束 | low：使用者決定報名開始可以是過去，優先期已過是自然結果；之後直接進入先搶期 | 不處理 |
| 9 | Blind | 欄位錯誤與日程錯誤分兩次回傳 | low：畫面在第二階段，前端可先做同樣的檢查 | 不處理 |
| 10 | Blind | 權限測試缺口：非主辦方讀單一賽事、未登入的 GET；`test_upcoming_to_finished_is_forbidden` 是循環斷言 | low：測試沒有證明 service 行為 | patch |
| 11 | Blind | 時區轉換只測 `start_at` | low：`registration_start` 決定開放狀態與優先期結束 | patch |
| 12 | Blind | spec 與 sprint 狀態不一致、Spec Change Log 空白 | false：sprint 依團隊慣例分階段維持 in-progress；128 的變更是實作前由人修改，不是審查迴圈 | 不處理 |
| 13 | Blind | 缺 AI 使用紀錄、PR 說明未列出動到的他人模組 | false：在 bmad-build 完成與開 PR 時處理 | 不處理 |
| 14 | Blind | 候選查詢沒有 `SKIP LOCKED`，被鎖住的賽事會卡住整輪 worker | low：持有賽事鎖的都是短交易 | 不處理 |
| 15 | Edge | 年份極端的時間轉 UTC 溢位回 500 | low：一般輸入不會出現，修正要新增防護 | 不處理 |
| 16 | Edge | 某一筆賽事每次都失敗時，後面的賽事永遠不會開放 | low：需要資料已損壞才會發生 | 不處理 |
| 17 | Edge | worker 停機期間錯過，報名截止後才開放報名 | low：worker 長時間停機才會發生，且 3.6 會隨即截止 | 不處理 |
| 18 | Edge | 狀態欄位有列舉以外的值會拋 ValueError | low：只有繞過 service 的寫入 | 不處理 |
| 19 | Edge | 直播連結中間有空白仍被接受 | low：主辦方手動輸入少見，修正要新增檢查 | 不處理 |
| 20 | Edge | 棄權＋BO×每局＋申訴超過整數上限時，錯誤要求的間隔無法輸入 | low：需要極端的遊戲設定 | 不處理 |
| 21 | Edge | 只載入 core 的腳本 flush 操作紀錄時找不到 `tournament` 表 | false：實測只 import identity 的情況下外鍵可解析（`app.modules` 會註冊所有資料表） | 不處理 |
| 22 | Edge | 已取消的賽事再取消回 409，與約定「任何非 finished → cancelled」字面不符 | low：取消屬於擱置的 2.6，屆時再定 | 不處理 |
| 23 | Edge | 送 `mode=custom` 被忽略而回 201 | false：spec 明定 API 不接受模式欄位，一律存 `campus`；忽略與實作說明一致 | 不處理 |

## Verification

**Commands:**
- `docker compose up -d --build --wait` -- 五個服務 healthy
- `docker compose exec backend bash scripts/test.sh` -- 全部通過，覆蓋率達門檻
- `docker compose exec backend bash scripts/lint.sh` -- 無錯誤
- `docker compose exec frontend bun run --filter frontend build`、`docker compose exec frontend bun run --filter frontend typecheck` -- 通過
