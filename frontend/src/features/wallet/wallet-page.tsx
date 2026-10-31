import { Plus } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { formatMoney } from "@/lib/money";

import { KycCard } from "./kyc-card";
import { useWallet } from "./queries";
import { TopUpSheet } from "./top-up-sheet";
import { TransactionList } from "./transaction-list";

export function WalletBalance({
  balanceMinor,
  currency,
  onTopUp,
}: {
  balanceMinor: number;
  currency: string;
  onTopUp: () => void;
}): ReactNode {
  return (
    <div className="dark rounded-[var(--radius-panel)] border border-line bg-bg p-6 text-ink sm:p-8">
      <p className="eyebrow text-muted">Wallet balance</p>
      <p className="display mt-3 text-6xl tabular-nums sm:text-7xl">
        {formatMoney(balanceMinor, currency)}
      </p>
      <p className="mt-3 max-w-md text-sm text-muted">
        Your shares are paid from here, and refunds land back here. Demo money: BLIK and card are
        simulated, nothing real is charged.
      </p>
      <p className="mt-2 max-w-md text-xs text-muted">
        Funds held by TripSplit Pay (simulated licensed partner) — TripSplit itself never holds your
        money.
      </p>
      <Button variant="sun" size="lg" className="mt-6" onClick={onTopUp}>
        <Plus className="size-5" aria-hidden /> Top up
      </Button>
    </div>
  );
}

export function WalletPage(): ReactNode {
  const { data, isPending } = useWallet();
  const [open, setOpen] = useState(false);
  if (isPending || !data) return <div className="h-96" aria-hidden />;
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-10 sm:px-6 lg:py-14">
      <WalletBalance
        balanceMinor={data.balance_minor}
        currency={data.currency}
        onTopUp={() => setOpen(true)}
      />
      <KycCard kyc={data.kyc} />
      <Panel>
        <PanelHeader>
          <span>History</span>
          <span>{data.transactions.length} transactions</span>
        </PanelHeader>
        <TransactionList transactions={data.transactions} currency={data.currency} />
      </Panel>
      <TopUpSheet open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
