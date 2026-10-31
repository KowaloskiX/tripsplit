from app.core.domain.trips import ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    AdvanceClock,
    CastVotes,
    CheckFundingDeadlines,
    CloseVoting,
    ExpectAgentMessage,
    ExpectError,
    ExpectEscrow,
    ExpectEvent,
    ExpectShares,
    ExpectStatus,
    ExpectWallet,
    GeneratePackages,
    Pay,
    Scenario,
    SetPayBy,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

KUBA = "Kuba Mazur"

SCENARIO = Scenario(
    name="funding_deadline_refund",
    title="Pay-by deadline missed — the escrow refunds every paid share and the trip expires",
    description=(
        "Five friends pay into the trip escrow, Kuba never does. The organizer gives the group "
        "until tomorrow; the deadline passes, the background sweep finds the trip not 100% "
        "funded, transfers every paid share back from the escrow to the members' wallets and "
        "moves the trip to EXPIRED. Nothing was bought, nothing is lost, and Kuba cannot pay "
        "into an expired trip."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectError("invalid_pay_by"),
        SetPayBy(hours=-1),
        SetPayBy(hours=24),
        Pay(everyone_except=[KUBA]),
        ExpectStatus(TripStatus.PAYING),
        AdvanceClock(hours=12),
        CheckFundingDeadlines(),
        ExpectStatus(TripStatus.PAYING),
        AdvanceClock(hours=13),
        CheckFundingDeadlines(),
        ExpectStatus(TripStatus.EXPIRED),
        ExpectEvent(EventKind.FUNDING_EXPIRED),
        ExpectAgentMessage("returned every paid share"),
        ExpectWallet(ORGANIZER, refunded=True),
        ExpectWallet(KUBA, balance_minor=0, refunded=False),
        ExpectShares(status=ContributionStatus.PENDING),
        ExpectEscrow(paid_to_suppliers_minor=0, held_minor=0),
        ExpectError("invalid_trip_state"),
        Pay(members=[KUBA]),
    ),
)
