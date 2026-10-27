import { unified } from "@astrojs/markdown-remark";
import { defineConfig } from "astro/config";
import remarkGfm from "remark-gfm";

export default defineConfig({
  site: "http://localhost:4321",
  compressHTML: true,
  devToolbar: { enabled: false },
  markdown: {
    processor: unified({ remarkPlugins: [remarkGfm] }),
    shikiConfig: {
      theme: "github-light",
    },
  },
});
