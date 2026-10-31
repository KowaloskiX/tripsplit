"""Deterministic packages — the offline demo and the test double for `PackageResearcher`.

Prices are realistic per-person rates multiplied by the group and the nights, so a six-person
weekend in Prague reads like something you could actually buy. The Prague train is the real
PKP Intercity offer for 2026-11-20: EC 131 Batory 07:52 -> 17:52 out, EC 117 Silesia 14:08
back, Super Promo International 2nd class — 466.95 PLN out and 802.80 PLN back per three
passengers, i.e. 2 539.50 PLN return for six (423.25 PLN per person, scaled per traveller).
Supplier links point at the real supplier home pages the booking agent starts from.

With a per-person budget in the brief the cheaper packages trim themselves to fit (dorm beds
instead of private rooms, no paid evening) — the splurge stays a splurge. Whether a package
still exceeds the budget is flagged where it is stored (`Proposal.over_budget`).
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.ai.research import PackageItemPlan, PackagePlan, TripBrief
from app.core.domain.packages import is_over_budget, per_person
from app.core.domain.trips import BookingKind

INTERCITY_URL = "https://www.intercity.pl/pl/"
BOOKING_URL = "https://www.booking.com/"
GETYOURGUIDE_URL = "https://www.getyourguide.com/"


@dataclass(frozen=True, slots=True)
class _Destination:
    name: str
    station: str
    aliases: tuple[str, ...]
    # The PKP Intercity connections (outbound / return) the train item names.
    outbound_train: str
    return_train: str
    outbound_departs: time
    # Per-person prices in grosze.
    train_2nd_return: int
    train_1st_return: int
    hostel_dorm_night: int
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
    outbound_train="EC 131 Batory (dep. 07:52, arr. 17:52)",
    return_train="EC 117 Silesia (dep. 14:08, arr. 22:48)",
    outbound_departs=time(7, 52),
    # Super Promo International per person: 2nd class (466.95 + 802.80) PLN / 3 on EC 131 +
    # EC 117; 1st class (734.55 + 936.60) PLN / 3 (live PKP quote, EC 116 + EC 117).
    train_2nd_return=42_325,
    train_1st_return=55_705,
    hostel_dorm_night=5_500,
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
        outbound_train="EC Berlin-Warszawa-Express",
        return_train="EC Berlin-Warszawa-Express",
        outbound_departs=time(8, 0),
        train_2nd_return=35_800,
        train_1st_return=59_800,
        hostel_dorm_night=6_000,
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
        outbound_train="EC Sobieski",
        return_train="EC Sobieski",
        outbound_departs=time(8, 0),
        train_2nd_return=39_800,
        train_1st_return=65_800,
        hostel_dorm_night=6_500,
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


_LOCAL = ZoneInfo("Europe/Warsaw")


def _at(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=_LOCAL)


def _fits(plan: PackagePlan, brief: TripBrief) -> bool:
    return not is_over_budget(
        per_person(plan.total_minor, brief.travellers), brief.budget_per_person_minor
    )


class FixtureResearcher:
    async def research(self, brief: TripBrief) -> list[PackagePlan]:
        place = _destination_for(brief)
        people, nights = brief.travellers, brief.nights
        route = f"{brief.origin} -> {place.station}"
        times = (
            f"Outbound {brief.date_from.isoformat()} {place.outbound_train}; return "
            f"{brief.date_to.isoformat()} {place.return_train}."
        )

        def train(travel_class: str, per_person: int) -> PackageItemPlan:
            name = place.outbound_train.split(" (")[0]
            return PackageItemPlan(
                kind=BookingKind.TRAIN,
                title=f"PKP Intercity {name} {route} ({travel_class} class, return)",
                supplier="PKP Intercity",
                supplier_url=INTERCITY_URL,
                price_minor=per_person * people,
                details=f"{times} Super Promo International, {travel_class} class.",
                starts_at=_at(brief.date_from, place.outbound_departs),
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
                starts_at=_at(brief.date_from, time(19)),
            )

        budget = PackagePlan(
            title="Budget: PKP Intercity EC + hostel",
            summary=(
                f"The cheapest way to {place.name}: 2nd class on the morning EuroCity and "
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
        )
        if not _fits(budget, brief):
            budget = PackagePlan(
                title="Budget: PKP Intercity EC + hostel dorm beds",
                summary=(
                    f"The cheapest way to {place.name} we could find for your budget: 2nd "
                    "class on the morning EuroCity and beds in a central hostel dorm."
                ),
                items=(
                    train("2nd", place.train_2nd_return),
                    stay(
                        f"Central hostel in {place.name} (dorm beds)",
                        place.hostel_dorm_night,
                        "Beds in 6-bed dorms, lockers, shared kitchen, rating 8.5+.",
                    ),
                ),
            )
        comfort_items = (
            train("2nd", place.train_2nd_return),
            stay(
                f"Apartment in {place.apartment_area}, {place.name}",
                place.apartment_night,
                "Entire place, 3 bedrooms, kitchen, rating 9+.",
            ),
        )
        comfort = PackagePlan(
            title=f"Comfort: train + apartment in {place.apartment_area} + local evening",
            summary=(
                f"A whole apartment in {place.apartment_area} for the group, the morning "
                f"train and one guided evening: {place.casual_activity}."
            ),
            items=(*comfort_items, activity(place.casual_activity, place.casual_activity_price)),
        )
        if not _fits(comfort, brief):
            comfort = PackagePlan(
                title=f"Comfort: train + apartment in {place.apartment_area}",
                summary=(
                    f"A whole apartment in {place.apartment_area} for the group and the "
                    "morning train — no paid evening, to stay closer to your budget."
                ),
                items=comfort_items,
            )
        splurge = PackagePlan(
            title=f"Weekend splurge: 1st class + hotel in {place.hotel_area} + river evening",
            summary=(
                f"1st class both ways, a 4-star hotel in {place.hotel_area} with breakfast "
                f"and a {place.splurge_activity}."
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
        )
        return [budget, comfort, splurge]
