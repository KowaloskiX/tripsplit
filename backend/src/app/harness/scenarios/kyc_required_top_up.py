from app.core.domain.escrow import KycStatus
from app.core.domain.trips import TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectError,
    ExpectKyc,
    ExpectStatus,
    ExpectWallet,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    TopUp,
    VerifyIdentity,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

KUBA = "Kuba Mazur"

SCENARIO = Scenario(
    name="kyc_required_top_up",
    title="KYC light: top-ups above 1 000 zł need a quick ID check first",
    description=(
        "Nobody has verified their ID at the payment partner yet. Kuba tops up 900 zł — under "
        "the KYC-light threshold, fine. Another 200 zł would take his cumulative top-ups past "
        "1 000 zł, so the partner refuses with `kyc_required` and nothing moves. He verifies "
        "his ID (name + date of birth, no document stored) and the same top-up goes through; "
        "everyone pays and the trip is booked."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    kyc_verified=False,
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectKyc(KUBA, KycStatus.NOT_STARTED),
        TopUp(KUBA, 90_000),
        ExpectWallet(KUBA, balance_minor=90_000),
        ExpectError("kyc_required"),
        TopUp(KUBA, 20_000),
        ExpectWallet(KUBA, balance_minor=90_000),
        VerifyIdentity(KUBA),
        ExpectKyc(KUBA, KycStatus.VERIFIED),
        TopUp(KUBA, 20_000),
        ExpectWallet(KUBA, balance_minor=110_000),
        *(VerifyIdentity(name) for name in (ORGANIZER, *FRIENDS) if name != KUBA),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        Approve("all"),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
