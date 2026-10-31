from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectAgentMessage,
    ExpectBookingStatus,
    ExpectEvent,
    ExpectPlanned,
    ExpectPurchases,
    ExpectShares,
    ExpectStatus,
    GeneratePackages,
    Pay,
    PlanDays,
    Scenario,
    StartBookings,
    SupplierSpec,
    VoteAttractions,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="attraction_tickets",
    title="Six friends vote on Prague's sights; the agent buys the museum tickets",
    description=(
        "After the package vote the group votes on attractions while paying, the organizer "
        "plans the days, the planned National Museum visit queues 6 timed-entry tickets (the "
        "shares are re-split), everyone pays, the agent buys the train, the stay and the "
        "tickets for the planned slot on the demo ticket shop, and the plan shows them booked."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=(
        SupplierSpec("sim_rail"),
        SupplierSpec("sim_stay"),
        SupplierSpec("sim_tickets"),
        SupplierSpec("sim_sights"),
    ),
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        VoteAttractions(
            {
                "National Museum": None,
                "Charles Bridge": ("Anna Kowalska", "Kuba Mazur", "Marta Lis", "Piotr Nowak"),
                "Vyšehrad": ("Zosia Wrona", "Tomek Dudek"),
                "Letná Beer Garden": ("Tomek Dudek",),
            }
        ),
        ExpectEvent(EventKind.ATTRACTION_VOTED),
        PlanDays(),
        ExpectEvent(EventKind.ITINERARY_READY),
        ExpectPlanned("National Museum", tickets="to_buy"),
        ExpectPlanned("Charles Bridge"),
        ExpectBookingStatus("activity", BookingStatus.PENDING, count=1),
        ExpectPurchases("activity", (6,)),
        ExpectAgentMessage("tickets for National Museum"),
        ExpectShares(status=ContributionStatus.PENDING, vs_initial="higher"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        ExpectBookingStatus("activity", BookingStatus.AWAITING_APPROVAL),
        ExpectPlanned("National Museum", tickets="buying"),
        Approve("all"),
        ExpectBookingStatus("activity", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
        ExpectPlanned("National Museum", tickets="booked"),
        # Planning again after the purchase keeps the bought slot.
        PlanDays(),
        ExpectPlanned("National Museum", tickets="booked"),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
