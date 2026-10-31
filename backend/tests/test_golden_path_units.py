"""The /plan golden path's party and purchase rules — no database, no browser.

A brief "for 4" made by one organizer who pays for everyone is ONE member travelling with
three guests: every quote, hold, purchase and the agent's vault must count 4, or the re-quote
"lowers" the price to one person's and the demo rail site sells one ticket.
"""

from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from beanie import PydanticObjectId

from app.core.domain.travellers import TravellerDetails, with_guests
from app.core.domain.trips import BookingKind, TransportMode
from app.db.documents import utc_now
from app.models.bookings import Booking
from app.models.trips import Trip, TripMember
from app.services.bookings import readable_reason
from app.services.supplier_prices import party_of
from app.suppliers.demo_rail import purchase_url
from app.suppliers.ports import SearchRequest
from app.suppliers.sim import SIM_URL, sim_supplier

TRIP_ID = PydanticObjectId()


# `model_construct`: Beanie documents cannot be instantiated before `init_beanie`, and these
# rules read plain fields only.
def _trip(group_size: int) -> Trip:
    return Trip.model_construct(
        title="Weekend in Prague",
        origin="Warszawa",
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 22),
        group_size=group_size,
        organizer_id=PydanticObjectId(),
        invite_code="abc12345",
    )


def _member(name: str) -> TripMember:
    return TripMember.model_construct(
        trip_id=TRIP_ID, user_id=PydanticObjectId(), display_name=name
    )


def _booking(passengers: list[TripMember]) -> Booking:
    return Booking.model_construct(
        trip_id=TRIP_ID,
        kind=BookingKind.TRANSPORT,
        title="EC 131",
        supplier="PKP Intercity",
        supplier_url="https://example.com",
        goal="Find and book EC 131",
        amount_minor=62_260,
        passenger_user_ids=[member.user_id for member in passengers],
    )


def test_one_organizer_booking_for_four_counts_four() -> None:
    organizer = _member("Ola")
    assert party_of(_trip(4), _booking([organizer]), [organizer]) == 4


def test_a_part_of_a_split_purchase_counts_its_own_passengers() -> None:
    members = [_member(f"M{index}") for index in range(6)]
    assert party_of(_trip(6), _booking(members[:3]), members) == 3


def test_more_members_than_the_brief_count_every_member() -> None:
    members = [_member(f"M{index}") for index in range(3)]
    assert party_of(_trip(2), _booking(members), members) == 3


def test_guests_travel_on_the_leads_details_under_their_own_names() -> None:
    lead = TravellerDetails(full_name="Ola Nowak", nationality="PL", document_number="EH1")
    padded = with_guests([lead], 3)
    assert [t.full_name for t in padded] == ["Ola Nowak", "Guest2 Nowak", "Guest3 Nowak"]
    assert padded[2].provided_fields() == lead.provided_fields()
    assert with_guests([lead], 1) == [lead]
    assert with_guests([], 3) == []


def test_a_raw_exception_becomes_one_readable_line() -> None:
    raw = (
        "Error('Page.goto: NS_ERROR_UNKNOWN_HOST\\nCall log:\\n - navigating to "
        '"https://sim.tripsplit.invalid/x"\')'
    )
    assert readable_reason(raw) == "Page.goto: NS_ERROR_UNKNOWN_HOST"
    plain = "summary does not match the goal (passenger count 1 != 4)"
    assert readable_reason(plain) == plain
    assert readable_reason("") == "the supplier site did not respond as expected"


def test_the_demo_rail_url_preselects_a_party_one_purchase_can_carry() -> None:
    def passengers(count: int) -> list[str] | None:
        url = purchase_url(
            "http://x/rail",
            origin="A",
            destination="B",
            depart=date(2026, 11, 20),
            back=None,
            passengers=count,
        )
        return parse_qs(urlparse(url).query).get("passengers")

    assert passengers(4) == ["4"]
    assert passengers(1) is None  # the site's default
    assert passengers(6) is None  # split into several purchases, each picks its own


async def test_simulated_trains_are_bought_on_the_demo_rail_site_in_a_demo() -> None:
    request = SearchRequest(
        origin="Warszawa",
        destination="Prague",
        depart_date=date.today() + timedelta(days=20),
        return_date=None,
        party_size=4,
        mode=TransportMode.RAIL,
    )
    demo = sim_supplier("sim_rail", utc_now, purchase_site="http://localhost:8830/rail")
    offers = await demo.search(request)
    assert offers
    query = parse_qs(urlparse(offers[0].purchase_url).query)
    assert offers[0].purchase_url.startswith("http://localhost:8830/rail?")
    assert query["passengers"] == ["4"]
    assert int(query["fare"][0]) * 4 == offers[0].price_minor

    plain = await sim_supplier("sim_rail", utc_now).search(request)
    assert plain[0].purchase_url.startswith(SIM_URL)
