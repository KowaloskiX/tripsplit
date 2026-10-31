import { Link } from "@tanstack/react-router";
import { Wallet } from "lucide-react";
import type { ReactNode } from "react";

import { useSession } from "@/features/auth";
import { formatMoney } from "@/lib/money";

import { useWallet } from "./queries";

export function WalletChip({
  balanceMinor,
  currency,
}: {
  balanceMinor: number;
  currency: string;
}): ReactNode {
  return (
    <Link
      to="/wallet"
      aria-label={`Wallet: ${formatMoney(balanceMinor, currency)}`}
      className="inline-flex h-9 items-center gap-2 rounded-full border border-ink/15 px-3.5 text-[13px] font-medium text-ink tabular-nums transition duration-150 hover:border-ink/40"
    >
      <Wallet className="size-4 text-sun" aria-hidden />
      {formatMoney(balanceMinor, currency)}
    </Link>
  );
}

/** The header's balance chip — only for a signed-in user. */
export function HeaderWalletChip(): ReactNode {
  const { user } = useSession();
  const { data } = useWallet(Boolean(user));
  if (!user || !data) return null;
  return <WalletChip balanceMinor={data.balance_minor} currency={data.currency} />;
}
