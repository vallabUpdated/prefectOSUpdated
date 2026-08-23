import { useCallback, useState } from "react";

/**
 * Institution settings (bank name, USD→INR rate, policy pack) as used by the
 * processing suites.
 *
 * They live in localStorage rather than in React state so every window shares
 * one set of values: change them on the landing page and the processing window
 * shows the same bank and rate, and vice versa.
 */
const LS_BANK = "prefectos_bank_name";
const LS_FX = "prefectos_usd_inr";
const LS_POLICY = "prefectos_policy_pack";
const DEFAULT_FX = 88;

function read() {
  try {
    const rate = Number.parseFloat(localStorage.getItem(LS_FX));
    return {
      bankName: localStorage.getItem(LS_BANK) || "",
      fxRate: Number.isFinite(rate) && rate > 0 ? rate : DEFAULT_FX,
      policyPath: localStorage.getItem(LS_POLICY) || "",
    };
  } catch {
    return { bankName: "", fxRate: DEFAULT_FX, policyPath: "" };
  }
}

export default function useInstitutionSettings() {
  const [settings, setSettings] = useState(read);

  const save = useCallback(({ bankName, fxRate, policyPath }) => {
    const next = {
      bankName: bankName || "",
      fxRate: Number.isFinite(fxRate) && fxRate > 0 ? fxRate : DEFAULT_FX,
      policyPath: policyPath || "",
    };
    setSettings(next);
    try {
      localStorage.setItem(LS_BANK, next.bankName);
      localStorage.setItem(LS_FX, String(next.fxRate));
      localStorage.setItem(LS_POLICY, next.policyPath);
    } catch {
      /* storage disabled */
    }
  }, []);

  return { ...settings, save };
}

export { DEFAULT_FX, LS_BANK, LS_FX, LS_POLICY };
