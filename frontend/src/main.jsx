import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { wakeServer } from "./api/serverWake.js";
import "./index.css";

// Start waking the API before React has rendered anything. On a cold instance
// this is the difference between the wait starting when the page opens and it
// starting when the user presses "Sign in".
wakeServer();

// After a deploy, the lazily loaded chunks from the previous build are gone. A
// tab left open across the deploy then fails the next time it opens a page it
// hasn't visited yet. Reloading picks up the new build. The timestamp guard
// stops a chunk that is genuinely missing from reloading the page in a loop.
const RELOAD_KEY = "if_chunk_reload_at";
window.addEventListener("vite:preloadError", (event) => {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY)) || 0;
    if (Date.now() - last < 60_000) return;
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch {
    // Without storage there is no loop guard, so let the error surface.
    return;
  }
  event.preventDefault();
  window.location.reload();
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
