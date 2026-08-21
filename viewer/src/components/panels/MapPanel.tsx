import { useEffect, useRef } from "react";
import { Map as MapLibreMap, NavigationControl, GeoJSONSource } from "maplibre-gl";
import type { LayerSpecification } from "maplibre-gl";
import type { ContactView } from "../../types";
import { Panel } from "../Panel";

// GeoJSON served from our own origin — no tile server, no API key, works offline.
const WORLD_GEOJSON_URL = "/geo/world-110m.geojson";

const TERRITORIES = {
  northstar: { center: [19, 60.5] as [number, number], color: "#7fd4ff" },
  vesper: { center: [-69, -41.5] as [number, number], color: "#ffb46f" },
} as const;

const MAP_VIEW = {
  center: [-20, 25] as [number, number],
  zoom: 1.35,
};

const KIND_COLOR: Record<ContactView["kind"], string> = {
  exercise: "#ff5c5c",
  movement: "#ffd166",
  readiness_report: "#8affa0",
  planted_suspicion: "#c77dff",
};

function contactFeatures(contacts: ContactView[]): {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    id: string;
    properties: Record<string, unknown>;
    geometry: { type: "Point"; coordinates: [number, number] };
  }[];
} {
  return {
    type: "FeatureCollection",
    features: contacts.map((contact) => ({
      type: "Feature" as const,
      id: contact.id,
      properties: {
        kind: contact.kind,
        label: contact.label,
        turn: contact.turn,
        verified: contact.verified,
        color: KIND_COLOR[contact.kind] ?? "#ffffff",
      },
      geometry: { type: "Point" as const, coordinates: [contact.lon, contact.lat] },
    })),
  };
}

export function MapPanel({ contacts }: { contacts: ContactView[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new MapLibreMap({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          world: {
            type: "geojson",
            data: WORLD_GEOJSON_URL,
          },
        },
        layers: [
          {
            id: "background",
            type: "background",
            paint: { "background-color": "#041008" },
          },
          {
            id: "world-fill",
            type: "fill",
            source: "world",
            filter: ["!=", ["get", "selected"], true],
            paint: { "fill-color": "#12331d", "fill-outline-color": "#2e6b3f" },
          },
          {
            id: "territory-northstar-fill",
            type: "fill",
            source: "world",
            filter: ["==", ["get", "sov"], "northstar"],
            paint: { "fill-color": "#14405c", "fill-opacity": 0.55 },
          },
          {
            id: "territory-vesper-fill",
            type: "fill",
            source: "world",
            filter: ["==", ["get", "sov"], "vesper"],
            paint: { "fill-color": "#5c3a14", "fill-opacity": 0.55 },
          },
          ...(["northstar", "vesper"] as const).flatMap(
            (state): LayerSpecification[] => [
              {
                id: `territory-${state}-outline`,
                type: "line",
                source: "world",
                filter: ["==", ["get", "sov"], state],
                paint: { "line-color": TERRITORIES[state].color, "line-width": 1.5 },
              },
              {
                id: `territory-${state}-label`,
                type: "symbol",
                source: "world",
                filter: ["==", ["get", "sov"], state],
                layout: {
                  "symbol-placement": "point",
                  "text-field": ["get", "name"],
                  "text-font": ["Open Sans Regular"],
                  "text-size": 11,
                  "text-transform": "uppercase",
                },
                paint: {
                  "text-color": TERRITORIES[state].color,
                  "text-halo-color": "#000000",
                  "text-halo-width": 1.5,
                },
              },
            ],
          ),
        ],
      },
      center: MAP_VIEW.center,
      zoom: MAP_VIEW.zoom,
      attributionControl: false,
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      map.addSource("contacts", { type: "geojson", data: contactFeatures([]) });
      map.addLayer({
        id: "contact-ring",
        type: "circle",
        source: "contacts",
        paint: {
          // Confidence ring: bigger + brighter for verified contacts.
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["coalesce", ["get", "verified"], false],
            4,
            9,
          ],
          "circle-color": "#000000",
          "circle-opacity": 0,
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": 1.5,
          "circle-stroke-opacity": 0.85,
        },
      });
      map.addLayer({
        id: "contact-dot",
        type: "circle",
        source: "contacts",
        paint: {
          "circle-radius": 3,
          "circle-color": ["get", "color"],
          "circle-stroke-color": "#000000",
          "circle-stroke-width": 0.8,
        },
      });
      mapRef.current = map;
    });
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (map.isStyleLoaded()) {
      (map.getSource("contacts") as GeoJSONSource | undefined)?.setData(contactFeatures(contacts));
      return;
    }
    map.once("load", () => {
      (map.getSource("contacts") as GeoJSONSource | undefined)?.setData(contactFeatures(contacts));
    });
  }, [contacts]);

  return (
    <Panel title="Theatre Map" accent="green" className="ops-map">
      <div ref={containerRef} className="map-container" />
    </Panel>
  );
}
