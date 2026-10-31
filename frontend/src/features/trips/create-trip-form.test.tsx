import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { API_ORIGIN, server } from "@tests/msw-server";
import { renderInRouter } from "@tests/render";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { CreateTripForm } from "@/features/trips";

import { createTripSchema, toCreateTripBody } from "./schema";

const VALID = {
  title: "Weekend in Prague",
  origin: "Warszawa",
  destination: "Praha",
  transportMode: "rail" as const,
  earliestDeparture: "8",
  maxTransfers: "",
  brief: "cheap, good food",
  dateFrom: "2026-11-20",
  dateTo: "2026-11-22",
  groupSize: "6",
  budgetPerPerson: "450,50",
  displayName: "Łukasz",
};

describe("createTripSchema", () => {
  it("accepts a valid trip and converts it to the API shape", () => {
    const parsed = createTripSchema.parse(VALID);
    expect(toCreateTripBody(parsed)).toEqual({
      title: "Weekend in Prague",
      origin: "Warszawa",
      destination: "Praha",
      transport_mode: "rail",
      earliest_departure_hour: 8,
      max_transfers: null,
      brief: "cheap, good food",
      date_from: "2026-11-20",
      date_to: "2026-11-22",
      group_size: 6,
      budget_per_person_minor: 45_050,
      display_name: "Łukasz",
    });
  });

  it("sends no mode or preferences when the group has none", () => {
    const parsed = createTripSchema.parse({
      ...VALID,
      transportMode: "any",
      earliestDeparture: "",
    });
    const body = toCreateTripBody(parsed);
    expect([body.transport_mode, body.earliest_departure_hour, body.max_transfers]).toEqual([
      null,
      null,
      null,
    ]);
  });

  it("sends no budget when the field is empty", () => {
    const parsed = createTripSchema.parse({ ...VALID, budgetPerPerson: "" });
    expect(toCreateTripBody(parsed).budget_per_person_minor).toBeNull();
  });

  it.each([
    [{ dateTo: "2026-11-19" }, "dateTo", "The trip cannot end before it starts."],
    [{ groupSize: "0" }, "groupSize", "A group has between 1 and 20 people."],
    [{ groupSize: "2.5" }, "groupSize", "Enter a whole number of people."],
    [{ budgetPerPerson: "lots" }, "budgetPerPerson", "Enter an amount like 450 or 450.50"],
    [{ title: "   " }, "title", "Give the trip a name."],
    [{ destination: " " }, "destination", "Where are you going?"],
    [{ earliestDeparture: "24" }, "earliestDeparture", "Pick an hour between 0 and 23"],
  ])("rejects %o", (override, field, message) => {
    const result = createTripSchema.safeParse({ ...VALID, ...override });
    expect(result.success).toBe(false);
    const issue = result.error?.issues.find((candidate) => candidate.path[0] === field);
    expect(issue?.message).toContain(message);
  });
});

describe("CreateTripForm", () => {
  it("shows validation errors without calling the API", async () => {
    const user = userEvent.setup();
    await renderInRouter(<CreateTripForm />);

    await user.click(screen.getByRole("button", { name: "Create trip" }));

    expect(await screen.findByText("Give the trip a name.")).toBeInTheDocument();
    expect(screen.getByText("Pick the start date.")).toBeInTheDocument();
    expect(screen.getByText("How should the group call you?")).toBeInTheDocument();
  });

  it("creates the trip and opens its room", async () => {
    let body: unknown;
    server.use(
      http.post(`${API_ORIGIN}/api/trips`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ trip_id: "trip-1", status: "collecting" }, { status: 201 });
      }),
      http.get(`${API_ORIGIN}/api/trips`, () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    const { navigatedTo } = await renderInRouter(<CreateTripForm defaultDisplayName="Ola" />);

    await user.type(screen.getByLabelText("Trip name"), "Weekend in Prague");
    await user.type(screen.getByLabelText("To"), "Praha");
    await user.selectOptions(screen.getByLabelText("Getting there"), "rail");
    await user.type(screen.getByLabelText("Start"), "2026-11-20");
    await user.type(screen.getByLabelText("End"), "2026-11-22");
    await user.click(screen.getByRole("button", { name: "Create trip" }));

    await waitFor(() => expect(navigatedTo()).toBe("/t/trip-1"));
    expect(body).toMatchObject({
      title: "Weekend in Prague",
      destination: "Praha",
      transport_mode: "rail",
      group_size: 6,
      display_name: "Ola",
    });
  });
});
