"""The simulated world behind the `sim_*` suppliers: places, carriers and realistic prices for
travellers starting in Poland (PLN, grosze, PER PERSON).

The Prague rail fares are the real PKP Intercity offer for 2026-11-20: EC 131 Batory 07:52 ->
17:52 out, EC 117 Silesia 14:08 back, Super Promo International — 466.95 PLN out and 802.80 PLN
back per three passengers in 2nd class, 734.55 + 936.60 PLN in 1st. Everything else is a
plausible approximation; nothing here is bought anywhere.
"""

import zlib
from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True, slots=True)
class Origin:
    name: str
    aliases: tuple[str, ...]
    station: str
    airport: str  # the main airport (LOT, Wizz Air)
    low_cost_airport: str  # where Ryanair flies from
    bus_stop: str


@dataclass(frozen=True, slots=True)
class RailLeg:
    number: str  # "EC 131"
    name: str  # "Batory"
    departs: time
    arrives: time
    second_pp: int
    first_pp: int


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    aliases: tuple[str, ...]
    station: str
    airport: str
    bus_stop: str
    rail_out: RailLeg | None
    rail_back: RailLeg | None
    flight_pp: int  # the cheapest one-way fare (a low-cost carrier)
    flight_minutes: int
    bus_pp: int | None
    bus_minutes: int
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


@dataclass(frozen=True, slots=True)
class Carrier:
    name: str
    code: str  # "LO", "FR", "W6", "N", "RJ"
    price_factor: float
    departs_out: time
    departs_back: time
    low_cost_airport: bool = False

    def number(self, route: str) -> str:
        """A stable flight / bus number per route: the same search gives the same offers."""
        seed = zlib.crc32(f"{self.code}:{route}".encode())
        if self.code == "LO":
            return f"LO {400 + seed % 100}"
        return f"{self.code} {1000 + seed % 9000}"


ORIGINS: tuple[Origin, ...] = (
    Origin(
        "Warszawa",
        ("warszawa", "warsaw", "waw"),
        "Warszawa Centralna",
        "WAW",
        "WMI",
        "Warszawa Zachodnia",
    ),
    Origin("Kraków", ("kraków", "krakow", "cracow", "krk"), "Kraków Główny", "KRK", "KRK", "MDA"),
    Origin("Gdańsk", ("gdańsk", "gdansk", "gdn"), "Gdańsk Główny", "GDN", "GDN", "Gdańsk PKS"),
    Origin("Wrocław", ("wrocław", "wroclaw", "wro"), "Wrocław Główny", "WRO", "WRO", "Wrocław"),
)

AIRLINES: tuple[Carrier, ...] = (
    Carrier("Ryanair", "FR", 1.0, time(6, 25), time(20, 30), low_cost_airport=True),
    Carrier("Wizz Air", "W6", 1.12, time(9, 40), time(18, 10)),
    Carrier("LOT Polish Airlines", "LO", 2.25, time(7, 5), time(16, 40)),
)
BUS_LINES: tuple[Carrier, ...] = (
    Carrier("FlixBus", "N", 1.0, time(7, 15), time(15, 0)),
    Carrier("RegioJet", "RJ", 1.18, time(9, 30), time(17, 30)),
)
RAIL_CARRIER = "PKP Intercity"
RETURN_LEG_FACTOR = 1.08  # flying / riding home on a Sunday costs a little more

PLACES: tuple[Place, ...] = (
    Place(
        name="Prague",
        aliases=("prague", "praha", "prag"),
        station="Praha hl.n.",
        airport="PRG",
        bus_stop="Praha Florenc",
        rail_out=RailLeg("EC 131", "Batory", time(7, 52), time(17, 52), 15_565, 24_485),
        rail_back=RailLeg("EC 117", "Silesia", time(14, 8), time(22, 48), 26_760, 31_220),
        flight_pp=29_900,
        flight_minutes=80,
        bus_pp=14_900,
        bus_minutes=600,
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
    ),
    Place(
        name="Berlin",
        aliases=("berlin",),
        station="Berlin Hbf",
        airport="BER",
        bus_stop="Berlin ZOB",
        rail_out=RailLeg(
            "EC 41", "Berlin-Warszawa-Express", time(8, 0), time(13, 40), 17_900, 29_900
        ),
        rail_back=RailLeg(
            "EC 44", "Berlin-Warszawa-Express", time(15, 37), time(21, 20), 17_900, 29_900
        ),
        flight_pp=27_900,
        flight_minutes=90,
        bus_pp=9_900,
        bus_minutes=540,
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
    Place(
        name="Vienna",
        aliases=("vienna", "wien", "wiedeń", "wieden"),
        station="Wien Hbf",
        airport="VIE",
        bus_stop="Wien Erdberg",
        rail_out=RailLeg("EC 105", "Sobieski", time(8, 0), time(15, 25), 19_900, 32_900),
        rail_back=RailLeg("EC 104", "Sobieski", time(14, 55), time(22, 20), 19_900, 32_900),
        flight_pp=34_900,
        flight_minutes=85,
        bus_pp=15_900,
        bus_minutes=600,
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
    Place(
        name="Budapest",
        aliases=("budapest", "budapeszt"),
        station="Budapest-Keleti",
        airport="BUD",
        bus_stop="Budapest Népliget",
        rail_out=RailLeg("EC 281", "Hungaria", time(6, 58), time(16, 32), 21_900, 34_900),
        rail_back=RailLeg("EC 280", "Hungaria", time(12, 25), time(21, 59), 21_900, 34_900),
        flight_pp=31_900,
        flight_minutes=90,
        bus_pp=11_900,
        bus_minutes=450,
        hostel_dorm_night=5_000,
        hostel_night=8_000,
        apartment_night=15_000,
        hotel_night=27_000,
        apartment_area="the Jewish Quarter",
        hotel_area="Belváros",
        casual_activity="Ruin-bar crawl with a local guide",
        casual_activity_price=11_000,
        splurge_activity="Széchenyi spa evening and Danube dinner cruise",
        splurge_activity_price=26_000,
    ),
    Place(
        name="Barcelona",
        aliases=("barcelona", "barcelonie", "bcn"),
        station="Barcelona Sants",
        airport="BCN",
        bus_stop="Barcelona Nord",
        rail_out=None,
        rail_back=None,
        flight_pp=32_900,
        flight_minutes=205,
        bus_pp=None,
        bus_minutes=0,
        hostel_dorm_night=9_000,
        hostel_night=14_000,
        apartment_night=22_000,
        hotel_night=39_000,
        apartment_area="Gràcia",
        hotel_area="the Gothic Quarter",
        casual_activity="Tapas crawl in El Born",
        casual_activity_price=16_000,
        splurge_activity="Sagrada Família guided tour and a flamenco evening",
        splurge_activity_price=32_000,
    ),
)


def _matches(text: str, aliases: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(alias in folded for alias in aliases)


def find_place(text: str) -> Place | None:
    return next((place for place in PLACES if _matches(text, place.aliases)), None)


def find_origin(text: str) -> Origin:
    """A known Polish city, or a plausible stand-in built from the name."""
    known = next((origin for origin in ORIGINS if _matches(text, origin.aliases)), None)
    if known is not None:
        return known
    code = (text.strip()[:3] or "XXX").upper()
    return Origin(text, (text.casefold(),), text, code, code, text)
