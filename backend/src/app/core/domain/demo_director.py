"""The demo director's vocabulary: which script, at what pace, where it is."""

from enum import StrEnum


class DirectorScript(StrEnum):
    FULL = "full"  # join -> chat -> research -> vote -> pay -> (auto) book -> disruption
    VOTE_AND_PAY = "vote_and_pay"  # from an open vote (or open payments) to everyone paid
    DISRUPTION = "disruption"  # a bought train is delayed; rebooking and top-ups


class DirectorPace(StrEnum):
    FAST = "fast"  # rehearsals and tests
    STAGE = "stage"  # ~1.5-3 s between actions: the audience can follow every phone


class DirectorState(StrEnum):
    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"


class DirectorPhase(StrEnum):
    STARTING = "starting"
    JOINING = "joining"
    RESEARCHING = "researching"
    VOTING = "voting"
    PAYING = "paying"
    WAITING_FOR_ORGANIZER = "waiting_for_organizer"
    BOOKING = "booking"
    DISRUPTION = "disruption"
    TOPPING_UP = "topping_up"
    FINISHED = "finished"
