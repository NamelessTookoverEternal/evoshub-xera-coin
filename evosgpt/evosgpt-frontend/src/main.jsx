import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { IS_HUB_MOUNT } from "./config";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode><App /></React.StrictMode>
);

// Floating "back to EVOS Hub" tab (served by the Hub at /hub-back.js; same origin only inside the Hub).
if (IS_HUB_MOUNT) {
  const s = document.createElement("script");
  s.src = "/hub-back.js"; s.defer = true;
  document.head.appendChild(s);
}
