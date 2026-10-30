---
title: 'Story 2.1（第一階段）：遊戲設定與學校清單的後端'
type: 'feature'
created: '2026-10-29'
status: 'done'
baseline_commit: '1a0d1e3ea3d3218e2cb7eb9c56edc1af24d2bf10'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 2.2 建立賽事需要遊戲與其預設值，但目前沒有 GameTitle／RankTier 資料表與管理 API；學校清單只有 1.3 的初始資料，平台管理員無法新增或改名。後台版面（A 的 1.8）11/1 才交付，2.2 的資料表卻要在 10/31 前完成。

**Approach:** 第一階段只做後端：tournaments 的 GameTitle、RankTier 與遊戲 API，identity 的學校新增與改名 API，只限平台管理員並寫操作紀錄。S36 畫面在第二階段（另一份 spec，1.8 合併後）完成。

## Boundaries & Constraints

**Always:**
- 遊戲欄位：名稱、先發人數（≥1）、替補人數（≥0）、預設 BO（只能 1、3、5、7）、每局預估時間（分鐘，≥1）、比分型態（`ScoreType`）、段位對照表（至少一筆；同遊戲內段位名稱不重複；積分為非負整數）。
- 遊戲名稱去除前後空白後、不分大小寫不可重複；學校名稱不可重複（沿用 `ix_school_name`）。重名回 409；兩個請求同時送出時也只有一個成功。
- 修改遊戲為整份替換（含段位表）。
- 程式中不得依遊戲名稱或 id 寫分支（AD-18）。
- 所有新 API（含遊戲讀取）只限 `PlatformAdmin`：非平台管理員 403 `PLATFORM_ADMIN_REQUIRED`，未登入 401。
- 新增遊戲、修改遊戲、新增學校、修正學校名稱都以 `core.audit.record()` 寫操作紀錄（`tournament_id` 為空，before／after 只放變動欄位；沒有變動時不寫）。

**Never:**
- 不做 S36 畫面與前端（第二階段）。
- 不做刪除或停用遊戲、刪除學校。
- 不做主辦方的遊戲選單與賽事快照（2.2）。
- 不改 1.3 的初始學校資料與既有 `GET /schools`。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 新增遊戲 | 合法資料、2 筆段位 | 201，回傳遊戲與段位（積分由高到低）；寫 `game.created` | N/A |
| 虛構第三款遊戲 | 先發 3、替補 0、BO 7、`win_loss`、1 筆段位 | 201，值與輸入一致 | N/A |
| BO 不合法 | `default_bo=2` | 拒絕 | 422，`default_bo` 欄位 |
| 段位為空 | `rank_tiers=[]` | 拒絕 | 422，`rank_tiers` 欄位 |
| 段位名稱重複 | 同遊戲兩筆「鑽石」 | 拒絕 | 422，`rank_tiers` 欄位 |
| 遊戲名稱重複 | 已有「英雄聯盟」，再送「英雄聯盟 」 | 拒絕 | 409 `GAME_NAME_TAKEN` |
| 修改遊戲 | 改 BO 與段位表 | 200；段位整份替換；寫 `game.updated` | 不存在 404 `GAME_NOT_FOUND` |
| 新增學校 | 新名稱 | 201；寫 `school.created`；`GET /schools` 立即包含 | 重名 409 `SCHOOL_NAME_TAKEN` |
| 修正學校名稱 | 改名 | 200；寫 `school.renamed`；帳號的 `school_id` 不變 | 不存在 404 `SCHOOL_NOT_FOUND`；重名 409 |
| 非平台管理員 | 一般已驗證帳號呼叫任一新 API | — | 403 `PLATFORM_ADMIN_REQUIRED` |

## Decisions

- 2026-10-29（使用者）：本 Story 拆兩階段。第一階段只做後端並先合併，讓 2.2 在 10/31 前能接上；S36 畫面在 1.8 合併後的第二階段完成。
- 2026-10-29（使用者）：「以虛構的第三款遊戲建立賽事、驗證快照」與「修改預設值不影響已建立賽事的快照」兩條 AC 移到 2.2 驗收；本 Story 只驗證遊戲設定本身。

</frozen-after-approval>

## Code Map

- `backend/app/modules/tournaments/models.py` -- 已有 `ScoreType`；新增 `GameTitle`（`__tablename__="game_title"`）、`RankTier`（`"rank_tier"`，FK `game_id` ON DELETE CASCADE）與 `GameIn`／`GameRead`／`RankTierIn`／`RankTierRead`
- `backend/app/modules/tournaments/{repository,service,router}.py` -- 目前只有 docstring；router 已註冊於 `api/main.py`
- `backend/app/modules/identity/models.py:49` `School`、`:197` `PublicSchool` -- 新增 `SchoolIn`
- `backend/app/modules/identity/repository.py:38-47` `add_account` -- 照抄 `begin_nested()`＋捕捉 `IntegrityError`、比對索引名稱的重名處理
- `backend/app/modules/identity/service.py:96` `_school_not_found`、`:100` `_email_already_registered`（409 寫法）、`:476-485`（只記變動欄位的 audit 範例）
- `backend/app/modules/identity/router.py:125-131` -- router 呼叫 service 後 commit；`:28` `PUBLIC_WRITE_ROUTES` 不加入新 API
- `backend/app/modules/identity/deps.py:56` `PlatformAdmin`
- `backend/app/core/audit.py:53` `record(...)`；`backend/app/core/errors.py` `BusinessError`、`FieldError`
- `backend/tests/identity/test_login.py:40-90` `_make_account(admin=True)`、`_token`、`_bearer` -- 移到 `backend/tests/helpers.py` 共用，`test_login.py` 改 import
- `backend/tests/test_migrations.py`、`test_enums.py`、`test_module_structure.py`、`test_auth_required.py` -- 必須繼續通過
- `backend/app/alembic/versions/9e5b3f1a7c42_story_1_5_password_reset.py` -- 新遷移的 `down_revision`

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/tournaments/models.py`、`backend/app/alembic/versions/<rev>_story_2_1_game_title.py` -- 兩張表、`lower(trim(name))` 唯一索引
- [x] `backend/app/modules/tournaments/{repository,service,router}.py` -- `GET/POST /admin/games`、`GET/PUT /admin/games/{game_id}`；公開函式 `get_game(session, *, game_id) -> GameRead` 供 2.2 使用
- [x] `backend/app/modules/identity/{models,repository,service,router}.py` -- `POST /admin/schools`、`PATCH /admin/schools/{school_id}`
- [x] `backend/tests/helpers.py`、`backend/tests/tournaments/test_games.py`、`backend/tests/identity/test_school_admin.py` -- I/O Matrix 每列至少一個測試，含重名競爭與 audit 內容
- [x] `frontend/src/client/` -- `bash scripts/generate-client.sh` 重新產生（CI 會檢查與後端一致）

**Acceptance Criteria:**
- Given 平台管理員新增或修改遊戲，when 再讀取遊戲列表，then 立即反映，不需重新部署
- Given 本 spec，when 執行 Verification 的所有指令，then 全部通過

## Implementation Notes

- 欄位名稱沿用架構初稿（c-d-design-groundwork）：`starters`、`substitutes`、`default_bo`、`game_minutes`、`score_type`；段位為 `name`、`score`。
- 遷移 `c2a7d4e9f1b3`：唯一索引 `ix_game_title_lower_name` 寫成 `lower(btrim(name))`（PostgreSQL 會把 `trim()` 存成 `btrim()`，寫成 btrim 才不會讓 autogenerate 比對出差異）；`rank_tier` 另有唯一索引 `ix_rank_tier_game_id_lower_name`（`game_id, lower(btrim(name))`），與 `GameIn` 不分大小寫的重複檢查一致。重名判斷比對 `exc.orig.diag.constraint_name` 是否等於索引名稱，不用字串包含。
- spec 沒規定的上限（為了不讓超長或超大值變成 500）：遊戲名稱 100 字、段位名稱 50 字、段位最多 100 筆、整數不超過 PostgreSQL INTEGER 上限；學校名稱沿用欄位長度 255。段位名稱去除前後空白、不分大小寫比對重複。
- 重名競態：先查同名、再在 savepoint 裡寫入並 flush，撞到唯一索引時轉成 409。要修改的欄位必須在 savepoint 裡才設定，因為 `begin_nested()` 會先 flush 既有的變更，否則唯一索引錯誤會發生在 savepoint 之外。
- 修改遊戲時段位表以「依積分、名稱排序後整份比較」判斷是否變動；內容相同只是順序不同視為沒有變動，不寫操作紀錄。
- 學校改成同一個名稱（含只差前後空白）回 200、不寫操作紀錄。
- `tests/helpers.py` 改用不帶底線的名稱（`make_account`、`token_for`、`bearer`、`login`、`random_email`），`test_login.py` 以別名匯入，原本的測試內容不變。

## Spec Change Log

## Review Triage Log

第一輪（2026-10-29）：Blind Hunter 14 筆、Edge Case Hunter 3 筆、Verification Gap 0 筆。

| # | 來源 | 發現 | 判定 | 處理 |
|---|------|------|------|------|
| 1 | Blind | 「同時送出」測試是依序執行並 monkeypatch 同名檢查，不是真的兩條連線 | low：唯一索引才是真正的保護，測試已證明索引擋下並轉成 409；與 1.3 的競態測試做法相同，改成雙連線測試要另寫連線管理 | 不處理 |
| 2 | Blind | 改名競態測試只檢查 409，沒檢查錯誤代碼與「沒有寫操作紀錄」 | low：錯誤對應壞掉時測試仍會通過 | patch |
| 3 | Blind | 學校名稱區分大小寫、遊戲名稱不區分 | false：凍結區塊明定學校「沿用 `ix_school_name`」，遊戲才要求不分大小寫 | 不處理 |
| 4 | Blind | `uq_rank_tier_game_id_name` 區分大小寫，與驗證規則不一致 | low：繞過 `GameIn` 的寫入（種子腳本）可存入只差大小寫的段位 | patch |
| 5 | Blind | 允許兩個段位同分 | false：同分只代表兩個段位強度相同，排序與之後的段位積分加總都有明確結果 | 不處理 |
| 6 | Blind | 資料表沒有 CHECK 限制 | low：只有繞過 API 的手動寫入才會遇到；加上限制屬於新增防護 | 不處理 |
| 7 | Blind | 兩位管理員同時編輯，後存的覆蓋先存的 | low：平台管理員人數極少，同時編輯同一款遊戲不太會發生；修正要新增版本欄位與 API 介面 | 不處理 |
| 8 | Blind | 段位每次修改都換新 id，`RankTierRead` 沒有 id | false：2.2 把段位表複製進賽事快照（AD-12），之後不回頭參照遊戲的段位列 | 不處理 |
| 9 | Blind | 缺測試：PUT 送不合法資料、只差大小寫的段位名稱、404 不寫操作紀錄 | low：驗證共用同一個 schema，但修改失敗時資料不變沒有被證明 | patch |
| 10 | Blind | 重名判斷以錯誤訊息字串包含索引名稱，前綴相同的新索引也會命中 | low：目前沒有這種索引；改成比對 `diag.constraint_name` 是直接修正 | patch |
| 11 | Blind | Implementation Notes 對段位比較是否區分大小寫的描述不清楚 | 修正方式是改本 spec | 不處理 |
| 12 | Blind | 遊戲列表以 `COLLATE "C"` 排序，大小寫與中文順序不直覺 | low：與 1.3 學校清單的排序一致；畫面在第二階段，屆時可再決定 | 不處理 |
| 13 | Blind | tournaments 與 identity 的名稱驗證函式重複 | low：重構會動到 identity 既有程式，沒有已知的分歧造成問題 | 不處理 |
| 14 | Blind | 缺 AI 使用紀錄 | false：紀錄在 bmad-build 完成時（step 5）寫入 | 不處理 |
| 15 | Edge | 名稱含 NUL 字元時，資料庫拒絕而回 500 | low：只有平台管理員能呼叫，一般輸入不會出現；修正要新增防護 | 不處理 |
| 16 | Edge | 缺欄位、`score_type` 不在列舉時 422 訊息是英文 | low：既有問題，identity 的 API 也一樣；不是本 Story 造成 | defer |
| 17 | Edge | NFC／NFD 正規化不同的名稱可重複 | low：管理員以鍵盤輸入不會產生 NFD；修正要新增正規化 | 不處理 |

## Verification

**Commands:**
- `docker compose up -d --build --wait` -- 五個服務 healthy
- `docker compose exec backend bash scripts/test.sh` -- 全部通過，覆蓋率達門檻
- `docker compose exec backend bash scripts/lint.sh` -- 無錯誤
- `docker compose exec frontend bun run --filter frontend build`、`docker compose exec frontend bun run --filter frontend typecheck` -- 通過（client 重新產生後）
