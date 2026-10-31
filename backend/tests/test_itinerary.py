"""Leg descriptions: one helper, one clock (QA finding 2) — no database."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.domain.itinerary import Leg, describe_itinerary, describe_leg, return_date_of
from app.models.trips import TransportSegment
from app.services.booking_plans import itinerary
from app.suppliers.ports import Segment

WARSAW = ZoneInfo("Europe/Warsaw")
OUT = Leg(
    "EC 111",
    "Warszawa",
    "Praha",
    datetime(2026, 11, 30, 6, 20, tzinfo=WARSAW),
    datetime(2026, 11, 30, 14, 5, tzinfo=WARSAW),
)
BACK = Leg(
    "EC 111",
    "Praha",
    "Warszawa",
    datetime(2026, 12, 3, 6, 20, tzinfo=WARSAW),
    datetime(2026, 12, 3, 14, 5, tzinfo=WARSAW),
)


def test_the_same_moment_reads_the_same_in_utc_and_local_time() -> None:
    """Regression: the goal said 05:20 (UTC, stored segment) and 06:20 (offer details)."""
    utc = (OUT.departs_at.astimezone(UTC), OUT.arrives_at.astimezone(UTC))
    local = describe_leg("EC 111", "Warszawa", "Praha", OUT.departs_at, OUT.arrives_at)
    assert local == "EC 111 Warszawa → Praha 2026-11-30 06:20-14:05"
    assert describe_leg("EC 111", "Warszawa", "Praha", *utc) == local


def test_offer_details_and_the_booking_goal_agree() -> None:
    segment = Segment(
        "Demo rail", OUT.number, OUT.origin, OUT.destination, OUT.departs_at, OUT.arrives_at
    )
    stored = TransportSegment(
        carrier="Demo rail",
        number=OUT.number,
        origin=OUT.origin,
        destination=OUT.destination,
        departs_at=OUT.departs_at.astimezone(UTC),  # what Mongo hands back
        arrives_at=OUT.arrives_at.astimezone(UTC),
    )
    assert itinerary([stored]) == segment.describe()


def test_a_return_journey_labels_its_legs_and_knows_its_return_date() -> None:
    assert return_date_of([OUT, BACK]) == datetime(2026, 12, 3).date()
    assert return_date_of([OUT]) is None
    text = describe_itinerary([OUT, BACK])
    assert text.startswith("outbound EC 111 Warszawa → Praha 2026-11-30 06:20")
    assert "; return EC 111 Praha → Warszawa 2026-12-03 06:20-14:05" in text
