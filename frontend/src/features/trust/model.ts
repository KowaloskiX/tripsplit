/**
 * Where an offer comes from and how to check it. Shapes the API will send on package and
 * booking cards (`provenance`, `links[]`, `images[]`); until then the UI is fed fake data.
 */

/** live = a real supplier right now; test/sandbox = a supplier's test system; example = made up. */
export type ProvenanceKind = "live" | "test" | "sandbox" | "example";

export type Provenance = {
  kind: ProvenanceKind;
  /** "PKP Intercity", "Duffel", "LiteAPI". */
  source?: string;
  /** ISO time the offer was last checked against the supplier. */
  checked_at?: string | null;
};

export type TrustLinkKind = "book" | "verify" | "map" | "status";

export type TrustLink = {
  kind: TrustLinkKind;
  label: string;
  url: string;
};

export type TrustImage = {
  url: string;
  alt: string;
};

/** "just now", "2 min ago", "3 h ago" — how fresh a price check is. */
export function checkedAgo(checkedAt: string, now: number = Date.now()): string {
  const minutes = Math.floor((now - Date.parse(checkedAt)) / 60_000);
  if (!Number.isFinite(minutes) || minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.floor(hours / 24)} d ago`;
}

/** The pill's sentence. An example never claims a source, so it can never read as real. */
export function provenanceLabel(provenance: Provenance, now: number = Date.now()): string {
  const source = provenance.source?.trim();
  switch (provenance.kind) {
    case "live": {
      const head = source ? `Live from ${source}` : "Live price";
      return provenance.checked_at
        ? `${head} · checked ${checkedAgo(provenance.checked_at, now)}`
        : head;
    }
    case "test":
      return source ? `${source} test data` : "Test data";
    case "sandbox":
      return source ? `${source} sandbox` : "Sandbox";
    case "example":
      return "Example · not bookable";
  }
}

export function isExample(provenance: Provenance | null | undefined): boolean {
  return provenance?.kind === "example";
}
