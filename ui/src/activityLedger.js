/**
 * activityLedger — records what the signed-in licensee does.
 *
 * The server records the activities it performs itself (a chat answer, a
 * document job starting). This covers the ones only the browser sees: the
 * sign-in, and a job reaching its end in the client's own event stream.
 *
 * Attribution is by access key: the key is sent so the server can derive the
 * ledger's file name from its hash, and is never stored in the ledger itself.
 * Without a key nothing is recorded — an unattributed activity would be worse
 * than no activity at all.
 */

const LS = {
  key: "prefectos_api_key",
  id: "prefectos_user_id",
  name: "prefectos_user_name",
  role: "prefectos_user_role",
  bank: "prefectos_bank_name",
};

export function actor() {
  try {
    return {
      api_key: localStorage.getItem(LS.key) || "",
      user_id: localStorage.getItem(LS.id) || "",
      user_name: localStorage.getItem(LS.name) || "",
      role: localStorage.getItem(LS.role) || "",
      institution: localStorage.getItem(LS.bank) || "",
    };
  } catch {
    return { api_key: "" };
  }
}

export function hasKey() {
  return !!actor().api_key;
}

/** Append one activity. Fire-and-forget: recording must never block the UI. */
export function record(kind, summary, details = {}) {
  const who = actor();
  if (!who.api_key) return Promise.resolve(null);
  return fetch("/ledger/activity", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: who, kind, summary, details }),
  })
    .then((r) => r.json())
    .catch(() => null);
}

export async function load(kind = "") {
  const who = actor();
  if (!who.api_key) return { days: [], totals: { records: 0 }, owner: {} };
  const q = new URLSearchParams({ api_key: who.api_key });
  if (kind) q.set("kind", kind);
  const res = await fetch(`/ledger/activity?${q.toString()}`);
  return res.json();
}

export function exportUrl() {
  return `/ledger/activity/export?api_key=${encodeURIComponent(actor().api_key)}`;
}
