"""The money rule is pure arithmetic, so it is tested without a database."""

import pytest

from app.core.domain.trips import is_fully_paid, split_evenly


@pytest.mark.parametrize(
    ("total", "members"),
    [(120_000, 6), (100_001, 6), (5, 6), (0, 3), (99_999, 7), (1, 1)],
)
def test_split_sums_exactly_to_the_total(total: int, members: int) -> None:
    shares = split_evenly(total, members)
    assert len(shares) == members
    assert sum(shares) == total
    assert max(shares) - min(shares) <= 1


def test_split_rejects_an_empty_group() -> None:
    with pytest.raises(ValueError):
        split_evenly(100, 0)


def test_booking_waits_for_every_share() -> None:
    assert is_fully_paid([100, 100], [100, 100])
    assert is_fully_paid([100, 100], [150, 100])
    assert not is_fully_paid([100, 100], [100, 99])
    assert not is_fully_paid([100, 100], [100])
