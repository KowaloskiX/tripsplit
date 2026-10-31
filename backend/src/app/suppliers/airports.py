"""Which airport code a trip's city flies from, for the flight suppliers. One table, one place.

A city with several airports maps to its IATA **city** code (`LON`, `PAR`, `ROM`, `MIL`): the
airline APIs search all of its airports at once. `WAW` is both Warsaw Chopin and the city code
(it includes Modlin, WMI). Keys are case-folded, in the local and the English spelling, so
"Warszawa", "Warsaw" and "warszawa" all work; a bare three-letter code passes through as is.
"""

import re

_IATA = re.compile(r"^[A-Za-z]{3}$")

# city -> (the code to search with, the airports it covers — for the docs and the feed)
AIRPORTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "warszawa": ("WAW", ("WAW", "WMI")),
    "warsaw": ("WAW", ("WAW", "WMI")),
    "kraków": ("KRK", ("KRK",)),
    "krakow": ("KRK", ("KRK",)),
    "cracow": ("KRK", ("KRK",)),
    "gdańsk": ("GDN", ("GDN",)),
    "gdansk": ("GDN", ("GDN",)),
    "wrocław": ("WRO", ("WRO",)),
    "wroclaw": ("WRO", ("WRO",)),
    "poznań": ("POZ", ("POZ",)),
    "poznan": ("POZ", ("POZ",)),
    "katowice": ("KTW", ("KTW",)),
    "barcelona": ("BCN", ("BCN",)),
    "madrid": ("MAD", ("MAD",)),
    "praha": ("PRG", ("PRG",)),
    "prague": ("PRG", ("PRG",)),
    "berlin": ("BER", ("BER",)),
    "wien": ("VIE", ("VIE",)),
    "vienna": ("VIE", ("VIE",)),
    "budapest": ("BUD", ("BUD",)),
    "lisboa": ("LIS", ("LIS",)),
    "lisbon": ("LIS", ("LIS",)),
    "porto": ("OPO", ("OPO",)),
    "roma": ("ROM", ("FCO", "CIA")),
    "rome": ("ROM", ("FCO", "CIA")),
    "milano": ("MIL", ("MXP", "LIN", "BGY")),
    "milan": ("MIL", ("MXP", "LIN", "BGY")),
    "paris": ("PAR", ("CDG", "ORY", "BVA")),
    "london": ("LON", ("LHR", "LGW", "STN", "LTN", "LCY", "SEN")),
    "londyn": ("LON", ("LHR", "LGW", "STN", "LTN", "LCY", "SEN")),
    "amsterdam": ("AMS", ("AMS",)),
    "dublin": ("DUB", ("DUB",)),
    "athens": ("ATH", ("ATH",)),
    "ateny": ("ATH", ("ATH",)),
    "copenhagen": ("CPH", ("CPH",)),
    "kopenhaga": ("CPH", ("CPH",)),
    "stockholm": ("STO", ("ARN", "BMA", "NYO")),
    "oslo": ("OSL", ("OSL",)),
    "münchen": ("MUC", ("MUC",)),
    "munich": ("MUC", ("MUC",)),
    "monachium": ("MUC", ("MUC",)),
    "zürich": ("ZRH", ("ZRH",)),
    "zurich": ("ZRH", ("ZRH",)),
    "brussels": ("BRU", ("BRU", "CRL")),
    "bruksela": ("BRU", ("BRU", "CRL")),
    "napoli": ("NAP", ("NAP",)),
    "naples": ("NAP", ("NAP",)),
    "malaga": ("AGP", ("AGP",)),
    "málaga": ("AGP", ("AGP",)),
    "valencia": ("VLC", ("VLC",)),
}


def airport_code(place: str) -> str | None:
    """The code a flight search uses for `place`, or None for a city we do not fly from.
    "Warszawa Centralna" style names match on their first word."""
    key = place.strip().casefold()
    if key in AIRPORTS:
        return AIRPORTS[key][0]
    first = key.split(" ")[0] if key else ""
    if first in AIRPORTS:
        return AIRPORTS[first][0]
    if _IATA.fullmatch(place.strip()):
        return place.strip().upper()
    return None
