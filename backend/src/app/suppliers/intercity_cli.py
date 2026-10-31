"""`uv run intercity-search Warszawa Praha 2026-11-20 --travellers 6` — real trains and group
prices from PKP Intercity, no LLM. Uses a headless Camoufox page as the HTTP client."""

import argparse
import asyncio
import time
from datetime import date

from app.suppliers.intercity import (
    BrowserTransport,
    HttpTransport,
    IntercityClient,
    Transport,
    summarize,
)


async def _search(args: argparse.Namespace) -> None:
    started = time.monotonic()
    transport: Transport
    if args.http:
        transport = HttpTransport()
        await _run(IntercityClient(transport), args)
    else:
        async with BrowserTransport(headless=not args.headful) as browser:
            print(f"[browser ready in {time.monotonic() - started:.1f}s]")
            await _run(IntercityClient(browser), args)
    print(f"[total {time.monotonic() - started:.1f}s]")


async def _run(client: IntercityClient, args: argparse.Namespace) -> None:
    origin = await client.station(args.origin)
    destination = await client.station(args.destination)
    if origin is None or destination is None:
        print("unknown station")
        return
    print(f"{origin.name} ({origin.code}) -> {destination.name} ({destination.code})")
    connections = await client.connections(origin.code, destination.code, args.day)
    quotes = []
    for connection in connections:
        found = await client.group_quote(
            connection, origin.code, destination.code, args.travellers, args.travel_class
        )
        if found is None:
            print(f"  {connection.departs_at:%H:%M} {connection.label}: no matching fare")
        else:
            quotes.append(found)
    for line in summarize(quotes):
        print("  " + line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("destination")
    parser.add_argument("day", type=date.fromisoformat)
    parser.add_argument("--travellers", type=int, default=1)
    parser.add_argument("--travel-class", type=int, default=2, choices=[1, 2])
    parser.add_argument("--http", action="store_true", help="plain HTTPS instead of a browser")
    parser.add_argument("--headful", action="store_true")
    asyncio.run(_search(parser.parse_args()))


if __name__ == "__main__":
    main()
