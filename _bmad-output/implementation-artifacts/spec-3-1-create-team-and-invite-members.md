---
title: 'Story 3.1 建立隊伍與邀請隊員'
type: 'feature'
created: '2026-10-30'
status: 'done'
baseline_commit: '7414d3b9abd2be5aa8c64c187615a11448ad9f0b'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/contracts/README.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** registration 模組只有列舉，隊長還無法為賽事建隊、取得邀請連結，隊友也無法加入；後續 3.2～3.6 與 B 的 2.7（Invite link field，11/3 前）都在等這一步。

**Approach:** 在 registration 建立 Team、TeamMember、Registration（建隊時 `forming`），提供建隊、預覽邀請、加入、隊伍頁、我的隊伍 API 與 S16／S17／S19／S12 畫面，以及 Invite link field、Roster list、Registration status card 元件。Story 2.2 尚未合併，依 CONTRIBUTING 6.5 照 `contracts/tournaments.md` 呼叫 `get_tournament`、`lock_tournament`、`ensure_accepting_registrations`，測試以 monkeypatch 替身代替；不合併 story/2-2。

## Boundaries & Constraints

**Always:**
- 建隊、加入先 `lock_tournament()`，鎖住後才檢查：賽事 `open`（`ensure_accepting_registrations`）、主辦方身分、是否已在該賽事、人數上限（`starters + substitutes`）。
- TeamMember 帶 `tournament_id`，（tournament_id, account_id）唯一鍵；撞到唯一鍵也回 `ALREADY_IN_TOURNAMENT` 409。
- 寫入 API 用 `VerifiedAccount`；router commit；操作紀錄用 `audit.record`（`team.created`、`team.member_joined`，帶 `tournament_id`）。
- Registration 狀態只能經 `mark_status()` 修改，轉換表照期中文件 B 的報名狀態圖。
- 提供約定的公開函式 `get_team`（`TeamRead`）、`get_registration`（`RegistrationRead`）、`is_member`、`is_captain`。
- 測試帳號用各測試檔自己的 `_make_account` 直接 insert，賽事用 monkeypatch 替身。

**Never:**
- 不建立或使用 factory、seed；不合併 story/2-2；不改 tournaments 模組。
- 不做自訂模式（`TOURNAMENT_INVITE_REQUIRED`）、參賽資料、送出、退出、解散、重設邀請連結。
- 不手寫 fetch／axios；不手改 `frontend/src/client`、`routeTree.gen.ts`。

## Decisions（2026-10-30，邱芯彤）

- 建隊入口：本 Story 只做 `CreateTeamDialog` 元件與 API，不做暫時入口頁；S2 完成（2.4）後由 B 放上「建立隊伍」。
- 「我的隊伍」：所有登入帳號都顯示；identity 只新增 `IdentityKey.MY_TEAMS` 並在 `list_identities` append 一項，PR 說明列出動到 A 的模組。
- 隊名：去頭尾空白後 1～30 字；同賽事內不分大小寫不可重複，重複回 409 `TEAM_NAME_TAKEN`。
- spec 篇幅超過 1600 tokens，保留完整 spec，不拆分。
- 開工前已確認：分支 story/3-1 暫不 push；2.2 未合併，用約定介面與 monkeypatch 替身，不合併 story/2-2；不建立或使用 factory、seed。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 建隊 | 已驗證、非主辦方、賽事 open | 201 `TeamDetail`；建立者為 captain，Registration `forming`，產生邀請 token | N/A |
| 加入 | 有效 token、隊伍未滿 | 200，成為 player | N/A |
| 已在該賽事 | 建隊或加入另一隊 | 拒絕 | 409 `ALREADY_IN_TOURNAMENT` |
| 主辦方 | 建隊或加入 | 拒絕 | 403 `ORGANIZER_CANNOT_JOIN` |
| 隊伍已滿 | 人數 = 先發＋替補 | 預覽 `invite_status=full`；加入拒絕 | 409 `TEAM_FULL` |
| 賽事非 open | 建隊或加入 | 拒絕 | 409 `REGISTRATION_CLOSED`（由 tournaments 拋出） |
| token 不存在 | 預覽或加入 | 找不到 | 404 `TEAM_INVITE_NOT_FOUND` |
| 未驗證 Email | 寫入 API | 拒絕 | 403 `EMAIL_NOT_VERIFIED` |
| 非隊員看隊伍頁 | GET 隊伍 | 拒絕 | 403 `TEAM_MEMBER_REQUIRED` |
| 隊名重複 | 同賽事已有同名（不分大小寫） | 拒絕 | 409 `TEAM_NAME_TAKEN` |
| 隊名長度 | 去空白後 0 字或超過 30 字 | 拒絕 | 422 |

</frozen-after-approval>

## Code Map

- `backend/app/modules/registration/models.py` -- 已有 `MemberRole`、`RegistrationStatus`；新增資料表、schema、`TeamRead`／`RegistrationRead`
- `backend/app/modules/registration/{service,repository,router}.py` -- 骨架，依 identity 寫法填入
- `backend/app/modules/identity/deps.py` -- `VerifiedAccount`、`CurrentAccount`，回 `AccountRead`（含 `display_name`）
- `backend/app/modules/identity/service.py:423` `list_identities`、`models.py:272` `IdentityKey` -- 「我的隊伍」（見 Decisions）
- `backend/app/modules/identity/service.py` `_issue_verification_token` -- `secrets.token_urlsafe` 用法；邀請 token 要能重複顯示，故明文存 `team.invite_token`（UNIQUE）
- `backend/app/core/{errors,audit,clock}.py` -- `BusinessError`、`record(session, *, actor_id, tournament_id, action, entity_type, entity_id, before, after)`、`now()`；`core/authz.py` 不存在（2.2 才加），本 Story 不需要 `ensure_captain`
- `backend/app/alembic/versions/` -- head 為 `9e5b3f1a7c42`；`tests/test_migrations.py` 要求模型與遷移一致
- `backend/tests/identity/test_login.py` -- `_make_account`、`_token`、`_bearer` 寫法參考
- `backend/tests/test_auth_required.py` -- 寫入路由未帶 token 要回 401
- `frontend/src/features/identity/auth.ts` `requireSignedIn`；`features/identity/redirect.ts` `safeRedirect`；`login`／`signup`／`verify-email` 已支援 `redirect`
- `frontend/src/components/layout/IdentitySwitcher.tsx`、`features/identity/identity-icons.ts` `IDENTITY_ICONS`（`Record<IdentityKey,…>`，新增 key 必須補 icon）
- `frontend/tests/unit/{auth-fixtures.ts,render-router.tsx,helpers.ts}` -- `mockAccountApis`、`signInAs`、`renderApp`
- `contracts/tournaments.md` -- `TournamentRead` 欄位：`organizer_id`、`name`、`status`、`game_name`、`starters`、`substitutes`

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/registration/models.py` -- `Team`（id, tournament_id, name, invite_token UNIQUE, created_at）、`TeamMember`（id, team_id FK, tournament_id, account_id FK, role, created_at；UNIQUE(tournament_id, account_id)）、`Registration`（id, team_id FK UNIQUE, tournament_id, status, created_at）；`TeamCreate`、`TeamDetail`、`TeamInvitePreview`、`MyTeamCard`、`TeamRead`、`RegistrationRead` -- 期中文件 B 資料表；快照欄位與參賽資料欄位留給 3.2、3.3
- [x] `backend/app/alembic/versions/<hex>_story_3_1_team_and_registration.py` -- 建三張表；`tournament_id` 暫不加 FK（tournament 表在 2.2）
- [x] `backend/app/modules/registration/repository.py` -- 查詢與 insert
- [x] `backend/app/modules/registration/service.py` -- `create_team`、`preview_invite`、`join_team`、`get_team_detail`、`list_my_teams`、`mark_status`、公開函式；呼叫 tournaments 時加 `# type: ignore[attr-defined]` 並以本地 `Protocol` 描述需要的 `TournamentRead` 欄位
- [x] `backend/app/modules/registration/router.py` -- `POST /tournaments/{id}/teams`、`GET /teams/{id}`、`GET /team-invites/{token}`（公開讀取）、`POST /team-invites/{token}/members`、`GET /accounts/me/teams`
- [x] `backend/app/modules/identity/{models,service}.py` -- `IdentityKey.MY_TEAMS`、`list_identities` append「我的隊伍」→ `/me/teams`
- [x] `backend/tests/registration/` -- I/O 矩陣、唯一鍵防線、`mark_status` 轉換表、公開函式、操作紀錄；`tournaments.service` 以 `monkeypatch.setattr(..., raising=False)` 替身
- [x] `frontend/src/features/registration/` -- `InviteLinkField`（通用，2.7 沿用）、`RosterList`、`RegistrationStatusCard`、`CreateTeamDialog`
- [x] `frontend/src/routes/` -- `teams.$teamId.tsx`（S17）、`join.$inviteToken.tsx`（S19）、`me.teams.tsx`（S12）；不做建隊入口頁
- [x] `frontend/tests/unit/` -- 元件與三個頁面的測試；`features/identity/identity-icons.ts` 補 icon
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- 新增：2.2 合併後補 `tournament_id` FK、移除 type ignore 與替身、補 PostgreSQL 平行加入的併發測試

**Acceptance Criteria:**
- Given 隊伍頁 S17，when 隊員檢視，then Roster list 每人一列顯示名稱，隊長有 outline Badge「隊長」，下方「4／6 人（先發 5）」，並以 Invite link field 顯示邀請連結（唯讀＋「複製連結」，複製後 Toast「已複製」）；額滿時顯示「連結已失效」與原因「隊伍已滿」。
- Given S19，when 開啟邀請連結，then 先顯示賽事名、遊戲與隊名；未登入時提供註冊與登入（帶 `redirect` 回 S19）；未驗證時說明需先驗證 Email；被拒時說明原因並提供回賽事頁的連結。
- Given 已有隊伍的帳號，when 開啟 S12，then 每隊一張 Registration status card（賽事名＋遊戲、隊名、徽章「組隊中」），點擊到 S17；沒有隊伍時「你還沒有加入任何隊伍。」＋「瀏覽賽事」。
- Given 未驗證帳號，when 看到「建立隊伍」，then 按鈕停用並說明原因。
- Given 任何登入帳號，when 開啟身分切換器，then 出現「我的隊伍」，點選到 `/me/teams`。
- Given 建隊 Dialog，when 送出成功，then 導向該隊 S17。

## Implementation Notes

- S12 的路由檔名是 `me_.teams.tsx`（路徑仍為 `/me/teams`），不是 Code Map 寫的 `me.teams.tsx`：`me.tsx`（S11）沒有 `Outlet`，巢狀在它底下的 S12 不會被渲染；尾端底線讓它不巢狀，也不必改 A 的 `me.tsx`。
- ty 不認 `type: ignore[attr-defined]`，呼叫 tournaments 的三處另加 `# ty: ignore[unresolved-attribute]`（已列入 deferred-work，2.2 合併後一併移除）。
- 「我的隊伍」放在「瀏覽賽事」之後、「平台管理」之前（UX-DR8 的順序）。所有帳號因此至少有 2 個身分，第一次登入會先到 S11（`postLoginDestination` 的既有規則）；`tests/identity/test_login.py` 的兩個身分清單斷言已跟著更新。
- `get_registration(session, *, team_id)` 以隊伍 id 查詢（報名與隊伍一對一，其他模組手上是 team_id）；`mark_status(session, *, registration, to, actor_id)` 同時寫操作紀錄 `registration.status_changed`，非法轉換回 409 `REGISTRATION_INVALID_TRANSITION`。
- `TeamDetail` 對所有隊員都含 `invite_token`；S19 的公開預覽 `TeamInvitePreview` 不含隊員名單。新增業務錯誤：`TEAM_NOT_FOUND` 404、`REGISTRATION_NOT_FOUND` 404。
- 驗收時補上：`TeamRead` 加 `members`（`account_id`、`role`），依 c-d-design-groundwork「`get_team` 回傳 `TeamRead`（隊名、隊員帳號與角色）」，其他模組以它判斷隊長。
- S16 Dialog 只有「建立隊伍」送出鈕，關閉用 Dialog 右上角的關閉鈕（避免「取消」這類非動詞＋名詞的按鈕）。

## Spec Change Log

## Review Triage Log

第 1 輪（2026-10-30；E＝Edge Case Hunter、B＝Blind Hunter、V＝Verification Gap、M＝主流程驗收）

| 來源 | 發現 | 判定 | 證據 | 去向 |
| --- | --- | --- | --- | --- |
| E1、B2 | 加入時沒檢查報名仍是 `forming` | false | 3.1 沒有任何 API 會把報名轉出 `forming`（`mark_status` 未對外開放），目前無法發生；送出後鎖定名單屬 3.3 | reject |
| E2、B1 | 賽事非 open 時預覽仍顯示「加入隊伍」 | low | 按下後回 `REGISTRATION_CLOSED`，頁面顯示原因與返回連結；修正要新增邀請狀態與分支 | reject |
| E3 | 先發＋替補 < 1 時隊長也超額 | false | 遊戲設定的先發人數至少 1（2.1），賽事快照沿用 | reject |
| E4、E11 | 賽事不存在時我的隊伍／預覽整頁 404 | false | 賽事不會被刪除，取消只是狀態（2.6） | reject |
| E5、B9 | 以 `assert` 守不變量 | low | 專案不以 `-O` 執行，`core/errors.py` 等既有程式同樣用法 | reject |
| E6 | 資料庫狀態值不在轉換表時 KeyError | false | `status` 只經列舉寫入 | reject |
| E7 | 預查隊名用 Python `lower()`，與 PostgreSQL `lower()` 對部分 Unicode 不同 | low | 預查與唯一索引判斷不一致時會誤擋或只靠索引；改成 `func.lower(name)` 是直接修正 | patch |
| E8、B5 | 隊名可為零寬字元、未做 NFKC、未合併空白 | low | 少見；修正要增加驗證規則，超出已決定的「去頭尾空白 1～30 字、不分大小寫」 | reject |
| E9、B3 | `team_member.tournament_id` 與 `team` 沒有一致性約束 | low | service 一律從 team 複製；複合外鍵屬加固，增加 schema 複雜度 | reject |
| E10、B7 | S19 加入失敗一律顯示拒絕畫面；開自己隊伍的連結只看到拒絕 | low | 隊員重開自己隊伍的連結很常見，只看到「已在隊伍中」與失效的回賽事頁連結；在 `ALREADY_IN_TOURNAMENT` 時加「查看我的隊伍」連結是直接補充。暫時性錯誤的重試按鈕屬新增分支，不做 | patch（只做前者） |
| E12、B7 | 加入成功或 `TEAM_FULL` 後邀請預覽快取未失效 | low | 預設 staleTime 0 重新掛載會重抓，但同頁停留時人數過期；加一行 invalidate | patch |
| E13、B6 | `CreateTeamDialog` 尚未掛載、「回到賽事頁」指向尚未存在的 S2 | medium | 依 Decisions 刻意如此，但 deferred-work 未追蹤，2.4 完成時容易漏接 | defer |
| E14 | 路由檔名與 spec 不同 | false | 修正對象是 spec；Implementation Notes 已說明 | reject |
| B4 | 隊伍頁、我的隊伍 N+1 查詢 | low | 每隊最多數人、每人隊伍數少 | reject |
| B8 | 缺測試：我的隊伍排序、`actor_id=None`、未驗證隊員讀隊伍頁 | low | 排序與系統操作者是 docstring 承諾的行為；補測試是直接新增 | patch（排序、`actor_id=None`） |
| B8 | 缺 API 層級的額滿預覽測試 | false | `test_team_full_invalidates_invite` 已以 API 斷言 `invite_status == "full"` | reject |
| B10 | 邀請 token 無法重設；建立報名沒有操作紀錄 | low | 重設邀請連結在 Never 範圍外；`team.created` 已記錄建隊 | reject |
| V1 | 替身以 `raising=False` 打 patch，2.2 介面變動測不出來 | medium | 已有 deferred 項目；補記 2.2 合併後先移除 `raising=False` | defer |
| V2 | 「先鎖再檢查」的順序與使用鎖定回傳值沒有測試 | medium | 替身只記錄有呼叫 lock；順序錯誤不會被抓到 | patch |
| V 其他 | PR 先於 2.2 合併會讓端點 500 | false | PR 等 2.2 合併後才送（Decisions：暫不 push） | reject |
| V 其他 | 前端登入測試的 fixture 仍只有 BROWSE 身分 | low | 2 個身分的規則另有測試守住 | reject |
| M | 轉換表多了 `drawn → disqualified`，期中文件 B 狀態圖沒有 | false | 主流程讀狀態圖時漏看第 590 行；圖中有 `drawn --> disqualified`，條件 4 也寫明已參賽可被取消資格（由實作子代理指出後查證） | reject |

## Design Notes

併發：建隊／加入的人數上限仰賴 `lock_tournament` 的列鎖，替身無法驗證；2.2 合併後再補真實 PostgreSQL 平行加入測試（deferred-work）。本 Story 的測試以唯一鍵防線（直接 insert 重複 TeamMember 失敗、service 轉成 409）驗證最後防線。

## Verification

**Commands:**
- `docker compose up -d --build --wait && docker compose exec -T backend bash scripts/test.sh` -- 全綠
- `docker compose exec -T backend bash scripts/lint.sh` -- mypy／ty／ruff 通過（type ignore 僅限呼叫 tournaments 處）
- `docker compose exec -T frontend bun run --filter frontend typecheck`、`bunx biome check`、`bun run test:unit` -- 通過
