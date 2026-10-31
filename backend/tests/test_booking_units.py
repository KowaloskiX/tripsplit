"""Booking rules, the runner's approval wait and the launcher's vault file — no database, no
browser, no LLM."""

import json
import stat
from pathlib import Path

import pytest

from app.agent.launcher import load_vault_file, write_private_json
from app.agent.runner import final_click_mode, read_approval, wait_for_approval
from app.core.domain.bookings import (
    all_confirmed,
    booking_status_after,
    contribution_status,
    format_delta,
    format_money,
    is_valid_run_id,
    repriced_minor,
    resplit,
)
from app.core.domain.trips import AgentOutcome, BookingStatus, ContributionStatus


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_wait_returns_the_decision_once_the_file_appears(tmp_path: Path) -> None:
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now >= 3:
            (tmp_path / "approval.json").write_text('{"approved": true}', encoding="utf-8")

    assert wait_for_approval(str(tmp_path), 900, sleep=sleep, clock=clock) is True
    assert clock.now == 3


def test_wait_reports_a_rejection(tmp_path: Path) -> None:
    (tmp_path / "approval.json").write_text('{"approved": false}', encoding="utf-8")
    assert wait_for_approval(str(tmp_path), 5) is False


def test_wait_times_out_with_none(tmp_path: Path) -> None:
    clock = FakeClock()
    assert wait_for_approval(str(tmp_path), 10, sleep=clock.sleep, clock=clock) is None
    assert clock.now == 10


@pytest.mark.parametrize("content", ["", "{", "[]", '{"approved": "yes"}', '{"other": 1}'])
def test_unreadable_approvals_count_as_no_decision(tmp_path: Path, content: str) -> None:
    (tmp_path / "approval.json").write_text(content, encoding="utf-8")
    assert read_approval(str(tmp_path)) is None


def test_the_final_click_is_simulated_unless_explicitly_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_FINAL_CLICK", raising=False)
    assert final_click_mode() == "simulate"
    monkeypatch.setenv("AGENT_FINAL_CLICK", "yes please")
    assert final_click_mode() == "simulate"
    monkeypatch.setenv("AGENT_FINAL_CLICK", "REAL")
    assert final_click_mode() == "real"


def test_vault_file_is_private_and_outside_the_runs_dir(tmp_path: Path) -> None:
    path = write_private_json({"email": "anna@example.com"})
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert tmp_path not in path.parents
        assert json.loads(path.read_text(encoding="utf-8")) == {"email": "anna@example.com"}
    finally:
        path.unlink()


def test_extra_vault_file_is_flattened_and_tolerant(tmp_path: Path) -> None:
    extra = tmp_path / "vault.json"
    extra.write_text('{"phone": "+48600000000", "empty": "", "n": 3}', encoding="utf-8")
    assert load_vault_file(extra) == {"phone": "+48600000000", "n": "3"}
    assert load_vault_file(tmp_path / "missing.json") == {}
    assert load_vault_file(None) == {}


@pytest.mark.parametrize("run_id", ["b6ae5-1", "e2e_rail", "A" * 64])
def test_valid_run_ids(run_id: str) -> None:
    assert is_valid_run_id(run_id)


@pytest.mark.parametrize("run_id", ["", "../x", "a/b", "a.b", "A" * 65, "a\nb", "a b"])
def test_invalid_run_ids(run_id: str) -> None:
    assert not is_valid_run_id(run_id)


def test_outcomes_map_onto_booking_states() -> None:
    assert booking_status_after(AgentOutcome.DONE) is BookingStatus.CONFIRMED
    assert booking_status_after(AgentOutcome.HANDOFF) is BookingStatus.HANDOFF
    for outcome in (AgentOutcome.STUCK, AgentOutcome.MAX_STEPS, AgentOutcome.ERROR):
        assert booking_status_after(outcome) is BookingStatus.FAILED


def test_cancelled_bookings_do_not_block_the_trip() -> None:
    assert all_confirmed([BookingStatus.CONFIRMED, BookingStatus.CANCELLED])
    assert not all_confirmed([BookingStatus.CONFIRMED, BookingStatus.RUNNING])
    assert not all_confirmed([BookingStatus.CANCELLED])


@pytest.mark.parametrize(
    ("amount", "percent", "expected"),
    [
        (120_000, 5, 126_000),
        (120_000, 3.33, 123_996),
        (999, 0.05, 999),
        (1_001, 50, 1_502),
        (100, -100, 0),
        (12_345, -10, 11_111),
    ],
)
def test_repricing_rounds_half_up_to_grosze(amount: int, percent: float, expected: int) -> None:
    assert repriced_minor(amount, percent) == expected


def test_contribution_status_after_a_resplit() -> None:
    assert contribution_status(100, 99) is ContributionStatus.PENDING
    assert contribution_status(100, 100) is ContributionStatus.PAID
    assert contribution_status(100, 101) is ContributionStatus.REFUND_DUE


def test_resplit_sums_exactly_and_reports_deltas() -> None:
    changes = resplit(100_005, [16_667] * 6, [16_667] * 6)
    assert sum(change.share_minor for change in changes) == 100_005
    assert [change.delta_minor for change in changes] == [1, 1, 1, 0, 0, 0]
    assert [change.status for change in changes][:3] == [ContributionStatus.PENDING] * 3
    assert changes[3].status is ContributionStatus.PAID


def test_money_formatting() -> None:
    assert format_money(124_000, "PLN") == "1 240.00 PLN"
    assert format_money(5, "PLN") == "0.05 PLN"
    assert format_delta(1_200, "PLN") == "+12.00 PLN"
    assert format_delta(-1_200, "PLN") == "-12.00 PLN"
