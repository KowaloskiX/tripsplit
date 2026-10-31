import { create } from "zustand";
import { persist } from "zustand/middleware";

type DemoUiState = {
  /** The six-phone stage view above the room (the headline demo scene). */
  stageView: boolean;
  setStageView: (on: boolean) => void;
};

// Persisted so a reload on stage keeps the view; a one-paint delay is fine for a dev panel.
export const useDemoUiStore = create<DemoUiState>()(
  persist(
    (set) => ({
      stageView: false,
      setStageView: (stageView) => set({ stageView }),
    }),
    { name: "demo-ui" },
  ),
);
