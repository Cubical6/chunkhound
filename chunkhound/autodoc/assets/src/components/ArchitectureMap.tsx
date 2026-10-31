import { ReactLikeC4 } from "likec4:react";
import { useEffect, useState } from "react";
import type { ReactElement } from "react";

/** Version-1 publication boundary produced by architecture/site_data.py. */
export interface ArchitectureData {
  schemaVersion: 1;
  enabled: boolean;
  contextView: "index";
  views: Record<string, { title: string; level: string; elementId: string | null }>;
  elements: Record<
    string,
    {
      name: string;
      kind: string;
      description: string;
      status: string | null;
      focusView: string;
      defaultView: string | null;
    }
  >;
  topics: Record<string, { view: string | null; directElementIds: string[] }>;
}

/** Full native map with one URL-backed view selection, including browser history. */
// oxlint-disable-next-line import/no-default-export -- Astro imports this optional island directly.
export default function ArchitectureMap({ data }: { data: ArchitectureData }): ReactElement {
  const [requestedView, setRequestedView] = useState(
    () => new URL(window.location.href).searchParams.get("view") ?? data.contextView,
  );

  useEffect(() => {
    const onPopState = () =>
      setRequestedView(new URL(window.location.href).searchParams.get("view") ?? data.contextView);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [data.contextView]);

  if (!data.enabled || !Object.hasOwn(data.views, data.contextView)) {
    return <p>Architecture map is unavailable.</p>;
  }

  const knownView = Object.hasOwn(data.views, requestedView);
  const viewId = knownView ? requestedView : data.contextView;
  const navigate = (nextView: string) => {
    const url = new URL(window.location.href);
    if (url.searchParams.get("view") !== nextView) {
      url.searchParams.set("view", nextView);
      window.history.pushState(null, "", url);
    }
    setRequestedView(nextView);
  };

  return (
    <section className="architecture-map" aria-label="Architecture map">
      {!knownView && (
        <p role="status" className="architecture-map-warning">
          Unknown architecture view “{requestedView}”. Showing the system context instead.
        </p>
      )}
      <div className="architecture-map-toolbar">
        <label>
          View{" "}
          <select value={viewId} onChange={(event) => navigate(event.target.value)}>
            {Object.entries(data.views).map(([id, view]) => (
              <option key={id} value={id}>
                {view.title} ({view.level})
              </option>
            ))}
          </select>
        </label>
        <a href={`/architecture/?view=${encodeURIComponent(viewId)}`}>Link to this view</a>
      </div>
      <p className="architecture-map-help">
        Pan and zoom to explore. Open element details for evidence, topics and a Focus-view.
      </p>
      <ReactLikeC4
        viewId={viewId}
        injectFontCss={false}
        pannable
        zoomable
        controls
        enableElementDetails
        enableRelationshipDetails
        enableRelationshipBrowser
        enableNotations
        showNavigationButtons
        onNavigateTo={navigate}
        style={{ width: "100%", height: "70vh", minHeight: "32rem" }}
      />
      <p className="architecture-map-legend">
        C4: software system → container → component; people and external systems stay outside. Muted: gedocumenteerd.
        Solid: aangetroffen; dotted: gedocumenteerd. Dashed aggregate: inspect each relationship’s own status and
        sources.
      </p>
    </section>
  );
}
