import { zodResolver } from "@hookform/resolvers/zod";
import type { ReactNode } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { ErrorCallout } from "@/components/ui/callout";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api";

import { useJoinTrip } from "./mutations";
import { type JoinTripValues, joinTripSchema } from "./schema";

export function JoinTripForm({ inviteCode }: { inviteCode: string }): ReactNode {
  const { joinTrip, isPending, error } = useJoinTrip(inviteCode);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<JoinTripValues>({
    resolver: zodResolver(joinTripSchema),
    defaultValues: { displayName: "" },
  });

  return (
    <form className="space-y-4" onSubmit={handleSubmit((values) => joinTrip(values))} noValidate>
      {error && <ErrorCallout>{apiErrorMessage(error)}</ErrorCallout>}
      <Field htmlFor="displayName" label="Your name" error={errors.displayName?.message}>
        <Input
          id="displayName"
          autoComplete="given-name"
          aria-invalid={errors.displayName ? true : undefined}
          aria-describedby="displayName-message"
          {...register("displayName")}
        />
      </Field>
      <Button type="submit" className="w-full" disabled={isPending}>
        {isPending ? "Joining…" : "Join the trip"}
      </Button>
    </form>
  );
}
