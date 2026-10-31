import { describe, expect, it } from "vitest";

import { handedOff, type PhoneState, progressOf } from "./model";

function phone(voted: boolean, paid: boolean): PhoneState {
  return {
    name: "Ola Nowak",
    initials: "ON",
    last_message: null,
    voted_for: voted ? "Old Town by train" : null,
    paid,
    amount: 59_300,
  };
}

describe("progressOf", () => {
  it("counts votes while voting", () => {
    expect(progressOf([phone(true, false), phone(false, false)], "voting")).toEqual({
      done: 1,
      total: 2,
      unit: "voted",
    });
  });

  it("counts payments afterwards", () => {
    expect(progressOf([phone(true, true), phone(true, false)], "paying")).toEqual({
      done: 1,
      total: 2,
      unit: "paid",
    });
  });
});

describe("handedOff", () => {
  it("hands off when the last share is in, or once booking", () => {
    expect(handedOff([phone(true, true), phone(true, false)], "paying")).toBe(false);
    expect(handedOff([phone(true, true), phone(true, true)], "paying")).toBe(true);
    expect(handedOff([phone(true, false)], "booking")).toBe(true);
    expect(handedOff([], "paying")).toBe(false);
  });
});
