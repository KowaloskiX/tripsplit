import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  bookingsApproveMutation,
  bookingsListQueryKey,
  bookingsStartMutation,
  demoDisruptionMutation,
} from "@/lib/api";

/** Every booking write changes the list — refetch it instead of guessing the new state. */
function useInvalidateBookings(tripId: string): () => Promise<void> {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      queryKey: bookingsListQueryKey({ path: { trip_id: tripId } }),
    });
}

export function useStartBooking(tripId: string) {
  const invalidate = useInvalidateBookings(tripId);
  const mutation = useMutation({ ...bookingsStartMutation(), onSuccess: invalidate });
  return {
    ...mutation,
    start: (bookingId: string): void =>
      mutation.mutate({ path: { trip_id: tripId, booking_id: bookingId } }),
  };
}

export function useApproveBooking(tripId: string) {
  const invalidate = useInvalidateBookings(tripId);
  const mutation = useMutation({ ...bookingsApproveMutation(), onSuccess: invalidate });
  return {
    ...mutation,
    decide: (bookingId: string, approved: boolean): void =>
      mutation.mutate({ path: { trip_id: tripId, booking_id: bookingId }, body: { approved } }),
  };
}

export function useSimulateDisruption(tripId: string) {
  const invalidate = useInvalidateBookings(tripId);
  const mutation = useMutation({ ...demoDisruptionMutation(), onSuccess: invalidate });
  return {
    ...mutation,
    disrupt: (): void =>
      mutation.mutate({
        path: { trip_id: tripId },
        body: { delay_minutes: 140, price_change_percent: 5 },
      }),
  };
}
