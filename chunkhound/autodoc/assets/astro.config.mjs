import { existsSync, readFileSync } from "node:fs";
import { unified } from "@astrojs/markdown-remark";
import { defineConfig } from "astro/config";
import remarkGfm from "remark-gfm";

const architecturePath = new URL("./src/data/architecture.json", import.meta.url);
const architecture = existsSync(architecturePath) ? JSON.parse(readFileSync(architecturePath, "utf8")) : null;
const hasMap =
  architecture?.schemaVersion === 1 &&
  architecture.enabled === true &&
  existsSync(new URL("./likec4/", import.meta.url));
const integrations = [];
const plugins = [];
if (hasMap) {
  const [{ default: react }, { LikeC4VitePlugin: likeC4VitePlugin }] = await Promise.all([
    import("@astrojs/react"),
    import("likec4/vite-plugin"),
  ]);
  integrations.push(react());
  plugins.push(
    likeC4VitePlugin({
      workspace: "likec4",
      throwIfInvalid: true,
      ai: "disabled",
    }),
  );
}

export default defineConfig({
  site: "http://localhost:4321",
  compressHTML: true,
  devToolbar: { enabled: false },
  integrations,
  vite: {
    resolve: { dedupe: ["react", "react-dom"] },
    plugins,
  },
  markdown: {
    processor: unified({ remarkPlugins: [remarkGfm] }),
    shikiConfig: {
      theme: "github-light",
    },
  },
});
