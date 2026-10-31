import { CircleAlert, CircleCheck } from "lucide-react";
import type { ReactNode } from "react";

import type { MemberResponse, TravellerField } from "@/lib/api";

export const FIELD_LABEL: Record<TravellerField, string> = {
  full_name: "full name",
  date_of_birth: "date of birth",
  nationality: "nationality",
  document_number: "document number",
  document_expiry: "document expiry",
};

/**
 * Who has entered the traveller details the trip's suppliers need. Shows which fields are
 * missing — never anybody's values.
 */
export function TravellerChecklist({ members }: { members: MemberResponse[] }): ReactNode {
  return (
    <ul className="space-y-1.5" aria-label="Traveller details">
      {members.map((member) => (
        <li key={member.user_id} className="flex items-start gap-2 text-sm">
          {member.traveller_details_complete ? (
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-live" aria-label="complete" />
          ) : (
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" aria-label="missing" />
          )}
          <span className="text-ink">{member.display_name}</span>
          <span className="font-mono text-xs text-muted">
            {member.traveller_details_complete
              ? "details complete"
              : `missing: ${member.traveller_details_missing.map((f) => FIELD_LABEL[f]).join(", ")}`}
          </span>
        </li>
      ))}
    </ul>
  );
}
