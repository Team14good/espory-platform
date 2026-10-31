# Deferred Work

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-official-template-project-skeleton.md`
  summary: 首頁「後端狀態：正常」沒有自動化的端對端測試，`bun run test` 因為沒有任何 Playwright 規格而回報「No tests found」並以非零代碼結束。
  evidence: `frontend/tests/` 只有 `.gitkeep`；Story 1.1 的 Never 移除了 playwright 服務，目前沒有可執行的 e2e 環境。等 e2e 環境建立後（最晚 Story 7.2），新增 `frontend/tests/home.spec.ts`，以 `PLAYWRIGHT_BASE_URL` 對 compose 執行，斷言 `role="status"` 顯示「後端狀態：正常」。
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-official-template-project-skeleton.md`
  summary: worker 可能在 job 失敗後的 rollback 或 session close 拋錯時結束程序，而 compose 沒有替它設定 restart 政策（未證實；若成立為 medium）。
  evidence: `Worker.run_forever` 外層沒有例外保護，`compose.yml` 的 worker 沒有 `restart`。要確認是否成立：在 worker 執行工作時重啟 db 容器，觀察 `session.rollback()`／close 是否拋錯、worker 是否結束。若成立，補上 `restart: unless-stopped` 並在 `run_once` 保護 rollback；Story 1.3 加入第一個 outbox 工作時一併處理。
- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-flow-frontend-shell-and-theme.md`
  summary: DESIGN.md 的部分色票對比不足：淺色 primary #0891B2 搭配白字約 3.7:1，未達 WCAG AA 一般文字 4.5:1；深色 `status-eliminated` #4B5370 在背景 #070A14 上約 2.6:1，連非文字元素的 3:1 都不到。
  evidence: Story 1.2 照 DESIGN.md frontmatter 原樣寫入 `frontend/src/index.css`，數值與設計稿一致，所以問題出在設計稿本身。需要由 UX（bmad-ux）調整色票，例如加深淺色 primary，或讓 primary 按鈕在淺色時改用深色字，再同步更新 `index.css`。
- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-email-signup-and-verification.md`
  summary: worker 的事件分派與寄信遇到「每次都失敗」的項目時（不是 payload 格式錯誤，而是持續性的資料庫錯誤或外鍵錯誤），同一筆會一直排在最前面，擋住後面所有事件或信件（未證實；若成立為 medium）。
  evidence: `dispatch_outbox` 與 `send_next_email` 每次都取最舊的一筆，失敗時交易回滾、項目不變；`outbox_event` 沒有 attempts 或 dead-letter 欄位，`_compose` 的資料庫錯誤也可能讓 `attempts` 無法寫入。Story 1.3 的事件只有 `VerificationEmailRequested`，payload 一定合法、帳號不可刪除，所以沒能證明實際會發生。要確認是否成立：用 Story 1.6 的新事件類型，或刻意製造持續性的資料庫錯誤來觀察。若成立，在 1.6 建立事件類型登錄機制時，加上分派次數上限與 dead-letter 標記。
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-official-template-project-skeleton.md`
  summary: `audit_log` 的「只增不改」只靠資料庫 trigger；應用程式、worker、alembic 都以資料表擁有者（預設 postgres 超級使用者）連線，可以停用或刪除 trigger，AD-9 沒有真正的強制力。
  evidence: 2026-10-24 Story 1.1 Code Review（Blind Hunter）。要強制，需另建非擁有者的應用程式角色，對 `audit_log` 只給 INSERT／SELECT，並撤銷 UPDATE／DELETE／TRUNCATE；遷移仍以擁有者身分執行。牽涉 compose、`.env` 與連線設定，適合在部署或安全強化時一併處理。
- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-login-logout-account-identity-switcher.md`
  summary: `POST /api/v1/access-tokens` 沒有頻率限制或連續失敗鎖定；每次請求都會跑一次 argon2，可被用來暴力猜密碼或耗用 CPU（規劃文件沒有相關規則，嚴重度未證實；若部署到公開網路，為 medium）。
  evidence: 2026-10-27 Story 1.4 Code Review（Blind Hunter）。Story 1.4 調查時確認 PRD、架構、epics 都沒有鎖定或頻率限制的規則。要處理時，先由 PM／架構決定規則（例如同一 Email 或 IP 每分鐘上限），再在登入端點實作，並決定是否要以 429 回應。

## Deferred from: code review of spec-1-4-login-logout-account-identity-switcher.md (2026-10-28)

- 正式啟動程式 `frontend/src/main.tsx` 呼叫 `createQueryClient()` 與 `configureApiClient(...)`（接上 Bearer 標頭與 401 攔截器）沒有任何測試；刪掉這行，所有單元測試照樣通過，但正式環境的已登入請求會不帶 token、401 也不會導向 S6。要等第一個 Playwright e2e 規格（登入後開 `/account`）才能涵蓋；`configureApiClient` 本身已有單元測試。

## Deferred from: code review of spec-1-5-forgot-reset-password.md (2026-10-28)

- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-forgot-reset-password.md`
  summary: 同一個重設連結同時送出兩次（兩個分頁、連點）時只能成功一次的保護（`reset_password` 先鎖帳號再鎖 token 重查、`get_token_by_hash` 的 `populate_existing`）沒有並行測試；拿掉任一環，現有測試都照樣通過（未證實會出錯；若退步，為 medium：一次性連結可被用兩次、`credentials_version` 加 2）。
  evidence: 2026-10-28 Story 1.5 Code Review（Verification Gap、Blind Hunter）。測試的 `client` 與 `session` fixture 共用同一條連線與外層交易，兩個交易不可能互搶 `FOR UPDATE` 鎖。要補需要另一套測試架構：自行建立並提交資料、兩條連線、兩個執行緒以 barrier 同時送出，斷言恰好一個 204、一個 `RESET_LINK_INVALID`、版本只加 1。`verify_email` 的鎖定重查也一併適用。
- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-forgot-reset-password.md`
  summary: `POST /api/v1/password-reset-emails` 沒有頻率限制：可以對同一個 Email 大量寄信灌爆收件匣，而且每次申請都會作廢對方手上的重設連結，讓本人無法完成重設。
  evidence: 2026-10-28 Story 1.5 Code Review（Edge Case Hunter）。Story 1.5 的 Never 明定不做頻率限制（與登入相同）。處理時與登入的頻率限制一起由 PM／架構決定規則（例如同一 Email 每小時上限、同一 IP 上限），並決定超過時是否仍回相同的 202 以免透露帳號是否存在。
- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-forgot-reset-password.md`
  summary: 「重設信只寄 Email、不建立站內通知」目前沒有任何斷言（1.5 第一輪審查移除了 `"notification" not in metadata.tables`）；Story 1.6 加入站內通知後，若 `dispatch_event` 誤替 `PasswordResetRequested`（或 `VerificationEmailRequested`）建立站內通知，現有測試照樣通過。
  evidence: 2026-10-28 Story 1.5 第二輪 Code Review（Blind Hunter、Acceptance Auditor）。目前還沒有 notification 表，無從斷言。Story 1.6 建立站內通知時，在 `tests/notifications/test_email_delivery.py` 的重設信與驗證信測試補上「站內通知筆數不變」的斷言。
- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-forgot-reset-password.md`
  summary: `tests/test_migrations.py` 只開 `compare_type`，沒有比對 server default；遷移檔與模型的 `server_default` 不一致（例如 `account.credentials_version` 的 `"0"` 被刪掉或改值）時測試照樣通過。測試資料庫每次從空表升級，也測不到「既有帳號升級後拿到 0」（低；若遷移檔被改錯，為 medium：有資料的資料庫升級失敗，或舊登入全部失效）。
  evidence: 2026-10-28 Story 1.5 第二輪 Code Review（Verification Gap）。比對設定自 Story 1.1 起就是如此，不是本 Story 造成。處理時在 `MigrationContext.configure` 加 `"compare_server_default": True`，先跑一次確認其他既有欄位沒有誤報；要完整守住資料升級，另寫一支「升到上一版、插入帳號、再升到 head」的測試。

## Deferred from: spec-3-2-player-registration-info.md 第一段 (2026-10-30)

- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-player-registration-info.md`
  summary: Story 3.2 第二段（依賴 Story 3.1 的 `team_member` 與 S17）尚未實作：參賽資料還不能存檔，S18 還沒有入口。
  evidence: 依 spec Decisions，story/3-2 從 `main` 開出、與 story/3-1 獨立；第一段只做了 `core.storage`、`registration/player_profile.py` 的 `rank_score_for`、`ScreenshotUploader` 與 `PlayerProfileDialog`。3.1 合併後在同一分支 `git merge origin/main`，再做：`team_member` 加 `game_account_id`、`rank_tier`、`rank_score`、`rank_screenshot_key`、截圖原始檔名與遷移；multipart API（先 `lock_tournament`，只能改自己、名單鎖定時拒絕，段位用 `rank_score_for` 驗證、截圖用 `core.storage.save_image` 存）；重新產生 `frontend/src/client`；S17「填寫我的資料」、Roster 行與「資料完成／缺：…」、平均段位積分（含替補，取到小數第二位）；以生成的 client 的 options 傳 axios `onUploadProgress`，接上 `PlayerProfileDialog` 的 `uploadProgress`。段位對照表改用 tournaments 的 `RankTierRead`，取代 `player_profile.py` 的本地 `Protocol`。

- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-player-registration-info.md`
  summary: `core.storage` 沒有刪檔函式；第二段選手更換段位截圖後，舊檔會永遠留在 uploads volume。
  evidence: 2026-10-30 Story 3.2 第一段 Code Review（Blind Hunter）。本段沒有更換流程所以尚未發生；第二段存檔時要新增 `delete_file(key)`，並在同一交易成功後刪除舊鍵值的檔案（medium）。
- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-player-registration-info.md`
  summary: 上傳 API 沒有請求大小上限，5 MB 在 multipart 整個收完後才由 `core.storage` 檢查。
  evidence: 2026-10-30 Story 3.2 第一段 Code Review（Blind Hunter）。Starlette 會先把整個 body spool 到暫存檔，超大請求仍會被完整接收；第二段建 multipart API 時要決定請求大小上限（例如檢查 `Content-Length`）（medium）。
- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-player-registration-info.md`
  summary: 段位截圖原始檔名的欄位名、長度上限與清理規則（路徑分隔字元、控制字元）未定。
  evidence: 2026-10-30 Story 3.2 第一段 Code Review（Blind Hunter）。第二段才會存檔名並在 S17、S18 顯示，先記下避免漏掉（low）。
- source_spec: `_bmad-output/implementation-artifacts/spec-5-3-score-rules.md`
  summary: （低）`rounds` 型態的回合數沒有上限，純函式 `scoring.make_game` 接受任意大的非負整數；寫入資料庫的整數欄位時可能溢位。
  evidence: 2026-10-29 Story 5.3 第一階段審查（Edge Case Hunter、Blind Hunter）。第二階段寫 `record_game` 的 API schema 時，以 `Field(ge=0, le=...)` 設定合理範圍（例如 999），回 422。
- source_spec: `_bmad-output/implementation-artifacts/spec-5-1-check-in-panel.md`
  summary: （中）前端單元測試在容器冷啟動時不穩定：`login`、`signup`、`account`、`auth`、`forgot-password` 等走路由的舊測試，在 frontend 容器裡第一次執行會有 4～32 個因等不到元素（預設 1 秒）失敗，同一個容器第二次執行全部通過。CI 若遇到機器忙碌也可能偶發失敗。
  evidence: 2026-10-29 在沒有任何前端改動的分支（story/5-5）上重現：第一次 14 failed／162，第二次 162 passed；與本 Story 的新測試無關。可能的修法：路由測試的 `findBy*` 加長 timeout，或在 `vitest.config.ts` 設 `testTimeout`／預先載入路由，修好後以冷啟動連跑多次確認。

- source_spec: `_bmad-output/implementation-artifacts/spec-4-3-schedule-rules.md`
  summary: （低）competition 純函式（schedule.py；4.1 合併後的 bracket.py、5.5 的 progression.py 也適用）要求的 90% 分支覆蓋率只靠 spec 的手動指令驗證，CI 沒有強制。
  evidence: CI 在 backend 容器內執行 `scripts/test.sh`，其中 `coverage run` 沒有 `--branch`，全域門檻是 `fail_under = 85`。CI 要另加一步 `coverage run --branch -m pytest tests/competition` 再 `coverage report --include=... --fail-under=90`；若改成全域開 branch，要先確認整體覆蓋率仍高於 85%。

- source_spec: `_bmad-output/implementation-artifacts/spec-4-3-schedule-rules.md`
  summary: 4.3 第二階段的改時間 service 呼叫 `reschedule_window`／`check_reschedule` 時，準決賽的 `next_match_at` 要傳決賽與季軍賽中較早的那一場。
  evidence: A 在 #5 的審查：8 強 10:00、準決賽 12:00、決賽 16:00、最小間隔 85 分，先把季軍賽改到 14:00、再把準決賽改到 13:00 都會被允許，但準決賽最早 14:25 才結束。`schedule.py` 只收一個 `next_match_at`，規則（不晚於兩隊要去的下一場）要由呼叫端選對場次；docstring 已註明。
