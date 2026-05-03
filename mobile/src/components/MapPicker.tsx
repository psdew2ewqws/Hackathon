import { useCallback, useEffect, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { fetchConfig, reverseGeocode, type LatLng, type PlaceDetails } from "../services/api";

interface Props {
  origin: PlaceDetails | null;
  dest: PlaceDetails | null;
  onOriginChange: (p: PlaceDetails | null) => void;
  onDestChange: (p: PlaceDetails | null) => void;
}

type ActivePin = "origin" | "dest";

const formatCoord = (p: LatLng) => `${p.lat.toFixed(4)}, ${p.lng.toFixed(4)}`;

const customPlace = (label: string, location: LatLng): PlaceDetails => ({
  placeId: `custom:${location.lat.toFixed(5)},${location.lng.toFixed(5)}`,
  name: label,
  formattedAddress: formatCoord(location),
  location,
});

export function MapPicker({ origin, dest, onOriginChange, onDestChange }: Props) {
  const { data: config, isLoading, error } = useQuery({
    queryKey: ["app-config"],
    queryFn: fetchConfig,
    staleTime: 60 * 60_000, // 1h
  });

  if (Platform.OS !== "web") {
    return (
      <View style={styles.fallback}>
        <Text style={styles.fallbackText}>
          Interactive map is web-only for now. Use search above.
        </Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.fallback}>
        <Text style={styles.errorText}>Map config failed to load: {(error as Error).message}</Text>
      </View>
    );
  }

  if (isLoading || !config) {
    return (
      <View style={styles.fallback}>
        <Text style={styles.fallbackText}>Loading map…</Text>
      </View>
    );
  }

  return (
    <WebMap
      apiKey={config.googleMapsBrowserKey}
      center={config.ammanCenter}
      zoom={config.defaultZoom}
      origin={origin}
      dest={dest}
      onOriginChange={onOriginChange}
      onDestChange={onDestChange}
    />
  );
}

interface WebMapProps {
  apiKey: string;
  center: LatLng;
  zoom: number;
  origin: PlaceDetails | null;
  dest: PlaceDetails | null;
  onOriginChange: (p: PlaceDetails | null) => void;
  onDestChange: (p: PlaceDetails | null) => void;
}

// Lazily required so RN bundler on native doesn't try to resolve `@vis.gl/...`
function WebMap(props: WebMapProps) {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { APIProvider, Map, Marker, useMap } = require("@vis.gl/react-google-maps") as typeof import("@vis.gl/react-google-maps");

  const [activePin, setActivePin] = useState<ActivePin>(props.origin ? "dest" : "origin");

  // Drop a pin instantly, then upgrade its label once reverse-geocoding resolves.
  // The setter callback re-checks identity so a second click before resolution
  // doesn't overwrite the new placeholder with the old name.
  const setPlace = useCallback(
    (pin: ActivePin, place: PlaceDetails) => {
      if (pin === "origin") props.onOriginChange(place);
      else props.onDestChange(place);
    },
    [props],
  );

  const resolveLabel = useCallback(
    async (pin: ActivePin, point: LatLng, fallback: string) => {
      const placeholder = customPlace(fallback, point);
      setPlace(pin, placeholder);
      try {
        const resolved = await reverseGeocode(point);
        setPlace(pin, resolved);
      } catch {
        // keep placeholder coordinates if reverse-geocode fails
      }
    },
    [setPlace],
  );

  const handleClick = useCallback(
    (e: { detail: { latLng: { lat: number; lng: number } | null } }) => {
      if (!e.detail.latLng) return;
      const point: LatLng = { lat: e.detail.latLng.lat, lng: e.detail.latLng.lng };
      const fallback = activePin === "origin" ? "Origin" : "Destination";
      void resolveLabel(activePin, point, fallback);
      if (activePin === "origin") setActivePin("dest");
    },
    [activePin, resolveLabel],
  );

  const handleUseLocation = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const point: LatLng = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        void resolveLabel("origin", point, "Your location");
        setActivePin("dest");
      },
      (err) => {
        console.warn("geolocation failed", err);
      },
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  }, [resolveLabel]);

  return (
    <View style={styles.wrap}>
      <APIProvider apiKey={props.apiKey}>
        <View style={styles.mapBox}>
          <Map
            defaultCenter={props.center}
            defaultZoom={props.zoom}
            disableDefaultUI={false}
            clickableIcons={false}
            onClick={handleClick}
            style={{ width: "100%", height: "100%" }}
          >
            {props.origin && (
              <Marker
                position={props.origin.location}
                draggable
                icon="https://maps.google.com/mapfiles/ms/icons/blue-dot.png"
                onDragEnd={(e: { latLng?: { lat: () => number; lng: () => number } | null }) => {
                  if (!e.latLng) return;
                  void resolveLabel("origin", { lat: e.latLng.lat(), lng: e.latLng.lng() }, "Origin");
                }}
              />
            )}
            {props.dest && (
              <Marker
                position={props.dest.location}
                draggable
                icon="https://maps.google.com/mapfiles/ms/icons/red-dot.png"
                onDragEnd={(e: { latLng?: { lat: () => number; lng: () => number } | null }) => {
                  if (!e.latLng) return;
                  void resolveLabel("dest", { lat: e.latLng.lat(), lng: e.latLng.lng() }, "Destination");
                }}
              />
            )}
            <AutoFit origin={props.origin?.location ?? null} dest={props.dest?.location ?? null} />
          </Map>
        </View>
      </APIProvider>

      <View style={styles.controls}>
        <Pressable
          style={[styles.toggle, activePin === "origin" && styles.toggleActive]}
          onPress={() => setActivePin("origin")}
        >
          <View style={[styles.dot, { backgroundColor: "#3B82F6" }]} />
          <Text style={styles.toggleText}>Set From</Text>
        </Pressable>
        <Pressable
          style={[styles.toggle, activePin === "dest" && styles.toggleActive]}
          onPress={() => setActivePin("dest")}
        >
          <View style={[styles.dot, { backgroundColor: "#EF4444" }]} />
          <Text style={styles.toggleText}>Set To</Text>
        </Pressable>
        <Pressable style={styles.locButton} onPress={handleUseLocation}>
          <Text style={styles.locButtonText}>📍 Use my location</Text>
        </Pressable>
      </View>

      <Text style={styles.hint}>
        {activePin === "origin"
          ? "Click anywhere on the map to drop your starting point"
          : "Now click the map to drop your destination"}
      </Text>

      {(props.origin || props.dest) && (
        <View style={styles.pinSummary}>
          {props.origin && <PinBadge color="#3B82F6" label="From" name={props.origin.name} />}
          {props.dest && <PinBadge color="#EF4444" label="To" name={props.dest.name} />}
        </View>
      )}
    </View>
  );

  function AutoFit({ origin, dest }: { origin: LatLng | null; dest: LatLng | null }) {
    const map = useMap();
    useEffect(() => {
      if (!map) return;
      if (origin && dest) {
        const padDeg = 0.005;
        map.fitBounds(
          {
            north: Math.max(origin.lat, dest.lat) + padDeg,
            south: Math.min(origin.lat, dest.lat) - padDeg,
            east: Math.max(origin.lng, dest.lng) + padDeg,
            west: Math.min(origin.lng, dest.lng) - padDeg,
          },
          64,
        );
      } else if (origin) {
        map.panTo(origin);
        map.setZoom(14);
      } else if (dest) {
        map.panTo(dest);
        map.setZoom(14);
      }
    }, [map, origin, dest]);
    return null;
  }
}

function PinBadge({ color, label, name }: { color: string; label: string; name: string }) {
  return (
    <View style={styles.pinBadge}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={styles.pinLabel}>{label}</Text>
      <Text style={styles.pinName} numberOfLines={1}>
        {name}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 12, marginBottom: 4 },
  pinSummary: { marginTop: 8, gap: 6 },
  pinBadge: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#1A1F29",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    gap: 8,
  },
  pinLabel: { color: "#8B95A8", fontSize: 12, fontWeight: "600", width: 28 },
  pinName: { color: "#fff", fontSize: 13, flex: 1 },
  mapBox: {
    width: "100%",
    height: 360,
    borderRadius: 12,
    overflow: "hidden",
    backgroundColor: "#1A1F29",
  },
  fallback: {
    height: 120,
    backgroundColor: "#1A1F29",
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    marginVertical: 12,
  },
  fallbackText: { color: "#8B95A8", fontSize: 13 },
  errorText: { color: "#F87171", fontSize: 13, paddingHorizontal: 16, textAlign: "center" },
  controls: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 8,
  },
  toggle: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#1A1F29",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#1A1F29",
  },
  toggleActive: { borderColor: "#3B82F6" },
  toggleText: { color: "#fff", fontSize: 13, marginLeft: 6 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  locButton: {
    backgroundColor: "#1A1F29",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    marginLeft: "auto",
  },
  locButtonText: { color: "#A8B3C5", fontSize: 13 },
  hint: { color: "#5C6373", fontSize: 12, marginTop: 6, fontStyle: "italic" },
});
