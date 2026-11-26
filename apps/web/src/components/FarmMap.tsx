import "leaflet/dist/leaflet.css";
import type { LatLngBoundsExpression, LatLngExpression } from "leaflet";
import { useEffect } from "react";
import { CircleMarker, LayersControl, MapContainer, Polygon, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";

export type MapField = { id: string; name: string; boundary: number[][]; color?: string; label?: string };
export type MapPoint = { id: string; name: string; lat: number; lon: number; label?: string; color?: string; radius?: number };

type Props = {
  center: [number, number];
  zoom?: number;
  points?: MapPoint[];
  fields?: MapField[];
  selectedFieldId?: string | null;
  onFieldClick?: (id: string) => void;
  onPointClick?: (id: string) => void;
  /** When set, clicks on the map are reported (used to place a farm or draw a field). */
  onMapClick?: (lat: number, lon: number) => void;
  drawing?: number[][]; // [lon, lat] vertices drawn so far
  fitTo?: number[][] | null; // [lon, lat] points to fit the view to
  className?: string;
};

/** Leaflet map with a street map and satellite imagery. Coordinates in props use GeoJSON order [lon, lat]. */
export function FarmMap({
  center, zoom = 15, points = [], fields = [], selectedFieldId, onFieldClick, onPointClick, onMapClick, drawing, fitTo, className,
}: Props) {
  const toLatLng = (p: number[]): LatLngExpression => [p[1], p[0]];
  return (
    <div className={className ?? "h-[28rem] overflow-hidden rounded-xl border border-line"}>
      <MapContainer center={center} zoom={zoom} scrollWheelZoom className="h-full w-full" style={{ cursor: onMapClick ? "crosshair" : undefined }}>
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Satellite">
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              attribution="Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community"
              maxZoom={19}
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Street map">
            <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" maxZoom={19} />
          </LayersControl.BaseLayer>
        </LayersControl>
        {fields.map((f) => (
          <Polygon
            key={f.id}
            positions={f.boundary.map(toLatLng)}
            pathOptions={{
              color: f.id === selectedFieldId ? "#ffffff" : (f.color ?? "#facc15"),
              weight: f.id === selectedFieldId ? 3 : 2,
              fillColor: f.color ?? "#facc15",
              fillOpacity: 0.25,
            }}
            eventHandlers={{ click: () => onFieldClick?.(f.id) }}
          >
            <Tooltip sticky>{f.label ?? f.name}</Tooltip>
          </Polygon>
        ))}
        {points.map((p) => (
          <CircleMarker key={p.id} center={[p.lat, p.lon]} radius={p.radius ?? 8} pathOptions={{ color: "#ffffff", weight: 2, fillColor: p.color ?? "#3b4fa8", fillOpacity: 1 }}
            eventHandlers={{ click: () => onPointClick?.(p.id) }}>
            <Tooltip direction="top" offset={[0, -6]}>{p.label ?? p.name}</Tooltip>
          </CircleMarker>
        ))}
        {drawing && drawing.length > 0 && (
          <>
            <Polyline positions={[...drawing, ...(drawing.length > 2 ? [drawing[0]] : [])].map(toLatLng)} pathOptions={{ color: "#ffffff", dashArray: "6 4", weight: 2 }} />
            {drawing.map((p, i) => (
              <CircleMarker key={`${p[0]}-${p[1]}-${i}`} center={toLatLng(p)} radius={4} pathOptions={{ color: "#ffffff", fillColor: "#ffffff", fillOpacity: 1 }} />
            ))}
          </>
        )}
        {onMapClick && <ClickCatcher onClick={onMapClick} />}
        <FitView points={fitTo ?? null} />
      </MapContainer>
    </div>
  );
}

function ClickCatcher({ onClick }: { onClick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onClick(e.latlng.lat, e.latlng.lng) });
  return null;
}

function FitView({ points }: { points: number[][] | null }) {
  const map = useMap();
  const key = points ? JSON.stringify(points) : "";
  // biome-ignore lint/correctness/useExhaustiveDependencies: refit only when the point set changes
  useEffect(() => {
    if (!points || points.length === 0) return;
    if (points.length === 1) {
      map.setView([points[0][1], points[0][0]], Math.max(map.getZoom(), 15));
      return;
    }
    const bounds: LatLngBoundsExpression = points.map((p) => [p[1], p[0]] as [number, number]);
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 17 });
  }, [key]);
  return null;
}

/** Centroid of a [lon, lat] ring, for labels and default map centres. */
export function centroid(ring: number[][]): [number, number] {
  const n = ring.length || 1;
  return [ring.reduce((s, p) => s + p[1], 0) / n, ring.reduce((s, p) => s + p[0], 0) / n];
}
