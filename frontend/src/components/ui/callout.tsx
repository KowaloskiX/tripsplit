import type { ReactNode } from "react";

type CalloutProps = {
  children: ReactNode;
};

/** A form error message. `role="alert"` makes a screen reader announce it immediately. */
export function ErrorCallout({ children }: CalloutProps): ReactNode {
  return (
    <p
      role="alert"
      className="rounded-[var(--radius-control)] bg-danger-soft px-3.5 py-2.5 text-sm text-danger"
    >
      {children}
    </p>
  );
}
