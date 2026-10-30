"""資源層級的權限判斷（AD-10）：只比對呼叫端已載入的資料，不查資料庫。

core 不能 import 模組（AD-3），所以這裡以 Protocol 描述需要的欄位；
tournaments 的 `TournamentRead` 等任何帶 `organizer_id` 的物件都可以傳入。
"""

import uuid
from typing import Protocol

from app.core.errors import BusinessError


class OwnedTournament(Protocol):
    @property
    def organizer_id(self) -> uuid.UUID: ...


def ensure_tournament_owner(tournament: OwnedTournament, account_id: uuid.UUID) -> None:
    """帳號是賽事的主辦方；否則拋 403 `TOURNAMENT_OWNER_REQUIRED`。"""
    if tournament.organizer_id != account_id:
        raise BusinessError(
            "TOURNAMENT_OWNER_REQUIRED",
            "只有這場賽事的主辦方可以使用這個功能。",
            status_code=403,
        )
