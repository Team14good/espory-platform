# competition 模組介面約定（D 黃鉅燊）

- 狀態：提議中（2026-10-29），請 A、B、C 在 PR 確認
- 依據：`docs/midterm/D-物件設計文件.md`〈五、competition〉、B 文件 MATCH 資料表、epic-4／5／6-context
- 函式都在 `app.modules.competition.service`，第一個參數是 `session: Session`，其餘用關鍵字參數

## 一、competition 提供給其他模組

### Schema（`competition/models.py`）

```python
class MatchRead(BaseModel):
    id: UUID
    tournament_id: UUID
    round_no: int                 # 1 起算；季軍賽與決賽同輪
    slot_no: int                  # 該輪由上到下，1 起算；季軍賽排在決賽之後
    is_third_place: bool
    code: str                     # 顯示用編號 "M3"：依輪次、同輪由上到下，輪空不佔編號
    team_a_id: UUID | None        # 未確定時為 None
    team_b_id: UUID | None
    referee_account_id: UUID | None
    scheduled_at: datetime
    status: MatchStatus
    outcome: MatchOutcome | None
    winner_id: UUID | None
    wins_a: int
    wins_b: int
    forfeit_deadline: datetime | None   # 兩隊都確定才有值
    appeal_deadline: datetime | None
    next_match_id: UUID | None

class BracketRead(BaseModel):
    id: UUID
    tournament_id: UUID
    size: int                     # P
    rounds: int
    drawn_at: datetime
    matches: list[MatchRead]

class PublicMatch(BaseModel):    # 公開 API 用（AD-19）：不含 Email、學校、截圖鍵值
    id: UUID
    code: str
    round_no: int
    slot_no: int
    is_third_place: bool
    team_a: PublicTeamRef | None  # {id, name}
    team_b: PublicTeamRef | None
    source_a: str | None          # 待定時的說明，例如 "M4 勝者"、"M29 敗者"（由 competition/bracket.py 產生）；該方已有隊伍、或確定不會有隊伍（已確認的 walkover、已取消的季軍賽）時為 null
    source_b: str | None
    bye_a: bool                   # a 方由輪空直接進入本輪，前端標「輪空」
    bye_b: bool                   # b 方同上；輪空多於 P÷4 時兩方可能都是輪空
    scheduled_at: datetime
    status: MatchStatus
    outcome: MatchOutcome | None
    winner_id: UUID | None
    wins_a: int
    wins_b: int

class PublicBracket(BaseModel):
    tournament_id: UUID
    rounds: int
    round_names: list[str]        # ["16 強", "8 強", "4 強", "決賽"]（EXPERIENCE.md 用語）
    matches: list[PublicMatch]
    updated_at: datetime          # 前端判斷是否有變動（update-flash）
```

### HTTP API（D 在 4.1 提供，A 的 4.6、5.8 使用）

| 方法與路徑 | 權限 | 回傳 |
| --- | --- | --- |
| `GET /api/v1/tournaments/{tournament_id}/bracket` | 公開 | `PublicBracket`；尚未抽籤回 404 `BRACKET_NOT_FOUND` |
| `POST /api/v1/tournaments/{tournament_id}/draw` | 該賽事主辦方 | `BracketRead` |

### 公開函式

| 函式 | 誰會呼叫 | 說明 | 提供於 |
| --- | --- | --- | --- |
| `get_bracket(session, *, tournament_id) -> BracketRead \| None` | A（4.6、5.8、7.1） | 尚未抽籤回 None | 4.1 |
| `get_public_bracket(session, *, tournament_id) -> PublicBracket \| None` | A（4.6） | 公開對戰樹 | 4.1 |
| `get_match(session, *, match_id) -> MatchRead` | A（5.2）、B（6.1、6.2、6.5） | 不存在拋 `MATCH_NOT_FOUND` 404 | 4.1 |
| `list_team_matches(session, *, tournament_id, team_id) -> list[MatchRead]` | B（6.4、6.5） | 依輪次排序，判斷「還沒比過」「最近一場輸給誰」 | 4.1 |
| `lock_match(session, *, match_id) -> Match` | competition 內的新檔案（A 的 5.2、B 的 6.5） | `SELECT … FOR UPDATE`；同時需要賽事鎖時先鎖賽事（AD-6） | 4.1 |
| `transition_match(session, *, match, to: MatchStatus) -> None` | 同上 | 唯一改場次狀態的入口，非法轉換拋 `MATCH_INVALID_TRANSITION` 409 | 4.1 |
| `start_forfeit_clock(session, *, match) -> None` | 同上 | 唯一設定 `forfeit_deadline` 的入口 | 4.1 |
| `list_forfeit_due(session, *, now) -> list[UUID]` | A（5.2 worker） | 待開打、`forfeit_deadline <= now` 的場次 id | 5.1 |
| `list_check_ins(session, *, match_id) -> list[CheckInRead]` | A（5.2） | `CheckInRead {match_id, team_id, at}` | 5.1 |
| `confirm_match(session, *, match, outcome, winner_id, actor) -> None` | A（5.2）、B（6.2） | 寫入結果、轉為已確認、寫 `confirmed_at`，接著呼叫 `advance` | 5.5 |
| `advance(session, *, match) -> None` | B（6.2 更正後、6.5） | 勝隊進下一場、準決賽敗隊進季軍賽；對手確定不會有隊伍時自動 walkover，季軍賽必要時轉為已取消 | 5.5 |
| `confirm_walkover(session, *, match) -> None` | B（6.5） | 一方確定不會有隊伍時以 walkover 確認並推進 | 5.5 |

申訴相關的 `mark_appealed`、`uphold_result`、`correct_result`、`replay_match`：設計文件放在 MatchService，epic 6 由 disputes 呼叫。**比照 6.6 的 `disqualify`，由 B 寫在 competition 新增的檔案，`service.py` 只新增這幾個公開函式，D 審查。**（B 已確認，2026-10-30）

### 事件（`core.events.publish`，期中只發不通知）

| 事件 | payload | 時機 |
| --- | --- | --- |
| `BracketDrawn` | `tournament_id`, `bracket_id` | 4.1 抽籤完成 |
| `MatchRescheduled` | `match_id`, `scheduled_at` | 4.3 修改時間 |
| `RefereeAssigned` | `match_id`, `referee_account_id` | 4.4 指派或改派 |
| `RefereeUnassigned` | `match_id`, `referee_account_id` | 4.4 收回、5.5 填位後衝突 |
| `MatchResultSubmitted` | `match_id` | 5.4 |
| `MatchResultConfirmed` | `match_id`, `winner_id` | 5.5 |

## 二、competition 需要的上游介面（提議，請 B、C 確認）

名稱沿用 epic context 已列的；新增的標 ★。

### tournaments（B）

| 函式 | 用在 | 需要的內容 |
| --- | --- | --- |
| `get_tournament(session, *, tournament_id) -> TournamentRead` | 4.1、4.3、4.4、5.x | 下表欄位 |
| `lock_tournament(session, *, tournament_id) -> TournamentRead` | 4.1、4.3、4.4、5.5 | `SELECT … FOR UPDATE` 賽事列 |
| `transition_tournament(session, *, tournament_id, to, actor) -> None` | 4.1（→ published）、5.x（→ ongoing、finished） | 非法轉換拋錯 |
| `is_referee(session, *, tournament_id, account_id) -> bool` | 4.4 | 已接受邀請 |
| ★ `list_referees(session, *, tournament_id) -> list[RefereeRead]` | 4.4 的 S30 選單 | `RefereeRead {account_id, display_name}` |
| `bo_for_round(session, *, tournament_id, round_no) -> int` | 4.3、5.3、5.4 | 期中一律回賽事的 BO |

`TournamentRead` 需要的欄位（完整定義與其他函式見 [tournaments.md](tournaments.md)）：

`id`, `organizer_id`, `name`, `status`, `mode`, `capacity`, `registration_end`, `start_at`, `round_interval_minutes`, `forfeit_minutes`, `appeal_minutes`, `bo`, `game_minutes`（遊戲快照的每局預估時間）, `score_type`

### registration（C）

| 函式 | 用在 | 說明 |
| --- | --- | --- |
| ★ `list_accepted_teams(session, *, tournament_id) -> list[TeamRead]` | 4.1 | 正取隊伍 |
| ★ `finalize_for_draw(session, *, tournament_id, actor) -> None` | 4.1 | 開放報名中提前抽籤時呼叫：仍在優先期就先做優先期分配，再做截止補位（`fill_at_deadline`）。分配規則留在 C，competition 只呼叫這一個 |
| ★ `mark_drawn(session, *, tournament_id, team_ids, actor) -> None` | 4.1 | 正取 → 已參賽 |
| `is_member(session, *, team_id, account_id) -> bool` | 4.4（裁判不能是參賽隊員） | |
| ★ `is_captain(session, *, team_id, account_id) -> bool` | 5.1 報到 | |
| ★ `get_team_names(session, *, team_ids) -> dict[UUID, str]` | 4.1 公開對戰樹 | 一次查多隊，避免 N+1 |

## 三、待確認

1. ~~申訴相關函式由誰實作~~：B 實作、D 審查（B 已確認，2026-10-30）。
2. `finalize_for_draw` 合併優先期分配與截止補位，請 C 確認可行。
3. ~~`TournamentRead` 的欄位名稱~~：以 [tournaments.md](tournaments.md) 為準，每局預估時間改名為 `game_minutes`（2026-10-30）。
