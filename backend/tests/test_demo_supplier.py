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
