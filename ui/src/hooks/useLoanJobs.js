import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import * as store from "../loanJobStore.js";

/**
 * useLoanJobs — a view onto the processing boxes for one domain.
 *
 * All the state lives in loanJobStore at module scope, not here: a run started
 * in a box keeps going — and keeps updating — while this component is
 * unmounted, so moving between Loan, Account and the orchestrator never
 * interrupts or loses a job. This hook only subscribes, reads, and forwards
 * actions.
 */
export default function useLoanJobs(bankName = "", domain = "loan", policyPath = "") {
  const subscribe = useCallback((fn) => store.subscribe(domain, fn), [domain]);
  const snapshot = useSyncExternalStore(
    subscribe,
    useCallback(() => store.getSnapshot(domain), [domain])
  );

  // The institution named in every report, and the credit-policy pack, are
  // both owned by the landing page's settings.
  useEffect(() => {
    store.setBankName(bankName);
  }, [bankName]);

  useEffect(() => {
    store.setPolicyPath(policyPath);
  }, [policyPath]);

  useEffect(() => {
    store.ensureConfig(domain);
  }, [domain]);

  const actions = useMemo(
    () => ({
      setField: (loanType, key, value) => store.setField(domain, loanType, key, value),
      resetPrompt: (loanType) => store.resetPrompt(domain, loanType),
      start: (loanType) => store.start(domain, loanType),
      cancel: (loanType) => store.cancel(domain, loanType),
      scanInput: (loanType, path) => store.scanInput(domain, loanType, path),
    }),
    [domain]
  );

  const { boxes, config, configError } = snapshot;
  const boxList = (config.loanTypes || []).map((t) => boxes[t.id]).filter(Boolean);
  const totals = boxList.reduce(
    (acc, b) => ({
      tokensIn: acc.tokensIn + b.tokensIn,
      tokensOut: acc.tokensOut + b.tokensOut,
      costUsd: acc.costUsd + (b.costUsd || 0),
      active: acc.active + (store.isActive(b.status) ? 1 : 0),
    }),
    { tokensIn: 0, tokensOut: 0, costUsd: 0, active: 0 }
  );

  return { boxes: boxList, config, configError, totals, actions };
}

/**
 * useActiveCount — how many boxes in a domain are running right now.
 * Lets a screen show activity in the section the operator isn't looking at.
 */
export function useActiveCount(domain) {
  const subscribe = useCallback((fn) => store.subscribe(domain, fn), [domain]);
  const snapshot = useSyncExternalStore(
    subscribe,
    useCallback(() => store.getSnapshot(domain), [domain])
  );
  return Object.values(snapshot.boxes).filter((b) => store.isActive(b.status)).length;
}
