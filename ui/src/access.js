// Which controls to show for a role. This only mirrors the server's rules
// (access.py) so a restricted role isn't offered buttons that would be refused;
// it is NOT a security boundary. The server decides who may actually do what.
const RESTRICTED = new Set(["user", "anonymous"]);

export const isRestricted = (role) =>
  RESTRICTED.has(String(role || "").trim().toLowerCase());

export const currentRole = () => {
  try {
    return localStorage.getItem("prefectos_user_role") || "";
  } catch {
    return "";
  }
};
