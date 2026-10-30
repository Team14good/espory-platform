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
- source_spec: `_bmad-output/implementation-artifacts/spec-2-1-game-settings-and-school-list.md`
  summary: Story 2.1 第二階段：S36 遊戲設定（列表、新增／編輯頁、段位表）與學校清單分頁的前端畫面，含側欄入口、375 px 卡片版面，以及學校異動後讓 `["identity","schools"]` 查詢失效。
  evidence: 2026-10-29 使用者決定 2.1 拆兩階段：後台 Sidebar 版面、Data table 由 A 的 1.8 提供（11/1），第一階段只做後端以趕上 2.2 的 10/31 期限。1.8 合併後另寫 spec 實作，並驗收 epics.md Story 2.1 的 S36 相關 AC。
- source_spec: `_bmad-output/implementation-artifacts/spec-2-1-game-settings-and-school-list.md`
  summary: （低）Pydantic 內建的 422 訊息是英文：缺欄位、列舉值不合法（例如 `score_type`）、型別不是 list／object 時，`detail[].msg` 不是繁中，前端直接顯示會出現英文。
  evidence: 2026-10-29 Story 2.1 第一階段審查（Edge Case Hunter）。既有問題，identity 的 API 也一樣（`core/errors.py` 沒有翻譯 `RequestValidationError`）。處理時在 core 加一個 `RequestValidationError` handler，依 `type`（missing、enum、list_type 等）換成繁中訊息，並補測試。
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2-create-tournament.md`
  summary: Story 2.2 第二階段：S25 我的賽事（列表、狀態徽章、空狀態「你還沒有建立賽事。」）、S26 建立賽事表單（選遊戲帶入預設值、每輪間隔不足時顯示最小間隔、欄位錯誤顯示）、S27 賽事總覽（主辦方賽事後台側欄「查看賽事頁」「總覽」、狀態徽章、模式、報名期間、優先期結束、開賽時間），以及接手 1.8 的 `routes/organizer/index.tsx`。
  evidence: 2026-10-30 使用者決定 2.2 拆兩階段：主辦方後台版面、`/organizer` 路由、Data table、狀態徽章由 A 的 1.8（PR #11）提供，第一階段只做後端以趕上 10/31 的交接期限。1.8 合併後另寫 spec，並驗收 epics.md Story 2.2 的畫面 AC；時間輸入需要新增以 Asia/Taipei 輸入、送出 UTC 的處理。
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2-create-tournament.md`
  summary: Story 2.2 第二階段的 S26 表單：名額超過 128 時，送出前彈出提醒「名額超過 128 隊，請確認沒有輸入錯誤」，主辦方確認後才送出（後端不限制 128）。
  evidence: 2026-10-30 使用者決定：128 是提醒門檻、不是上限，避免誤輸入極大值又不擋住真的需要的大型賽事。第一階段後端只擋 < 2 與超過資料庫整數上限。
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2-create-tournament.md`
  summary: （中）目前沒有任何工作把賽事從 `open` 轉成 `closed`，`ensure_accepting_registrations` 也只看狀態；在 C 的 3.6 完成前，報名截止時間過後仍可報名。
  evidence: 2026-10-30 Story 2.2 第一階段審查（Blind Hunter）。依 `contracts/tournaments.md`〈三〉，`open` → `closed` 由 3.6 在截止補位之後呼叫 `transition_tournament`。3.6 實作時要確認截止工作會轉換狀態；若 3.6 延後，改由 `ensure_accepting_registrations` 另外比對 `registration_end` 與 `clock.now()`，並同步修改約定。
