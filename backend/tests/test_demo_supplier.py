"""The fake rail supplier walks search -> results -> passengers -> summary -> confirmation."""

from httpx import AsyncClient

from app.services.demo_supplier import TRAINS

BASE = "/api/demo-supplier/rail"
TRIP = {"from": "Warszawa", "to": "Praha", "date": "2026-11-20", "passengers": "2"}


async def test_the_booking_path_end_to_end(client: AsyncClient) -> None:
    search = await client.get(BASE)
    assert search.status_code == 200
    assert search.headers["content-type"].startswith("text/html")
    assert 'action="/api/demo-supplier/rail/results"' in search.text

    results = await client.get(f"{BASE}/results", params=TRIP)
    for train in TRAINS:
        assert train.name in results.text

    chosen = {**TRIP, "train": TRAINS[1].code}
    passengers = await client.get(f"{BASE}/passengers", params=chosen)
    assert "Passenger 2 last name" in passengers.text

    people = {
        **chosen,
        "p1_first": "Anna",
        "p1_last": "Nowak",
        "p2_first": "<script>alert(1)</script>",
        "p2_last": "Kowalski",
        "email": "anna@example.com",
    }
    summary = await client.get(f"{BASE}/summary", params=people)
    assert "Review your booking" in summary.text
    assert "Total: 438.00 PLN" in summary.text
    assert "Pay now" in summary.text
    assert "<script>alert(1)</script>" not in summary.text
    assert "&lt;script&gt;" in summary.text

    first = await client.get(f"{BASE}/confirmation", params=people)
    second = await client.get(f"{BASE}/confirmation", params=people)
    assert "Booking number: DR-" in first.text
    assert first.text == second.text, "the confirmation number is deterministic"


async def test_an_unknown_train_is_a_404_page(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/summary", params={**TRIP, "train": "nope"})
    assert response.status_code == 404
    assert "Search again" in response.text


async def test_more_than_five_passengers_is_refused_like_pkp(client: AsyncClient) -> None:
    six = {**TRIP, "passengers": "6", "train": TRAINS[0].code}
    people = {f"p{n}_{part}": f"X{n}" for n in range(1, 7) for part in ("first", "last")}
    for page in ("results", "passengers", "summary", "confirmation"):
        response = await client.get(f"{BASE}/{page}", params={**six, **people, "email": "a@b.c"})
        assert "Too many passengers: 6" in response.text
        assert "at most 5 passengers" in response.text
        assert "Pay now" not in response.text
        assert "Booking number" not in response.text


async def test_three_passengers_one_part_of_a_split_train_go_through(client: AsyncClient) -> None:
    three = {**TRIP, "passengers": "3", "train": TRAINS[0].code, "email": "a@b.c"}
    people = {f"p{n}_{part}": f"X{n}" for n in range(1, 4) for part in ("first", "last")}
    confirmation = await client.get(f"{BASE}/confirmation", params={**three, **people})
    assert "Booking number: DR-" in confirmation.text
    assert "for 3 passenger(s)" in confirmation.text


async def test_a_return_journey_is_one_order_with_both_legs(client: AsyncClient) -> None:
    trip = {**TRIP, "return": "2026-11-23", "train": TRAINS[0].code, "email": "a@b.c"}
    people = {f"p{n}_{part}": f"X{n}" for n in range(1, 3) for part in ("first", "last")}
    search = await client.get(BASE, params={"date": "2026-11-20", "return": "2026-11-23"})
    assert 'name="return"' in search.text and 'value="2026-11-23"' in search.text

    summary = await client.get(f"{BASE}/summary", params={**trip, **people})
    assert "<th>Return date</th><td>2026-11-23</td>" in summary.text
    # 189.00 PLN per person and leg, two legs, two passengers.
    assert "Total: 756.00 PLN" in summary.text
    assert 'name="return" value="2026-11-23"' in summary.text, "carried to the confirmation"

    one_way = await client.get(f"{BASE}/confirmation", params={**TRIP, **people, "train": "EC-111"})
    back = await client.get(f"{BASE}/confirmation", params={**trip, **people})
    assert "Payment of 756.00 PLN received." in back.text
    assert one_way.text != back.text


async def test_a_fare_parameter_prices_the_journey_at_the_real_fare(client: AsyncClient) -> None:
    trip = {**TRIP, "return": "2026-11-23", "train": TRAINS[2].code, "fare": "56700"}
    results = await client.get(f"{BASE}/results", params=trip)
    assert "567.00 PLN / person, return" in results.text
    summary = await client.get(f"{BASE}/summary", params={**trip, "email": "a@b.c"})
    assert "Total: 1 134.00 PLN" in summary.text
