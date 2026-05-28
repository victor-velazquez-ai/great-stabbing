// @ts-check
import { defineConfig } from "astro/config";
import tailwind from "@astrojs/tailwind";

export default defineConfig({
  site: "https://great-stabbing.pages.dev",
  integrations: [tailwind()],
  vite: {
    optimizeDeps: {
      // maplibre-gl and pmtiles benefit from explicit pre-bundling
      include: ["maplibre-gl", "pmtiles", "@observablehq/plot"],
    },
  },
});
