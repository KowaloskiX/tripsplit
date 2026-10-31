"""Deterministic packages — the offline demo and the test double for `PackageResearcher`.

Prices are realistic per-person rates multiplied by the group and the nights, so a six-person
weekend in Prague reads like something you could actually buy. Supplier links point at the
real supplier home pages the booking agent starts from.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from app.ai.research import PackageItemPlan, PackagePlan, TripBrief
from app.core.domain.trips import BookingKind

INTERCITY_URL = "https://www.intercity.pl/pl/"
BOOKING_URL = "https://www.booking.com/"
GETYOURGUIDE_URL = "https://www.getyourguide.com/"


@dataclass(frozen=True, slots=True)
class _Destination:
    name: str
    station: str
    aliases: tuple[str, ...]
    # Per-person prices in grosze.
    train_2nd_return: int
    train_1st_return: int
    hostel_night: int
    apartment_night: int
    hotel_night: int
    apartment_area: str
    hotel_area: str
    casual_activity: str
    casual_activity_price: int
    splurge_activity: str
    splurge_activity_price: int


_PRAGUE = _Destination(
    name="Prague",
    station="Praha hl.n.",
    aliases=("prague", "praha", "prag"),
    train_2nd_return=31_800,
    train_1st_return=51_800,
    hostel_night=8_500,
    apartment_night=16_000,
    hotel_night=29_000,
    apartment_area="Vinohrady",
    hotel_area="the Old Town",
    casual_activity="Czech beer tasting with a local guide",
    casual_activity_price=12_000,
    splurge_activity="Vltava river cruise with dinner",
    splurge_activity_price=21_000,
)

_DESTINATIONS: tuple[_Destination, ...] = (
    _PRAGUE,
    _Destination(
        name="Berlin",
        station="Berlin Hbf",
        aliases=("berlin",),
        train_2nd_return=35_800,
        train_1st_return=59_800,
        hostel_night=9_500,
        apartment_night=18_000,
        hotel_night=32_000,
        apartment_area="Friedrichshain",
        hotel_area="Mitte",
        casual_activity="Street-food tour in Kreuzberg",
        casual_activity_price=14_000,
        splurge_activity="Spree river cruise with dinner",
        splurge_activity_price=23_000,
    ),
    _Destination(
        name="Vienna",
        station="Wien Hbf",
        aliases=("vienna", "wien", "wiedeń", "wieden"),
        train_2nd_return=39_800,
        train_1st_return=65_800,
        hostel_night=10_000,
        apartment_night=19_000,
        hotel_night=34_000,
        apartment_area="Neubau",
        hotel_area="the Innere Stadt",
        casual_activity="Wine tavern evening in Grinzing",
        casual_activity_price=15_000,
        splurge_activity="Danube dinner cruise",
        splurge_activity_price=24_000,
    ),
)


def _destination_for(brief: TripBrief) -> _Destination:
    """The first known city mentioned in the title or brief; Prague is the demo default."""
    text = f"{brief.title} {brief.brief}".lower()
    for destination in _DESTINATIONS:
        if any(alias in text for alias in destination.aliases):
            return destination
    return _PRAGUE


def _at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=UTC)


class FixtureResearcher:
    async def research(self, brief: TripBrief) -> list[PackagePlan]:
        place = _destination_for(brief)
        people, nights = brief.travellers, brief.nights
        route = f"{brief.origin} -> {place.station}"
        times = (
            f"Outbound {brief.date_from.isoformat()} departing 06:00-10:00; return "
            f"{brief.date_to.isoformat()} departing 15:00-19:00."
        )

        def train(travel_class: str, per_person: int) -> PackageItemPlan:
            return PackageItemPlan(
                kind=BookingKind.TRAIN,
                title=f"PKP Intercity EIC {route} ({travel_class} class, return)",
                supplier="PKP Intercity",
                supplier_url=INTERCITY_URL,
                price_minor=per_person * people,
                details=times,
                starts_at=_at(brief.date_from, 7),
            )

        def stay(title: str, per_night: int, details: str) -> PackageItemPlan:
            return PackageItemPlan(
                kind=BookingKind.STAY,
                title=title,
                supplier="Booking.com",
                supplier_url=BOOKING_URL,
                price_minor=per_night * people * nights,
                details=f"{nights} night(s) for {people} guests. {details}",
            )

        def activity(title: str, per_person: int) -> PackageItemPlan:
            return PackageItemPlan(
                kind=BookingKind.ACTIVITY,
                title=title,
                supplier="GetYourGuide",
                supplier_url=GETYOURGUIDE_URL,
                price_minor=per_person * people,
                details=f"Saturday evening, {people} people.",
                starts_at=_at(brief.date_from, 19),
            )

        return [
            PackagePlan(
                title="Budget: PKP Intercity EIC + hostel",
                summary=(
                    f"The cheapest way to {place.name}: 2nd class on the morning train and "
                    "private rooms in a well-rated central hostel."
                ),
                items=(
                    train("2nd", place.train_2nd_return),
                    stay(
                        f"Central hostel in {place.name} (private rooms)",
                        place.hostel_night,
                        "Private 4-6 bed rooms, shared kitchen, rating 8.5+.",
                    ),
                ),
            ),
            PackagePlan(
                title=f"Comfort: train + apartment in {place.apartment_area} + local evening",
                summary=(
                    f"A whole apartment in {place.apartment_area} for the group, the morning "
                    f"train and one guided evening: {place.casual_activity.lower()}."
                ),
                items=(
                    train("2nd", place.train_2nd_return),
                    stay(
                        f"Apartment in {place.apartment_area}, {place.name}",
                        place.apartment_night,
                        "Entire place, 3 bedrooms, kitchen, rating 9+.",
                    ),
                    activity(place.casual_activity, place.casual_activity_price),
                ),
            ),
            PackagePlan(
                title=f"Weekend splurge: 1st class + hotel in {place.hotel_area} + river evening",
                summary=(
                    f"1st class both ways, a 4-star hotel in {place.hotel_area} with breakfast "
                    f"and a {place.splurge_activity.lower()}."
                ),
                items=(
                    train("1st", place.train_1st_return),
                    stay(
                        f"4-star hotel in {place.hotel_area}, {place.name}",
                        place.hotel_night,
                        "Twin rooms with breakfast, rating 8.8+.",
                    ),
                    activity(place.splurge_activity, place.splurge_activity_price),
                ),
            ),
        ]
