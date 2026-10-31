"""選手參賽資料的業務規則（Story 3.2）：段位驗證。

純函式，不碰資料庫。段位對照表來自賽事快照（tournaments 的
`TournamentRead.rank_tiers`，元素有 `name`、`score`）；tournaments 的公開型別
合併前，以本地 `Protocol` 描述需要的欄位。
"""

from collections.abc import Iterable
from typing import Protocol

from app.core.errors import FieldError

RANK_TIER_NOT_ALLOWED_MESSAGE = "段位必須是賽事段位對照表中的段位"


class RankTierLike(Protocol):
    """段位對照表的一列：段位名稱與對應積分。"""

    @property
    def name(self) -> str: ...

    @property
    def score(self) -> int: ...


def rank_score_for(rank_tiers: Iterable[RankTierLike], rank_tier: str) -> int:
    """回傳段位 `rank_tier` 在對照表中的積分；名稱須完全相符。

    不在對照表中時拋 422 `RANK_TIER_NOT_ALLOWED`，`loc` 指向 `rank_tier` 欄位。
    """
    for tier in rank_tiers:
        if tier.name == rank_tier:
            return tier.score
    raise FieldError(
        "RANK_TIER_NOT_ALLOWED",
        RANK_TIER_NOT_ALLOWED_MESSAGE,
        loc=("body", "rank_tier"),
    )
