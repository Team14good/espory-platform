from dataclasses import dataclass

import pytest

from app.core.errors import FieldError
from app.modules.registration.player_profile import rank_score_for


@dataclass(frozen=True)
class Tier:
    name: str
    score: int


TIERS = [Tier("鑽石", 50), Tier("白金", 40), Tier("黃金", 30)]


@pytest.mark.parametrize(("rank_tier", "score"), [("鑽石", 50), ("黃金", 30)])
def test_rank_in_table_returns_its_score(rank_tier: str, score: int) -> None:
    assert rank_score_for(TIERS, rank_tier) == score


@pytest.mark.parametrize(
    "rank_tier",
    ["大師", "", "鑽石 ", " 鑽石", "鑽", "diamond"],
)
def test_rank_not_in_table_is_rejected_on_rank_tier_field(rank_tier: str) -> None:
    with pytest.raises(FieldError) as exc_info:
        rank_score_for(TIERS, rank_tier)

    error = exc_info.value
    assert error.code == "RANK_TIER_NOT_ALLOWED"
    assert error.status_code == 422
    assert error.loc == ("body", "rank_tier")


def test_empty_table_rejects_every_rank() -> None:
    with pytest.raises(FieldError):
        rank_score_for([], "鑽石")


def test_accepts_any_iterable_of_tiers() -> None:
    assert rank_score_for(iter(TIERS), "白金") == 40
