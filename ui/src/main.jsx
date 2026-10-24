import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";
import "./styles_v2.css";
import "./styles_landing.css";
import "./styles_mobile.css";

// Send the signed-in access key with every same-origin API call so the server
// can apply its role rules (access.py). Cross-origin and protocol-relative
// ("//host") URLs never get the key. EventSource can't set headers; the
// streaming routes it uses are read-only and open to every role.
const _fetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
  try {
    const key = localStorage.getItem("prefectos_api_key");
    const url = input instanceof Request ? input.url : String(input);
    const sameOrigin =
      (url.startsWith("/") && !url.startsWith("//")) || url.startsWith(window.location.origin + "/");
    if (key && sameOrigin) {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      if (!headers.has("X-API-Key")) headers.set("X-API-Key", key);
      init = { ...init, headers };
    }
  } catch {
    /* storage unavailable: send the request as-is */
  }
  return _fetch(input, init);
};

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
