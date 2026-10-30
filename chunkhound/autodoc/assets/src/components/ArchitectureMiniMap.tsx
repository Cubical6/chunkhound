import { LikeC4View, useLikeC4View } from "likec4:react";
import type { ReactElement } from "react";
import type { ArchitectureData } from "./ArchitectureMap";

/** Embedded native view; its popup browser keeps the preview independently interactive. */
// oxlint-disable-next-line import/no-default-export -- Astro imports this optional island directly.
export default function ArchitectureMiniMap({ viewId }: { viewId: string }): ReactElement {
  const view = useLikeC4View(viewId);
  const selectedView: keyof ArchitectureData["views"] = view ? viewId : "index";

  return (
    <section className="architecture-mini-map" aria-label="Architecture preview">
      {!view && <p role="status">Unknown architecture view. Showing the system context instead.</p>}
      <LikeC4View
        viewId={selectedView}
        injectFontCss={false}
        pannable
        zoomable
        controls
        enableElementDetails
        enableRelationshipDetails
        enableNotations
        browser
        style={{ width: "100%", minHeight: "20rem" }}
      />
      <p>
        <a href={`/architecture/?view=${encodeURIComponent(selectedView)}`}>Open full architecture map</a>
      </p>
    </section>
  );
}
