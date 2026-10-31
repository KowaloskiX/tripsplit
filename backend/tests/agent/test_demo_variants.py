"""The perturbed demo rail sites: each variant changes exactly what it claims to."""

from httpx import AsyncClient

from app.services import demo_supplier_variants as v
from app.services.demo_supplier import TRAINS

TRIP = {"from": "Warszawa", "to": "Praha", "date": "2026-12-04", "passengers": "3"}
CHOSEN = {**TRIP, "train": TRAINS[1].code}
PEOPLE = {
    **CHOSEN,
    **{f"p{i}_{part}": f"N{i}{part}" for i in range(1, 4) for part in ("first", "last")},
    "email": "a@b.c",
}


def _html(
    variant: str, page: str, params: dict[str, str], cookies: dict[str, str] | None = None
) -> str:
    answer = v.render(variant, page, params, cookies or {})
    assert answer.status == 200, answer.html
    return answer.html


def test_baseline_matches_the_demo_site_labels() -> None:
    assert ">Search</button>" in _html("baseline", "", TRIP)
    assert "Passenger 3 last name" in _html("baseline", "passengers", CHOSEN)
    assert "Total: 657.00 PLN" in _html("baseline", "summary", PEOPLE)


def test_renamed_and_reordered_and_extra() -> None:
    assert "Szukaj połączeń" in _html("renamed_buttons", "", TRIP)
    reordered = _html("reordered_fields", "passengers", CHOSEN)
    assert reordered.index('id="email"') < reordered.index('id="p1_first"')
    assert reordered.index('id="p1_last"') < reordered.index('id="p1_first"')
    extra = _html("extra_fields", "passengers", CHOSEN)
    assert 'name="phone"' in extra and 'name="newsletter"' in extra


def test_cookie_wall_until_consent() -> None:
    wall = v.render("cookie_wall", "results", TRIP, {})
    assert "Accept all cookies" in wall.html and not wall.set_consent_cookie
    accepted = v.render("cookie_wall", "results", {**TRIP, "consent": "1"}, {})
    assert accepted.set_consent_cookie and "EC 113 Vltava" in accepted.html
    assert "EC 113" in _html("cookie_wall", "results", TRIP, {v.CONSENT_COOKIE: "1"})


def test_split_pages_carry_the_first_half() -> None:
    first = _html("split_pages", "passengers", CHOSEN)
    assert "Passenger 2 first name" in first and "Passenger 3" not in first
    assert 'action="/api/demo-supplier/rail-variants/split_pages/passengers-2"' in first
    second = _html("split_pages", "passengers-2", {**CHOSEN, "p1_first": "A", "p1_last": "B"})
    assert "Passenger 3 first name" in second and 'name="p1_first" value="A"' in second


def test_failure_variants() -> None:
    sold = _html("sold_out", "results", TRIP)
    assert "Sold out" in sold and "aria-label=" not in sold
    assert "g-recaptcha" in _html("captcha", "passengers", CHOSEN)
    assert "Total: 821.25 PLN" in _html("price_changed_on_summary", "summary", PEOPLE)
    slow = v.render("slow", "", TRIP, {})
    assert slow.delay_s > 0 and 'class="slow"' in slow.html


def test_unknown_variant_or_page_is_404() -> None:
    assert v.render("nope", "", TRIP, {}).status == 404
    assert v.render("baseline", "admin", TRIP, {}).status == 404


async def test_the_route_serves_variants_and_sets_the_consent_cookie(client: AsyncClient) -> None:
    base = "/api/demo-supplier/rail-variants"
    page = await client.get(f"{base}/renamed_buttons")
    assert page.status_code == 200 and "Szukaj połączeń" in page.text
    consent = await client.get(f"{base}/cookie_wall/results", params={**TRIP, "consent": "1"})
    assert v.CONSENT_COOKIE in consent.headers.get("set-cookie", "")
    assert (await client.get(f"{base}/nope")).status_code == 404
