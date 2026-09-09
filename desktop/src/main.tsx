import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { OrbApp } from "./app/OrbApp";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Sleipnir desktop root element is missing");
}

const isOrb = new URLSearchParams(window.location.search).get("surface") === "orb";
if (isOrb) document.documentElement.dataset.surface = "orb";

createRoot(root).render(
  <StrictMode>
    {isOrb ? <OrbApp /> : <App />}
  </StrictMode>,
);
