import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_BASE_PATH=/evosgpt/ builds the Hub-mounted version (see hub-frontend/scripts/build-evosgpt.mjs);
// the default "/" keeps a standalone build working as before.
const base = process.env.VITE_BASE_PATH || "/";

export default defineConfig({
  base,
  // Build-time constant so a Hub build contains no standalone-backend URLs at all.
  define: { __HUB_MOUNT__: JSON.stringify(base !== "/") },
  plugins: [react()],
});
