import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { LinkChips } from "./link-chips";
import { type ApiTrust, imagesFromApi, provenanceFromApi } from "./model";
import { PhotoStrip } from "./photo-strip";
import { ProvenancePill } from "./provenance-pill";

type OfferTrustProps = ApiTrust & {
  /** Alt text for the photos: the offer's title. */
  title: string;
  /** Show the photo strip (stays); transport has no photos worth a row. */
  photos?: boolean;
  inverted?: boolean;
  className?: string;
};

/** Provenance, check-it links and photos of one offer, straight from the API fields. Renders
 *  nothing when the API sent none of them (older records, suppliers without trust data). */
export function OfferTrust({
  links,
  images,
  provenance,
  title,
  photos = true,
  inverted = false,
  className,
}: OfferTrustProps): ReactNode {
  const pill = provenanceFromApi(provenance);
  const shown = photos ? imagesFromApi(images, title) : [];
  const chips = links ?? [];
  if (!pill && chips.length === 0 && shown.length === 0) return null;
  return (
    <div className={cn("space-y-2", className)}>
      {shown.length > 0 && <PhotoStrip images={shown} example={pill?.kind === "example"} />}
      {(pill || chips.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {pill && <ProvenancePill provenance={pill} />}
          <LinkChips links={chips} inverted={inverted} />
        </div>
      )}
    </div>
  );
}
