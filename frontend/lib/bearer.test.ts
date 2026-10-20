import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearBearer, readBearer, writeBearer } from "./bearer";

describe("bearer storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("returns null when nothing stored", () => {
    expect(readBearer()).toBeNull();
  });

  it("round-trips a value through writeBearer/readBearer", () => {
    writeBearer({ token: "abc.def.ghi", userId: "u-1" });
    expect(readBearer()).toEqual({ token: "abc.def.ghi", userId: "u-1" });
  });

  it("clearBearer removes the entry", () => {
    writeBearer({ token: "abc", userId: "u-1" });
    clearBearer();
    expect(readBearer()).toBeNull();
  });

  it("tolerates malformed JSON", () => {
    window.localStorage.setItem("v5.bearer", "{not-json");
    expect(readBearer()).toBeNull();
  });

  it("rejects entries with the wrong shape", () => {
    window.localStorage.setItem("v5.bearer", JSON.stringify({ token: 123 }));
    expect(readBearer()).toBeNull();
    window.localStorage.setItem(
      "v5.bearer",
      JSON.stringify({ token: "ok", userId: 4 }),
    );
    expect(readBearer()).toBeNull();
  });
});