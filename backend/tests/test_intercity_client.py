"""PKP Intercity client on recorded answers (2026-10-31) — no network, no browser."""

from datetime import date
from typing import Any

import pytest

from app.suppliers.intercity import (
    MAX_PASSENGERS_PER_PURCHASE,
    IntercityClient,
    parse_connections,
    results_url,
    split_group,
)

STATIONS = [
    {"n": "Warszawa (dowolna stacja)", "h": "5196003"},
    {"n": "Warszawa Centralna", "h": "5100065"},
]
CONNECTIONS = {
    "polaczenia": [
        {
            "pociagi": [
                {
                    "kategoriaPociagu": "EC",
                    "nrPociagu": 131,
                    "nazwaPociagu": "Batory",
                    "dataWyjazdu": "2026-11-20 07:52:00",
                    "dataPrzyjazdu": "2026-11-20 17:52:00",
                }
            ],
            "dataWyjazdu": "2026-11-20 07:52:00",
            "dataPrzyjazdu": "2026-11-20 17:52:00",
            "czasJazdy": 600,
        }
    ]
}


def _fares(passengers: int) -> dict[str, Any]:
    if passengers > MAX_PASSENGERS_PER_PURCHASE:
        return {"ceny": [], "bledy": [{"kod": 254}]}
    one = {"opisyOfert": [{"nazwaOferty": "Super Promo International"}]}
    return {
        "ceny": [
            {
                **one,
                "klasa": 2,
                "cena": 15565 * passengers,
                "czyPropozycjaZwrotna": False,
                "kodPropozycji": f"promo-{passengers}",
                "dataWaznosciPropozycji": "2026-10-31 03:00:47",
                "podrozni": [{}] * passengers,
            },
            {
                "opisyOfert": [{"nazwaOferty": "eNRT"}],
                "klasa": 2,
                "cena": 45091 * passengers,
                "czyPropozycjaZwrotna": True,
                "kodPropozycji": f"flex-{passengers}",
                "dataWaznosciPropozycji": "2026-10-31 03:00:47",
                "podrozni": [{}] * passengers,
            },
        ]
    }


class RecordedTransport:
    def __init__(self) -> None:
        self.fare_requests: list[int] = []

    async def get_json(self, url: str) -> Any:
        return STATIONS

    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        if url.endswith("/Pociagi"):
            return CONNECTIONS
        self.fare_requests.append(len(body["podrozni"]))
        return _fares(len(body["podrozni"]))


@pytest.mark.parametrize(
    ("travellers", "expected"),
    [(1, [1]), (5, [5]), (6, [3, 3]), (8, [4, 4]), (11, [4, 4, 3])],
)
def test_groups_split_into_allowed_purchases(travellers: int, expected: list[int]) -> None:
    assert split_group(travellers) == expected


async def test_station_lookup_skips_the_aggregate_entry() -> None:
    station = await IntercityClient(RecordedTransport()).station("Warszawa")
    assert station is not None and station.code == 5100065


async def test_six_people_are_quoted_as_two_purchases_of_three() -> None:
    transport = RecordedTransport()
    client = IntercityClient(transport)
    connection = (await client.connections(5100065, 5400014, date(2026, 11, 20)))[0]

    quote = await client.group_quote(connection, 5100065, 5400014, travellers=6)

    assert quote is not None
    assert transport.fare_requests == [3, 3]  # never a 6-person request the API rejects
    assert quote.total_minor == 6 * 15565
    assert quote.offer_name == "Super Promo International"
    assert not quote.refundable
    assert [p.proposal_code for p in quote.purchases] == ["promo-3", "promo-3"]


async def test_refundable_fare_is_selectable() -> None:
    client = IntercityClient(RecordedTransport())
    connection = parse_connections(CONNECTIONS)[0]
    quote = await client.group_quote(connection, 5100065, 5400014, 2, refundable=True)
    assert quote is not None and quote.total_minor == 2 * 45091


def test_results_url_is_the_deterministic_e_ic_page() -> None:
    url = results_url(date(2026, 11, 20), 5100065, 5400014, "06:00")
    assert url.startswith("https://ebilet.intercity.pl/polaczenia-miedzynarodowe?dwyj=2026-11-20")
    assert "swyj=5100065" in url and "sprzy=5400014" in url and "time=06%3A00" in url
