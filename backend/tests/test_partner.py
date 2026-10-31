"""The simulated payment partner and the escrow rules: idempotency, Rule #1 at the partner,
single-use cards limited to the purchase, KYC light, pro-rata leftovers."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.domain.escrow import (
    CardStatus,
    KycLevel,
    KycStatus,
    card_declines,
    deadline_missed,
    kyc_remaining_minor,
    needs_kyc,
    pro_rata,
)
from app.core.domain.result import Err, Ok
from app.db.client import Database
from app.payments.fake_partner import FakePartner
from app.payments.partner import (
    CardCharge,
    CardSecrets,
    KycSubmission,
    PartnerError,
    PartnerOp,
    PayInInstrument,
    PayInMethod,
    SupplierAccount,
    TransferTag,
    WalletOwnerKind,
)
from app.services.escrow import card_charge_from_vault, card_vault, escrow_totals

BLIK = PayInInstrument(method=PayInMethod.BLIK, blik_code="123456")
SUPPLIER = SupplierAccount(supplier_id="sim_flight", display_name="Ryanair")


# ---- domain -----------------------------------------------------------------------------


def test_pro_rata_always_sums_to_the_total() -> None:
    assert pro_rata(100, [1, 1, 1]) == [34, 33, 33]
    assert sum(pro_rata(7, [500, 300, 0, 200])) == 7
    assert pro_rata(10, [0, 0]) == [0, 0]
    assert pro_rata(0, [1]) == [0]


def test_kyc_threshold_and_card_rules() -> None:
    assert not needs_kyc(90_000, 10_000, 100_000, KycLevel.NONE)
    assert needs_kyc(90_000, 10_001, 100_000, KycLevel.NONE)
    assert not needs_kyc(900_000, 10_001, 100_000, KycLevel.LIGHT)
    assert kyc_remaining_minor(30_000, 100_000, KycLevel.NONE) == 70_000
    assert kyc_remaining_minor(30_000, 100_000, KycLevel.LIGHT) is None
    assert card_declines(1_000, 1_000, CardStatus.ACTIVE, expired=False) is None
    assert card_declines(1_000, 1_001, CardStatus.ACTIVE, expired=False) == "amount_over_limit"
    assert card_declines(1_000, 500, CardStatus.INACTIVE, expired=False) == "card_inactive"
    assert card_declines(1_000, 500, CardStatus.USED, expired=False) == "card_closed"
    assert card_declines(1_000, 500, CardStatus.ACTIVE, expired=True) == "card_expired"
    now = datetime(2026, 11, 1, tzinfo=UTC)
    assert deadline_missed(now, now, fully_paid=False)
    assert not deadline_missed(now, now, fully_paid=True)
    assert not deadline_missed(None, now, fully_paid=False)


def test_card_vault_round_trips_to_a_charge() -> None:
    vault = card_vault(CardSecrets(pan="4242123456784242", exp_month=3, exp_year=2028, cvc="071"))
    assert vault["card_expiry"] == "03/28"
    charge = card_charge_from_vault(vault, 5_000, "DemoRail")
    assert (charge.pan, charge.exp_month, charge.exp_year, charge.cvc) == (
        "4242123456784242",
        3,
        2028,
        "071",
    )


# ---- the fake partner -------------------------------------------------------------------


@pytest.fixture
def partner(database: Database) -> FakePartner:
    return FakePartner(database, latency_s=0, kyc_delay=timedelta(0))


async def _funded_member(partner: FakePartner, owner: str, amount: int) -> str:
    wallet = await partner.create_wallet(WalletOwnerKind.USER, owner, "PLN")
    paid = await partner.pay_in(
        wallet, amount, BLIK, owner_ref=owner, idempotency_key=f"in:{owner}"
    )
    assert isinstance(paid, Ok)
    return wallet


async def test_money_calls_are_idempotent(partner: FakePartner) -> None:
    member = await _funded_member(partner, "user:a", 10_000)
    escrow = await partner.create_wallet(WalletOwnerKind.TRIP_ESCROW, "trip:1", "PLN")
    assert escrow == await partner.create_wallet(WalletOwnerKind.TRIP_ESCROW, "trip:1", "PLN")
    first = await partner.transfer(
        member, escrow, 4_000, TransferTag.SHARE, reference="share", idempotency_key="k1"
    )
    replay = await partner.transfer(
        member, escrow, 4_000, TransferTag.SHARE, reference="share", idempotency_key="k1"
    )
    assert isinstance(first, Ok) and isinstance(replay, Ok)
    assert first.value.id == replay.value.id
    assert await partner.balance(member) == 6_000
    assert await partner.balance(escrow) == 4_000
    overdraw = await partner.transfer(
        member, escrow, 6_001, TransferTag.SHARE, reference="share", idempotency_key="k2"
    )
    assert overdraw == Err(PartnerError.INSUFFICIENT_FUNDS)


async def test_escrow_releases_nothing_before_it_is_fully_funded(partner: FakePartner) -> None:
    member = await _funded_member(partner, "user:b", 10_000)
    escrow = await partner.create_wallet(WalletOwnerKind.TRIP_ESCROW, "trip:2", "PLN")
    await partner.set_release_target(escrow, 8_000)
    await partner.transfer(
        member, escrow, 5_000, TransferTag.SHARE, reference="share", idempotency_key="s1"
    )
    early = await partner.payout(escrow, SUPPLIER, 1_000, reference="x", idempotency_key="p1")
    assert early == Err(PartnerError.ESCROW_NOT_FUNDED)
    await partner.transfer(
        member, escrow, 3_000, TransferTag.SHARE, reference="share", idempotency_key="s2"
    )
    paid = await partner.payout(escrow, SUPPLIER, 6_000, reference="x", idempotency_key="p2")
    assert isinstance(paid, Ok) and paid.value.id.startswith("po_")
    reversed_ = await partner.reverse_payout(paid.value.id, idempotency_key="r1")
    assert isinstance(reversed_, Ok)
    assert await partner.balance(escrow) == 8_000


async def test_single_use_card_limited_to_the_purchase(partner: FakePartner) -> None:
    member = await _funded_member(partner, "user:c", 10_000)
    escrow = await partner.create_wallet(WalletOwnerKind.TRIP_ESCROW, "trip:3", "PLN")
    await partner.set_release_target(escrow, 10_000)
    await partner.transfer(
        member, escrow, 10_000, TransferTag.SHARE, reference="share", idempotency_key="s"
    )
    issued = await partner.issue_virtual_card(
        escrow, 7_000, "DemoRail", timedelta(hours=1), idempotency_key="c1"
    )
    assert isinstance(issued, Ok)
    card = issued.value
    assert card.status is CardStatus.INACTIVE and card.pan_last4 == "4242"
    secrets = await partner.reveal_card(card.card_id)
    assert secrets is not None
    charge = CardCharge(
        pan=secrets.pan,
        exp_month=secrets.exp_month,
        exp_year=secrets.exp_year,
        cvc=secrets.cvc,
        amount_minor=6_500,
        merchant="DemoRail",
    )
    # Inactive until the approval funds it.
    assert await partner.charge_card(charge, idempotency_key="x0") == Err(
        PartnerError.CARD_DECLINED
    )
    assert await partner.balance(escrow) == 10_000
    assert isinstance(await partner.activate_card(card.card_id, idempotency_key="a"), Ok)
    assert await partner.balance(escrow) == 3_000  # 7 000 reserved on the card
    over = replace(charge, amount_minor=7_001)
    assert await partner.charge_card(over, idempotency_key="x1") == Err(PartnerError.CARD_DECLINED)
    assert isinstance(await partner.charge_card(charge, idempotency_key="x2"), Ok)
    # Charged once, closed, the unspent 500 back in the escrow.
    used = await partner.card_status(card.card_id)
    assert used is not None and used.status is CardStatus.USED and used.spent_minor == 6_500
    assert await partner.balance(escrow) == 3_500
    again = await partner.charge_card(charge, idempotency_key="x3")
    assert again == Err(PartnerError.CARD_DECLINED)
    totals = escrow_totals(
        await partner.statement(escrow), await partner.cards_funded_by(escrow), escrow
    )
    assert totals.collected_minor == 10_000
    assert totals.paid_to_suppliers_minor == 6_500
    assert totals.balance_minor == totals.expected_held_minor == 3_500


async def test_closing_an_unused_card_returns_its_reserve(partner: FakePartner) -> None:
    member = await _funded_member(partner, "user:d", 5_000)
    escrow = await partner.create_wallet(WalletOwnerKind.TRIP_ESCROW, "trip:4", "PLN")
    await partner.set_release_target(escrow, 5_000)
    await partner.transfer(
        member, escrow, 5_000, TransferTag.SHARE, reference="share", idempotency_key="s"
    )
    issued = await partner.issue_virtual_card(
        escrow, 4_000, "Site", timedelta(hours=1), idempotency_key="c"
    )
    assert isinstance(issued, Ok)
    await partner.activate_card(issued.value.card_id, idempotency_key="a")
    assert await partner.balance(escrow) == 1_000
    closed = await partner.close_card(issued.value.card_id)
    assert closed is not None and closed.status is CardStatus.CLOSED
    assert await partner.balance(escrow) == 5_000


async def test_kyc_light_gates_cumulative_top_ups(partner: FakePartner) -> None:
    wallet = await partner.create_wallet(WalletOwnerKind.USER, "user:e", "PLN")
    first = await partner.pay_in(wallet, 90_000, BLIK, owner_ref="user:e", idempotency_key="1")
    assert isinstance(first, Ok)
    refused = await partner.pay_in(wallet, 20_000, BLIK, owner_ref="user:e", idempotency_key="2")
    assert refused == Err(PartnerError.KYC_REQUIRED)
    verified = await partner.submit_kyc(
        "user:e",
        KycSubmission(legal_name="Ewa Test", birth_date=date(1990, 1, 1), document_number="X123"),
    )
    assert verified.kyc_status is KycStatus.VERIFIED
    passed = await partner.pay_in(wallet, 20_000, BLIK, owner_ref="user:e", idempotency_key="3")
    assert isinstance(passed, Ok)
    assert await partner.balance(wallet) == 110_000


async def test_failure_injection(partner: FakePartner) -> None:
    wallet = await partner.create_wallet(WalletOwnerKind.USER, "user:f", "PLN")
    partner.fail_next(PartnerOp.PAY_IN)
    down = await partner.pay_in(wallet, 1_000, BLIK, owner_ref="user:f", idempotency_key="1")
    assert down == Err(PartnerError.UNAVAILABLE)
    up = await partner.pay_in(wallet, 1_000, BLIK, owner_ref="user:f", idempotency_key="1")
    assert isinstance(up, Ok)
