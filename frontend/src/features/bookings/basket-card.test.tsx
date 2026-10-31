import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { API_ORIGIN, server } from "@tests/msw-server";
import { renderInRouter } from "@tests/render";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import type { BookingResponse, TripBookingsResponse } from "@/lib/api";

import { BasketCard } from "./basket-card";
import { BookEverything } from "./book-everything";

function booking(overrides: Partial<BookingResponse>): BookingResponse {
  return {
    id: "b1",
    trip_id: "t1",
    kind: "transport",
    mode: "rail",
    title: "EC 131 Warszawa -> Praha",
    supplier: "PKP Intercity",
    supplier_url: "https://ebilet.intercity.pl",
    supplier_id: "pkp_intercity",
    channel: "agent",
    hold_expires_at: null,
    amount_minor: 86_835,
    status: "awaiting_approval",
    confirmation_ref: null,
    replaces_booking_id: null,
    passenger_user_ids: ["u1", "u2", "u3"],
    run: null,
    ...overrides,
  };
}

function trip(bookings: BookingResponse[], overrides: Partial<TripBookingsResponse> = {}) {
  return {
    trip_id: "t1",
    trip_status: "booking",
    currency: "PLN",
    total_minor: 0,
    travellers: 6,
    is_organizer: true,
    bookings,
    ...overrides,
  } satisfies TripBookingsResponse;
}

describe("BasketCard", () => {
  it("lists every purchase awaiting approval and approves them in one click", async () => {
    let called = 0;
    server.use(
      http.post(`${API_ORIGIN}/api/trips/t1/bookings/approve-all`, () => {
        called += 1;
        return HttpResponse.json({ trip_status: "booking", items: [] });
      }),
    );
    const basket = trip([
      booking({ id: "b1" }),
      booking({ id: "b2", title: "EC 131 second purchase" }),
      booking({
        id: "b3",
        kind: "stay",
        title: "Old Town hotel",
        channel: "api",
        amount_minor: 120_000,
      }),
      booking({ id: "b4", status: "confirmed", title: "Already bought" }),
    ]);
    const user = userEvent.setup();
    await renderInRouter(<BasketCard trip={basket} />);

    expect(screen.getByText("Old Town hotel")).toBeInTheDocument();
    expect(screen.queryByText("Already bought")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve basket (total 2 936.70 PLN)" }));
    await waitFor(() => expect(called).toBe(1));
  });

  it("is not shown to a member or when nothing waits", async () => {
    await renderInRouter(
      <>
        <BasketCard trip={trip([booking({})], { is_organizer: false })} />
        <BasketCard trip={trip([booking({ status: "running" })])} />
      </>,
    );
    expect(screen.queryByRole("region", { name: "Approve the basket" })).not.toBeInTheDocument();
  });
});

describe("BookEverything", () => {
  it("starts every purchase and names the ones that could not start", async () => {
    server.use(
      http.post(`${API_ORIGIN}/api/trips/t1/bookings/start-all`, () =>
        HttpResponse.json(
          {
            trip_status: "booking",
            items: [
              { booking: booking({ status: "running" }), error: null },
              {
                booking: booking({ id: "b2", title: "Flight to BCN", status: "pending" }),
                error: "traveller_details_missing",
              },
            ],
          },
          { status: 202 },
        ),
      ),
    );
    const user = userEvent.setup();
    await renderInRouter(
      <BookEverything
        trip={trip([booking({ status: "pending" }), booking({ id: "b2", status: "pending" })])}
      />,
    );
    await user.click(screen.getByRole("button", { name: /Book everything \(2 purchases\)/ }));
    expect(
      await screen.findByText(/Flight to BCN: some travellers still need to add their details/),
    ).toBeInTheDocument();
  });

  it("has nothing to start while the group is still paying", async () => {
    await renderInRouter(
      <BookEverything trip={trip([booking({ status: "pending" })], { trip_status: "paying" })} />,
    );
    expect(screen.queryByRole("button", { name: /Book everything/ })).not.toBeInTheDocument();
  });
});
