import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  bookingsApproveMutation,
  bookingsCompleteManuallyMutation,
  bookingsListQueryKey,
  bookingsStartMutation,
  demoDisruptionMutation,
  tripsFeedQueryKey,
  tripsRoomQueryKey,
} from "@/lib/api";

/**
 * Every booking write changes the list, and usually the trip status, shares and feed too —
 * refetch them instead of guessing the new state.
 */
function useInvalidateBookings(tripId: string): () => Promise<void> {
  const queryClient = useQueryClient();
  const path = { trip_id: tripId };
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: bookingsListQueryKey({ path }) }),
      queryClient.invalidateQueries({ queryKey: tripsRoomQueryKey({ path }) }),
      queryClient.invalidateQueries({ queryKey: tripsFeedQueryKey({ path }) }),
    ]);
  };
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

export function useCompleteManually(tripId: string) {
  const invalidate = useInvalidateBookings(tripId);
  const mutation = useMutation({ ...bookingsCompleteManuallyMutation(), onSuccess: invalidate });
  return {
    ...mutation,
    complete: (bookingId: string, confirmationRef: string): void =>
      mutation.mutate({
        path: { trip_id: tripId, booking_id: bookingId },
        body: { confirmation_ref: confirmationRef },
      }),
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
