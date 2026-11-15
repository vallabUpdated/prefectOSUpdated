// Where "back to the website" points (sign-in gate, its "← prefectos.ai" link, log out).
//
//   VITE_SITE_URL set at build time  -> that URL (on-prem installs)
//   running on localhost             -> /launch.html, the copy of the website this
//                                       server serves from landing/ — so a local run
//                                       shows YOUR working copy (language switch
//                                       included), not whatever is published
//   anywhere else                    -> the public website
const local = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);

export const SITE_URL =
  import.meta.env?.VITE_SITE_URL ||
  (local ? "/launch.html" : "https://www.prefectos.ai/launch.html");
