import { CreditCard, Users } from "lucide-react";
import { type ReactNode, useEffect } from "react";

import { inviteUrl } from "@/features/trips";
import { KycForm, PayAllForm, useWallet } from "@/features/wallet";
import type { RoomResponse } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import { InviteShare } from "./step-widgets";

export type WhoPays = "invite" | "pay_all";

function ChoiceButton({
  icon,
  title,
  detail,
  active,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  active: boolean;
  onClick: () => void;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex flex-1 items-start gap-3 rounded-[22px] border bg-surface p-4 text-left shadow-card transition active:scale-[0.99]",
        active ? "border-sun ring-2 ring-sun/30" : "border-line hover:border-ink/25",
      )}
    >
      <span className="mt-0.5 text-muted">{icon}</span>
      <span>
        <span className="block text-sm font-medium text-ink">{title}</span>
        <span className="block text-xs text-muted">{detail}</span>
      </span>
    </button>
  );
}

/** "Invite friends to split it" or "I'll pay for everyone" (with an ID check when needed). */
export function WhoPaysStep({
  room,
  choice,
  onChoose,
}: {
  room: RoomResponse;
  choice: WhoPays | null;
  onChoose: (choice: WhoPays) => void;
}): ReactNode {
  const wallet = useWallet();
  const currency = room.trip.currency;
  const outstanding = room.contributions.reduce((sum, share) => sum + share.outstanding_minor, 0);
  const share = room.my_contribution?.amount_minor ?? 0;
  const isOrganizer = room.my_role === "organizer";
  const kyc = wallet.data?.kyc;
  const shortfall = Math.max(0, outstanding - (wallet.data?.balance_minor ?? 0));
  const checking = kyc?.status === "pending";
  const refetch = wallet.refetch;
  useEffect(() => {
    // The partner verifies an ID asynchronously (~1 s): poll until it answers.
    if (!checking) return;
    const timer = window.setInterval(() => void refetch(), 1_000);
    return () => window.clearInterval(timer);
  }, [checking, refetch]);
  const needsId =
    kyc !== undefined &&
    kyc.status !== "verified" &&
    kyc.remaining_minor !== null &&
    shortfall > kyc.remaining_minor;

  return (
    <div className="space-y-3">
      {isOrganizer && (
        <div className="flex flex-col gap-2 sm:flex-row">
          <ChoiceButton
            icon={<Users className="size-5" aria-hidden />}
            title="Invite friends to split it"
            detail={`Each pays their own share (${formatMoney(share, currency)} now).`}
            active={choice === "invite"}
            onClick={() => onChoose("invite")}
          />
          <ChoiceButton
            icon={<CreditCard className="size-5" aria-hidden />}
            title="I'll pay for everyone"
            detail={`${formatMoney(outstanding, currency)} in one BLIK or card payment.`}
            active={choice === "pay_all"}
            onClick={() => onChoose("pay_all")}
          />
        </div>
      )}
      {choice === "invite" && (
        <InviteShare url={inviteUrl(room.invite_code)} title={room.trip.title} />
      )}
      {choice === "pay_all" && checking && (
        <p className="rounded-2xl bg-surface-sunken px-4 py-3 text-sm text-muted">
          Checking your ID with our payment partner…
        </p>
      )}
      {choice === "pay_all" && needsId && !checking && (
        <div className="space-y-2 rounded-[24px] border border-line bg-surface p-4 shadow-card">
          <p className="text-sm text-ink">
            Top-ups above {formatMoney(kyc?.limit_minor ?? 0, currency)} need a quick ID check by
            our payment partner first.
          </p>
          <KycForm />
        </div>
      )}
      {choice === "pay_all" && !needsId && !checking && outstanding > 0 && (
        <PayAllForm
          tripId={room.trip.id}
          totalMinor={outstanding}
          currency={currency}
          onPaid={() => undefined}
        />
      )}
    </div>
  );
}
