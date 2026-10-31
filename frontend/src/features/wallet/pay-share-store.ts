import { create } from "zustand";

/**
 * The "Pay my share" sheet's UI state. A store rather than component state, because paying
 * changes the room under the sheet (paying -> booking re-arranges the page): the sheet must
 * survive its parent re-mounting while the bank confirms.
 */
type PayShareState = {
  tripId: string | null;
  /** The share when the sheet opened — it stays shown after the room says "paid". */
  shareMinor: number;
  topUpId: string | null;
  paid: boolean;
  open: (tripId: string, shareMinor: number) => void;
  setTopUp: (topUpId: string | null) => void;
  markPaid: () => void;
  close: () => void;
};

export const usePayShareStore = create<PayShareState>((set) => ({
  tripId: null,
  shareMinor: 0,
  topUpId: null,
  paid: false,
  open: (tripId, shareMinor) => set({ tripId, shareMinor, topUpId: null, paid: false }),
  setTopUp: (topUpId) => set({ topUpId }),
  markPaid: () => set({ paid: true }),
  close: () => set({ tripId: null, topUpId: null, paid: false }),
}));
