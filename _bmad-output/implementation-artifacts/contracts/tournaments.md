# tournaments 模組介面約定（B 蘇采羚）

- 狀態：提議中（2026-10-30），請 C、D 在 PR 確認；A 的 5.2、7.1 也會用到
- 依據：`docs/midterm/D-物件設計文件.md`〈tournaments〉、c-d-design-groundwork D-2、epic-2～7-context、`contracts/competition.md`〈二〉
- 函式都在 `app.modules.tournaments.service`，第一個參數是 `session: Session`，其餘用關鍵字參數；service 不 commit（AD-5）
- 「提供於」是預計實作的 Story；還沒合併前，下游照 `contracts/README.md` 用測試替身先寫

## 一、Schema（`tournaments/models.py`）

```python
class RankTierRead(BaseModel):   # 2.1 已實作
    name: str
    score: int

class GameRead(BaseModel):       # 2.1 已實作（平台管理員維護的遊戲設定）
    id: UUID
    name: str
    starters: int
    substitutes: int
    default_bo: int
    game_minutes: int
    score_type: ScoreType
    rank_tiers: list[RankTierRead]   # 積分由高到低

class TournamentRead(BaseModel):
    id: UUID
    organizer_id: UUID
    name: str
    status: TournamentStatus
    mode: TournamentMode             # 期中一律 campus
    capacity: int                    # 正取名額
    registration_start: datetime
    priority_end: datetime           # 優先期結束 = registration_start + 優先期時數（校園賽）
    registration_end: datetime
    start_at: datetime               # 開賽時間（第 1 輪）
    round_interval_minutes: int
    forfeit_minutes: int             # 棄權時限，≥ 15
    appeal_minutes: int              # 申訴期，≥ 30
    livestream_url: str | None
    # 以下來自建立賽事時複製的遊戲快照（AD-12），之後不再讀 GameTitle
    game_id: UUID
    game_name: str
    starters: int
    substitutes: int
    bo: int                          # 賽事的 BO（預設帶入遊戲的 default_bo，主辦方可改）
    game_minutes: int                # 每局預估時間（分鐘）
    score_type: ScoreType
    rank_tiers: list[RankTierRead]   # 段位對照表快照，積分由高到低

class RefereeRead(BaseModel):
    account_id: UUID
    display_name: str
```

- 列舉沿用 `models.py` 既有的 `ScoreType`、`TournamentMode`、`TournamentStatus`。
- 時間一律帶時區（UTC）。
- 不登入就能呼叫的公開 API 用另外的 `Public*` schema（2.4 定義），不含 `organizer_id`、Email 與學校（AD-19）。

## 二、公開函式

| 函式 | 誰會呼叫 | 說明 | 提供於 |
| --- | --- | --- | --- |
| `get_game(session, *, game_id) -> GameRead` | tournaments 內部（2.2）、A（7.1 示範資料） | 不存在拋 `GAME_NOT_FOUND` 404 | 2.1 |
| `get_tournament(session, *, tournament_id) -> TournamentRead` | C（3.x）、D（4.x、5.x）、A（5.2、5.8）、B（6.x） | 不存在拋 `TOURNAMENT_NOT_FOUND` 404 | 2.2 |
| `lock_tournament(session, *, tournament_id) -> TournamentRead` | C（改名單、名額、分配前）、D（4.1、4.3、4.4、5.5）、A（5.2） | `SELECT … FOR UPDATE` 賽事列，回傳鎖定後的最新值；這是鎖賽事的唯一入口（AD-6）。同時要鎖場次時，先鎖賽事 | 2.2 |
| `transition_tournament(session, *, tournament_id, to, actor_id) -> TournamentRead` | 見〈三〉 | 唯一改賽事狀態的入口（AD-11）；呼叫前要先 `lock_tournament`。非法轉換拋 `TOURNAMENT_INVALID_TRANSITION` 409。寫操作紀錄 `tournament.status_changed`；`actor_id=None` 表示系統（worker） | 2.2 |
| `ensure_accepting_registrations(tournament: TournamentRead) -> None` | C（3.1～3.6） | 狀態不是 `open` 時拋 `REGISTRATION_CLOSED` 409。只看狀態：報名截止由 worker 轉成 `closed` | 2.2 |
| `ensure_accepting_scores(tournament: TournamentRead) -> None` | D（5.3、5.4）、B（6.2） | 狀態不是 `published`、`ongoing` 時拋 `TOURNAMENT_NOT_ACCEPTING_SCORES` 409（已結束、已取消都拒絕） | 2.2 |
| `bo_for_round(session, *, tournament_id, round_no) -> int` | D（4.3、5.3、5.4） | 期中一律回傳 `TournamentRead.bo`（2.3 分輪 BO 擱置）；`round_no` 從 1 起算 | 2.2 |
| `is_referee(session, *, tournament_id, account_id) -> bool` | D（4.4） | 已接受該賽事的裁判邀請；只在該賽事有效 | 2.7 |
| `list_referees(session, *, tournament_id) -> list[RefereeRead]` | D（4.4 的 S30 選單） | 依接受邀請的時間排序 | 2.7 |

兩個 `ensure_*` 不碰資料庫，傳入剛鎖定或讀到的 `TournamentRead`，讓呼叫端在同一次鎖定內判斷。

期中不提供（擱置的 Story）：`update_tournament`、`cancel_tournament`（2.5、2.6）、`reset_invite_link`（3.10）、`list_audit_logs`（2.8）。registration 的「提高名額」（FR-9）同樣到期末。

## 三、狀態轉換

| 從 → 到 | 誰呼叫 | 時機 |
| --- | --- | --- |
| `upcoming` → `open` | tournaments 的 worker 工作（2.2） | 報名開始時間到（1 分鐘內） |
| `open` → `closed` | C（3.6 報名截止） | 報名截止時，截止補位之後 |
| `open` → `published`、`closed` → `published` | D（4.1 抽籤） | 抽籤完成；開放報名中提前抽籤時直接從 `open` 轉 |
| `published` → `ongoing` | D（5.x） | 最早一場開放報到時（開賽前 30 分鐘） |
| `ongoing` → `finished` | D（5.5） | 決賽與季軍賽確定（季軍賽取消或不存在也算） |
| 任何非 `finished` → `cancelled` | B（2.6，期中擱置） | 主辦方取消；期中只保留轉換規則與防呆 |
| `closed` → `open` | B（2.5，期中擱置） | 正取不足 2 隊時延長報名 |

中文名稱：尚未開放、開放報名、報名截止、賽程已公布、進行中、已結束、已取消。

## 四、其他約定

- **操作紀錄**：2.2 在 `audit_log.tournament_id` 加上外鍵到 `tournament.id`（`core/audit.py` 的註記）。各模組寫賽事相關的操作紀錄時帶 `tournament_id`。
- **事件**：tournaments 期中不發其他模組需要處理的事件；之後新增時補在這裡。
- **權限**：主辦方對自己賽事的權限，用 `TournamentRead.organizer_id` 交給 `core.authz.ensure_tournament_owner` 判斷。

## 五、回覆 competition.md〈三〉

1. **申訴相關函式**：同意。`mark_appealed`、`uphold_result`、`correct_result`、`replay_match` 由 B 在 6.1、6.2 時寫在 competition 新增的檔案，`competition/service.py` 只新增這幾個公開函式，D 審查。
2. **`TournamentRead` 欄位名稱**：以本文件〈一〉為準。每局預估時間叫 `game_minutes`（與 `GameTitle`、設計文件一致），不叫 `game_minutes_per_game`；`competition.md` 已同步修改。
