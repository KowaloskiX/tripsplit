import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AvatarStack, initialsOf } from "./avatar";

describe("AvatarStack", () => {
  it("overlaps circles by less than the second initial's margin (no 'ON' -> 'OI')", () => {
    render(
      <AvatarStack
        people={[
          { id: "1", name: "Ola Nowak" },
          { id: "2", name: "Kuba Mazur" },
        ]}
      />,
    );
    const circles = Array.from(screen.getByRole("img").children);
    expect(circles.map((circle) => circle.textContent)).toEqual(["ON", "KM"]);
    // 32 px circles, 4 px overlap + 2 px ring: the initials (centred, ~14 px wide) stay clear.
    expect(circles[0]?.className).toContain("size-8");
    expect(circles[1]?.className).toContain("-ml-1");
    expect(circles[1]?.className).not.toMatch(/-ml-(1\.5|2|3)/);
  });

  it("takes initials from the first and last word", () => {
    expect(initialsOf("Kuba Mazur")).toBe("KM");
    expect(initialsOf("ola")).toBe("OL");
  });
});
