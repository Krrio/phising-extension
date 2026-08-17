import { describe, expect, test } from "vitest";
import { getLinkRisk } from "./linkRisk";

describe("getLinkRisk", () => {
  test("keeps a mismatch to reserved .invalid risky", () => {
    expect(
      getLinkRisk("paypal.com", "https://attacker.invalid/paypal-login"),
    ).toMatchObject({
      hostname: "attacker.invalid",
      mismatch: true,
      suspiciousDomain: false,
      risky: true,
    });
  });

  test("does not flag a matching safe destination", () => {
    expect(
      getLinkRisk("paypal.com", "https://www.paypal.com/login"),
    ).toMatchObject({
      hostname: "www.paypal.com",
      mismatch: false,
      suspiciousDomain: false,
      risky: false,
    });
  });

  test("flags a typosquat even when the visible text is not a URL", () => {
    expect(
      getLinkRisk("Zaloguj się", "https://paypa1.com/security"),
    ).toMatchObject({
      hostname: "paypa1.com",
      mismatch: false,
      suspiciousDomain: true,
      risky: true,
    });
  });
});
