import type { AttractionResponse, ItineraryDayResponse, TicketStatus } from "@/lib/api";

const FRIENDS = [
  { user_id: "u1", display_name: "Anna Kowalska" },
  { user_id: "u2", display_name: "Kuba Mazur" },
  { user_id: "u3", display_name: "Marta Lis" },
  { user_id: "u4", display_name: "Piotr Nowak" },
  { user_id: "u5", display_name: "Zosia Wrona" },
  { user_id: "u6", display_name: "Tomek Dudek" },
];

function attraction(
  id: string,
  title: string,
  kind: AttractionResponse["kind"],
  pricePp: number | null,
  provenance = "Demo ticket shop",
): AttractionResponse {
  return {
    attraction_id: id,
    title,
    kind,
    image_url: "",
    website: "https://example.com",
    lat: 50.08,
    lon: 14.42,
    opens: "10:00",
    closes: "18:00",
    duration_minutes: 90,
    price_per_person_minor: pricePp,
    currency: "PLN",
    bookable: pricePp !== null,
    provenance,
    rank: 0,
    votes: 0,
    voters: [],
    voted_by_me: false,
  };
}

export const ATTRACTIONS: readonly AttractionResponse[] = [
  attraction("a1", "National Museum", "museum", 7000),
  attraction("a2", "Charles Bridge", "landmark", null, "live"),
  attraction("a3", "Petřín Lookout Tower", "viewpoint", 3000),
  attraction("a4", "Letná Beer Garden", "food", null, "live"),
];

/** The attractions with `count[i]` of the six friends voting for each. */
export function withVoters(counts: readonly number[]): AttractionResponse[] {
  return ATTRACTIONS.map((item, index) => {
    const voters = FRIENDS.slice(0, counts[index] ?? 0);
    return { ...item, votes: voters.length, voters, voted_by_me: voters.length > 0 };
  });
}

const entry = (
  start: string,
  end: string,
  kind: ItineraryDayResponse["items"][number]["kind"],
  title: string,
  extra: Partial<ItineraryDayResponse["items"][number]> = {},
): ItineraryDayResponse["items"][number] => ({
  start,
  end,
  kind,
  title,
  place: "",
  lat: kind === "attraction" ? 50.08 : null,
  lon: kind === "attraction" ? 14.42 : null,
  link: "",
  map_url: kind === "attraction" ? "https://www.openstreetmap.org/?mlat=50.08&mlon=14.42" : "",
  note: "",
  attraction_id: kind === "attraction" ? title : null,
  tickets: null,
  booking_id: null,
  ...extra,
});

export function planDays(tickets: TicketStatus): ItineraryDayResponse[] {
  return [
    {
      date: "2026-11-20",
      label: "Friday",
      items: [
        entry("07:52", "17:52", "travel", "Arrive in Praha hl.n.", { note: "EC 131" }),
        entry("17:52", "18:37", "travel", "To the hostel, drop the bags"),
        entry("18:45", "19:30", "attraction", "Charles Bridge", { note: "Open 06:00-23:00" }),
        entry("19:30", "21:00", "meal", "Dinner"),
      ],
    },
    {
      date: "2026-11-21",
      label: "Saturday",
      items: [
        entry("10:00", "11:00", "attraction", "Petřín Lookout Tower", { tickets }),
        entry("11:08", "11:30", "travel", "Public transport to Letná Beer Garden"),
        entry("12:00", "13:30", "attraction", "Letná Beer Garden"),
        entry("13:30", "14:00", "travel", "Walk to National Museum"),
        entry("14:00", "16:30", "attraction", "National Museum", { tickets }),
        entry("19:00", "20:30", "meal", "Dinner"),
      ],
    },
    {
      date: "2026-11-22",
      label: "Sunday",
      items: [
        entry("10:00", "12:30", "free", "Free time", { note: "Wander, rest, shop." }),
        entry("12:38", "14:08", "travel", "Pick up the bags, to Praha hl.n."),
        entry("14:08", "21:00", "travel", "Head home from Praha hl.n.", { note: "EC 117" }),
      ],
    },
  ];
}
