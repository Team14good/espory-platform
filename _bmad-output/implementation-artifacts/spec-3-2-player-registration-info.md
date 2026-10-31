---
title: 'Story 3.2 選手填寫參賽資料（第一段：與 3.1 無關的部分）'
type: 'feature'
created: '2026-10-30'
status: 'done'
baseline_commit: '7414d3b9abd2be5aa8c64c187615a11448ad9f0b'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 選手要填遊戲 ID、段位並上傳段位截圖，但平台還沒有存檔的 `core.storage`、沒有段位驗證，也沒有上傳元件與 S18 表單。參賽資料要存的 `team_member` 與 S17 名單在 Story 3.1，尚未合併進 `main`。

**Approach:** 本分支（從 `main` 開出，與 story/3-1 獨立）先做不依賴 3.1 的部分：`core.storage`（存檔、讀檔、以 MIME 與大小驗證）、段位驗證純函式、Screenshot uploader 元件、S18 表單元件。3.1 合併後在同一分支 `git merge origin/main`，再接上 `team_member` 欄位與遷移、API、S17 按鈕與平均段位（第二段，記入 deferred-work）。

## Decisions（2026-10-30，邱芯彤）

- story/3-2 從 `main` 開出，與 story/3-1 完全獨立；不重寫 3.1 的模型或遷移檔。
- 依賴 3.1 的部分等 3.1 合併後，在同一分支 merge `origin/main` 再做（第二段）；本段不建 API、不改資料庫。
- spec 篇幅約 2,700 tokens，超過 1600，保留完整 spec，不拆分。

## Boundaries & Constraints

**Always:**
- `core.storage` 不 import 任何模組（AD-3）；只存在 settings 指定的資料夾（容器內為 volume `/app/uploads`），回傳的檔案鍵值不含路徑，資料庫只存鍵值（AD-15）。
- 伺服器驗證同時檢查宣告的 MIME（`image/jpeg`、`image/png`）與檔頭 magic bytes，兩者一致才收；大小超過 5 MB（5 × 1024 × 1024 bytes）拒絕，邊讀邊算，不先整個讀進記憶體再判斷。
- 讀檔時鍵值不合格式（防 `../` 路徑穿越）或不存在，拋業務錯誤。
- 段位只能是賽事快照對照表中的名稱（完全相符），回傳對應積分。
- 前端選檔當下就驗證 JPG／PNG 與 5 MB；錯誤時外框與說明文字用 `destructive`。
- 段位截圖送出後只顯示「已上傳」＋檔名，不顯示圖片（重開 S18 也一樣）。
- 新程式放新檔案，不改 registration 既有四個檔（3.1 大量修改它們，避免合併衝突）。

**Never:**
- 不建立 `team_member` 欄位、遷移檔、registration API，也不重新產生 `frontend/src/client`。
- 不做截圖下載 API（主辦方檢視是 3.8，期中擱置）。
- 不合併 story/3-1 或 story/2-2；不手寫 fetch／axios。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 存合格圖片 | PNG 或 JPG，≤ 5 MB，MIME 與檔頭一致 | 寫入儲存資料夾，回傳鍵值（如 `<uuid hex>.png`） | N/A |
| 格式不符 | MIME 不是 JPG／PNG，或檔頭與 MIME 不符 | 不寫檔 | 415 `UNSUPPORTED_FILE_TYPE`「只接受 JPG 或 PNG 圖片」 |
| 太大 | 超過 5 MB | 不留下檔案 | 413 `FILE_TOO_LARGE`「圖片不能超過 5 MB」 |
| 讀檔 | 合法且存在的鍵值 | 回傳可讀的二進位串流 | N/A |
| 鍵值不合法或不存在 | `../x`、空字串、找不到 | 不讀到資料夾外的檔案 | 404 `FILE_NOT_FOUND` |
| 段位在對照表 | `"鑽石"`，對照表有 | 回傳該段位積分 | N/A |
| 段位不在對照表 | 對照表沒有該名稱 | 拒絕 | 422 `RANK_TIER_NOT_ALLOWED`，`loc` 指向 `rank_tier` |
| 前端選錯檔 | 選 GIF 或 6 MB 的 PNG | 不顯示預覽，顯示錯誤 | 外框與說明文字 `destructive` |

</frozen-after-approval>

## Code Map

- `backend/app/core/config.py` -- `Settings`；新增 `UPLOAD_DIR: Path`（預設 `/app/uploads`，對應 `compose.yml` backend 的 `uploads:/app/uploads`）
- `backend/app/core/errors.py` -- `BusinessError(code, message, status_code)`、`FieldError(code, message, loc=...)`（422，`loc` 對應欄位）
- `backend/app/core/clock.py` -- core 模組的 docstring 與寫法參考
- `backend/tests/core/` -- core 單元測試所在；`tests/test_module_structure.py` 只要求四個分層檔存在，模組內可加新檔
- 段位對照表：`TournamentRead.rank_tiers: list[RankTierRead]`（`name: str`、`score: int`，積分由高到低），定義在 origin/story/2-2 的 `contracts/tournaments.md`，`main` 上還沒有；本段以本地 `Protocol` 描述
- `frontend/src/hooks/useMobile.ts` `useIsMobile()` -- 768px 斷點；測試裡 `matchMedia` 沒有 stub，要自行 mock
- `frontend/src/components/ui/{sheet,dialog,select,form,input,label,button}.tsx` -- 現成元件；沒有 Progress
- `frontend/src/features/identity/LoginForm.tsx` -- react-hook-form＋`zodResolver`＋`FormField`／`FormMessage`＋`LoadingButton` 寫法；`src/lib/api-error.ts` `applyFieldErrors`、`components/common/FormErrorAlert.tsx`
- `frontend/tests/unit/school-picker.test.tsx` -- 單一元件以 `render`＋`userEvent` 測試的範例；`tests/unit/setup.ts` 的 stub
- UX：`ux-designs/.../DESIGN.md:454`（Screenshot uploader）、`:500`（Roster 行，第二段用）；`EXPERIENCE.md:65`（S18）、`:231`（上傳行為）、`:235`（鎖定後唯讀）

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/core/config.py` -- 新增 `UPLOAD_DIR`
- [x] `backend/app/core/storage.py` -- `save_image(stream, *, content_type) -> str`、`open_file(key) -> BinaryIO`；常數 `MAX_IMAGE_BYTES`；驗證與錯誤依 I/O 矩陣；寫到暫存檔、驗證通過才改名，失敗時清掉
- [x] `backend/tests/core/test_storage.py` -- I/O 矩陣的儲存部分；用 `monkeypatch` 把 `UPLOAD_DIR` 指到 `tmp_path`；含剛好 5 MB 可收、多 1 byte 拒絕
- [x] `backend/app/modules/registration/player_profile.py` -- `rank_score_for(rank_tiers, rank_tier) -> int`，不在表內拋 `FieldError("RANK_TIER_NOT_ALLOWED", …, loc=("body","rank_tier"))`
- [x] `backend/tests/registration/test_player_profile.py` -- 段位驗證的單元測試（不需資料庫）
- [x] `frontend/src/features/registration/screenshot-file.ts` -- `validateScreenshotFile(file)`：回傳錯誤訊息或 `null`（與後端同樣的格式與大小規則）
- [x] `frontend/src/features/registration/ScreenshotUploader.tsx` -- 受控元件：虛線拖放區＋outline「選擇圖片」、本機縮圖預覽（`URL.createObjectURL`，移除或卸載時 revoke）、檔名與「移除截圖」鈕、`progress`（0～100，顯示進度條與百分比）、`uploadedFileName`（只顯示「已上傳」＋檔名）、`error`、`disabled`
- [x] `frontend/src/features/registration/PlayerProfileDialog.tsx` -- S18：`useIsMobile()` 決定 `Sheet`／`Dialog`；欄位遊戲 ID（去頭尾空白後必填）、段位 `Select`（選項只來自傳入的 `rankTiers`）、段位截圖（沒有已上傳的截圖時必選）；提示「上場時必須使用這個遊戲 ID」；`readOnly` 時欄位停用、不顯示送出鈕；送出鈕「儲存資料」；`onSubmit(values)` 回傳 Promise，伺服器欄位錯誤以 `applyFieldErrors` 顯示
- [x] `frontend/tests/unit/screenshot-uploader.test.tsx`、`player-profile-dialog.test.tsx` -- 選錯檔、拖放、預覽與移除、已上傳狀態、唯讀、手機／桌機外框、送出值
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- 新增第二段待辦（見 Design Notes）

**Acceptance Criteria:**
- Given S18 開啟，when 選了合格圖片，then 顯示縮圖、檔名與移除鈕；按移除後回到拖放區，可以重選。
- Given 已上傳過截圖，when 重開 S18，then 只顯示「已上傳」＋檔名，沒有圖片。
- Given 手機寬度（< 768px），when 開啟 S18，then 以 `Sheet` 呈現；桌機為 `Dialog`。
- Given 唯讀（名單鎖定），when 開啟 S18，then 所有欄位停用且沒有「儲存資料」鈕。

## Implementation Notes

- 實作時自訂的介面文字（spec 未規定）：S18 標題「我的參賽資料」、說明「填寫遊戲 ID、段位並上傳段位截圖。」、唯讀時「名單已鎖定，資料無法修改。」；拖放區「拖曳圖片到這裡，或」「JPG 或 PNG，5 MB 以內」；已上傳時「更換圖片」；錯誤訊息「找不到這個檔案」（404）、「段位必須是賽事段位對照表中的段位」（422）。
- 表單欄位名與 API 同名（`game_account_id`、`rank_tier`、`rank_screenshot`），第二段的 422 `loc` 可直接對應欄位。
- 選到不合格的檔案時，元件會 `onChange(null)` 清掉原本的選取。
- 開發用資料庫 `app` 的 Alembic 版本停在 3.1 的 `c5d2e8a4f913`（曾在 story/3-1 跑過遷移），本分支沒有該版本，`docker compose up` 的 prestart 會失敗；測試用 `app_test` 不受影響。未處理，由使用者決定 downgrade 或重建。

## Spec Change Log

## Review Triage Log

第 1 輪（2026-10-30；B＝Blind Hunter、E＝Edge Case Hunter、V＝Verification Gap）

| 來源 | 發現 | 判定 | 證據 | 去向 |
| --- | --- | --- | --- | --- |
| V1、B12、E3 | S18 重開時重設表單沒有測試；開啟中 `initialValues` 改變會清掉未送出的輸入 | medium | effect 依賴 `initialGameId`／`initialRankTier`，開啟中父元件重抓到新值就 reset；10 個測試都只渲染一次，刪掉 effect 也全過 | patch |
| B7 | 伺服器 415／413 顯示在表單頂部，前端同樣的錯誤顯示在截圖欄下方 | low | `BusinessError` 走 `FormErrorAlert`；同一個問題兩處顯示，修正只是 catch 內對兩個代碼 `setError` | patch |
| B13、E4 | 上傳中仍可選檔、更換、拖放 | low | 只有「移除截圖」看 `uploading`；S18 以 `isSubmitting` 擋住，但元件獨立使用時不成立 | patch |
| E5 | 拖檔到預覽列，瀏覽器直接開啟檔案、離開頁面 | medium | 預覽列沒有 dragover／drop handler，瀏覽器預設行為會導覽到檔案，表單內容遺失 | patch |
| E6 | 拖曳經過子元素時外框閃爍 | low | `onDragLeave` 在進入子元素時觸發；修正是一行 `relatedTarget` 判斷 | patch |
| E1 | 進度為 NaN 時顯示「上傳中 NaN%」 | low | axios 不知道總長時進度可能非有限數；修正是直接判斷 | patch |
| B3 | `core.storage` 沒有刪檔，換截圖後舊檔永遠留在 volume | medium | 本段沒有更換流程（沒有 API），第二段存檔時才會發生 | defer |
| B6 | 5 MB 在 multipart 整個收完後才檢查，沒有請求大小上限 | medium | Starlette 先把 body spool 到暫存檔；屬第二段 API 的設計 | defer |
| B9 | 截圖原始檔名的長度、清理規則與欄位名未定 | low | 第二段才存檔名；先記下避免漏掉 | defer |
| B1 | spec 不在 diff 中 | false | 審查流程刻意排除，spec 只交給 Edge Case Hunter | reject |
| B2 | 缺 AI 使用紀錄 | false | 紀錄在 bmad-build 結束時新增，不屬程式 diff | reject |
| B4、E8 | 程序被殺時 `.upload-*` 暫存檔殘留 | low | 只在寫入中被 SIGKILL 才發生；清理要另加啟動或排程工作 | reject |
| B5 | `save_image` 是同步 I/O，docstring 沒提醒 | low | 本段沒有呼叫端；第二段 router 依專案慣例用同步 `def` | reject |
| B8 | `image/jpg`、`image/pjpeg`、空 type 的 JPG 被拒 | low | 主流瀏覽器對 .jpg 給 `image/jpeg`；加別名要前後端同步擴充 | reject |
| B10 | 截圖欄 `aria-describedby` 指向不存在的 id | low | 只影響輔助技術的額外描述，錯誤文字本身仍可見；修正要重組 FormItem | reject |
| B11 | 段位對照表為空時無法儲存 | false | 2.1 建立遊戲時 `rank_tiers_required` 至少一筆，賽事快照沿用 | reject |
| B14 | `test_storage.py` 寫死 64 KB、fixture 只在本檔、與參數化案例重複 | low | 不影響正確性；第二段寫 API 測試時再決定 fixture 位置 | reject |
| B15 | 只檢查檔頭、未完整解碼，docstring 沒寫 | false | 模組 docstring 已寫「檔頭 magic bytes」；AD-15 只要求 MIME 與大小驗證 | reject |
| E2 | `initialValues.rank_tier` 不在對照表時 Select 看似空白 | false | 段位對照表是建立賽事時的快照，之後不變（AD-12） | reject |
| E7 | 檔案無讀取權限時回 500 | low | 檔案都由本程序寫入，權限一致 | reject |
| E9 | NFC／NFD 不同的段位名被拒 | low | 前端選項直接取自對照表字串，不會產生不同正規化 | reject |
| E10 | 對照表有重名段位時取第一筆 | false | 2.1 驗證 `rank_tier_name_duplicated`，同遊戲不會重名 | reject |
| E11 | 前端宣稱與後端規則相同，但不檢查檔頭與 0 byte | low | 註解已寫伺服器會再驗檔頭；錯誤會在送出時回 415 | reject |

## Design Notes

第二段（3.1 合併、merge `origin/main` 之後；記入 deferred-work）：`team_member` 加 `game_account_id`、`rank_tier`、`rank_score`、`rank_screenshot_key`、截圖原始檔名與遷移；multipart API（先 `lock_tournament`，只能改自己、名單鎖定時拒絕）；S17「填寫我的資料」、Roster 行與「資料完成／缺：…」、平均段位積分；接上 `onUploadProgress`（生成的 client 的 options 可直接傳 axios 設定）。

進度條沒有 UX 規格：用 2px 高的 `brand` 條＋「上傳中 42%」文字，不新增 shadcn Progress。

## Verification

**Commands:**
- `docker compose up -d --build --wait && docker compose exec -T backend bash scripts/test.sh` -- 全綠
- `docker compose exec -T backend bash scripts/lint.sh` -- 通過
- `docker compose exec -T frontend bun run --filter frontend typecheck`、`bunx biome check`、`bun run test:unit` -- 通過
