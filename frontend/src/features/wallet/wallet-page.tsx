import { Plus } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
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
    <div className="rounded-[calc(var(--radius-panel)+6px)] bg-sand-200 p-2 dark:bg-surface-sunken">
      <div className="flex flex-wrap items-end justify-between gap-6 rounded-[var(--radius-panel)] border border-line bg-surface p-6 shadow-card sm:p-8">
        <div>
          <p className="text-sm text-muted">Wallet balance</p>
          <p className="mt-2 text-5xl font-medium tracking-[-0.02em] tabular-nums text-ink sm:text-6xl">
            {formatMoney(balanceMinor, currency)}
          </p>
        </div>
        <Button variant="sun" size="lg" onClick={onTopUp}>
          <Plus className="size-4" aria-hidden /> Top up
        </Button>
      </div>
      <Disclosure
        summary="How the wallet works"
        className="px-4 sm:px-6"
        summaryClassName="py-3 text-[13px]"
      >
        <div className="space-y-2 pb-4 text-sm text-muted">
          <p>
            Your shares are paid from here, and refunds land back here. Demo money: BLIK and card
            are simulated, nothing real is charged.
          </p>
          <p className="text-xs">
            Funds held by Razor Trip Pay (simulated licensed partner) — TripSplit itself never holds
            your money.
          </p>
        </div>
      </Disclosure>
    </div>
  );
}

export function WalletPage(): ReactNode {
  const { data, isPending } = useWallet();
  const [open, setOpen] = useState(false);
  if (isPending || !data) return <div className="h-96" aria-hidden />;
  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-10 sm:px-6 lg:py-16">
      <h1 className="display text-4xl text-ink sm:text-5xl">Wallet</h1>
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
