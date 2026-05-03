import type { FastifyPluginAsyncZod } from "fastify-type-provider-zod";
import { z } from "zod";
import { config } from "../config.js";

// Bias autocomplete to Amman so "Sweifieh" returns the Amman one, not a global match.
const AMMAN_BIAS_CENTER = { latitude: 31.95, longitude: 35.92 };
const AMMAN_BIAS_RADIUS_M = 50_000;

const Prediction = z.object({
  placeId: z.string(),
  text: z.string(),
  mainText: z.string(),
  secondaryText: z.string().optional(),
});

const AutocompleteResponse = z.object({
  predictions: z.array(Prediction),
});

const DetailsResponse = z.object({
  placeId: z.string(),
  name: z.string(),
  formattedAddress: z.string().optional(),
  location: z.object({ lat: z.number(), lng: z.number() }),
});

export const placesRoutes: FastifyPluginAsyncZod = async (app) => {
  // Autocomplete: text query → list of places matching, biased to Amman
  app.get(
    "/places/autocomplete",
    {
      schema: {
        querystring: z.object({
          q: z.string().min(1).max(200),
          sessionToken: z.string().min(8).max(64).optional(),
        }),
        response: { 200: AutocompleteResponse },
      },
    },
    async (req) => {
      const body = {
        input: req.query.q,
        locationBias: {
          circle: { center: AMMAN_BIAS_CENTER, radius: AMMAN_BIAS_RADIUS_M },
        },
        ...(req.query.sessionToken ? { sessionToken: req.query.sessionToken } : {}),
      };

      const r = await fetch("https://places.googleapis.com/v1/places:autocomplete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const text = await r.text();
        app.log.warn({ status: r.status, text }, "places autocomplete failed");
        const e = new Error(`places autocomplete ${r.status}: ${text}`);
        (e as Error & { statusCode?: number }).statusCode = 502;
        throw e;
      }

      const json = (await r.json()) as {
        suggestions?: Array<{
          placePrediction?: {
            placeId: string;
            text: { text: string };
            structuredFormat?: {
              mainText?: { text: string };
              secondaryText?: { text: string };
            };
          };
        }>;
      };

      const predictions = (json.suggestions ?? [])
        .map((s) => s.placePrediction)
        .filter((p): p is NonNullable<typeof p> => Boolean(p))
        .map((p) => ({
          placeId: p.placeId,
          text: p.text.text,
          mainText: p.structuredFormat?.mainText?.text ?? p.text.text,
          secondaryText: p.structuredFormat?.secondaryText?.text,
        }));

      return { predictions };
    },
  );

  // Place Details: placeId → coordinates + canonical name
  app.get(
    "/places/details",
    {
      schema: {
        querystring: z.object({
          placeId: z.string().min(1).max(200),
          sessionToken: z.string().min(8).max(64).optional(),
        }),
        response: { 200: DetailsResponse },
      },
    },
    async (req) => {
      const url = new URL(`https://places.googleapis.com/v1/places/${encodeURIComponent(req.query.placeId)}`);
      if (req.query.sessionToken) url.searchParams.set("sessionToken", req.query.sessionToken);

      const r = await fetch(url, {
        headers: {
          "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
          "X-Goog-FieldMask": "id,displayName,formattedAddress,location",
        },
      });
      if (!r.ok) {
        const text = await r.text();
        const e = new Error(`place details ${r.status}: ${text}`);
        (e as Error & { statusCode?: number }).statusCode = 502;
        throw e;
      }

      const json = (await r.json()) as {
        id: string;
        displayName?: { text: string };
        formattedAddress?: string;
        location?: { latitude: number; longitude: number };
      };
      if (!json.location) {
        const e = new Error("place has no location");
        (e as Error & { statusCode?: number }).statusCode = 404;
        throw e;
      }

      return {
        placeId: json.id,
        name: json.displayName?.text ?? json.formattedAddress ?? "(unnamed place)",
        formattedAddress: json.formattedAddress,
        location: { lat: json.location.latitude, lng: json.location.longitude },
      };
    },
  );

  // Reverse geocoding: lat/lng → human-readable place name. Used when the user
  // drops a pin on the map so we display "Sweifieh" instead of "Origin".
  app.get(
    "/places/reverse",
    {
      schema: {
        querystring: z.object({
          lat: z.coerce.number().min(-90).max(90),
          lng: z.coerce.number().min(-180).max(180),
          language: z.string().min(2).max(5).default("en"),
        }),
        response: { 200: DetailsResponse },
      },
    },
    async (req) => {
      const url = new URL("https://maps.googleapis.com/maps/api/geocode/json");
      url.searchParams.set("latlng", `${req.query.lat},${req.query.lng}`);
      url.searchParams.set("key", config.GOOGLE_MAPS_API_KEY);
      url.searchParams.set("language", req.query.language);

      const r = await fetch(url);
      if (!r.ok) {
        const text = await r.text();
        const e = new Error(`reverse geocode ${r.status}: ${text}`);
        (e as Error & { statusCode?: number }).statusCode = 502;
        throw e;
      }

      const json = (await r.json()) as {
        status: string;
        results?: Array<{
          place_id: string;
          formatted_address: string;
          address_components?: Array<{
            long_name: string;
            short_name: string;
            types: string[];
          }>;
        }>;
      };

      // Fall back to a pretty coordinate if geocoding returned nothing
      // (e.g. middle of the desert) so the UI never shows a blank label.
      const coordName = `${req.query.lat.toFixed(4)}, ${req.query.lng.toFixed(4)}`;
      const best = json.status === "OK" ? json.results?.[0] : undefined;
      if (!best) {
        return {
          placeId: `latlng:${req.query.lat.toFixed(5)},${req.query.lng.toFixed(5)}`,
          name: coordName,
          location: { lat: req.query.lat, lng: req.query.lng },
        };
      }

      const components = best.address_components ?? [];
      const findType = (t: string) => components.find((c) => c.types.includes(t))?.long_name;
      // Prefer the most local recognizable label. "sublocality" maps to
      // neighborhoods like Sweifieh / Abdoun in Amman.
      const name =
        findType("sublocality") ??
        findType("neighborhood") ??
        findType("locality") ??
        findType("administrative_area_level_2") ??
        best.formatted_address.split(",")[0] ??
        coordName;

      return {
        placeId: best.place_id,
        name,
        formattedAddress: best.formatted_address,
        location: { lat: req.query.lat, lng: req.query.lng },
      };
    },
  );

  // Static map: proxies Google Maps Static API so the API key stays server-side.
  // We just stream the PNG bytes back.
  app.get(
    "/static-map",
    {
      schema: {
        querystring: z.object({
          origin: z.string().regex(/^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/),
          dest: z.string().regex(/^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/),
          width: z.coerce.number().int().min(100).max(1280).default(640),
          height: z.coerce.number().int().min(100).max(1280).default(320),
          scale: z.coerce.number().int().min(1).max(2).default(2),
        }),
      },
    },
    async (req, reply) => {
      const url = new URL("https://maps.googleapis.com/maps/api/staticmap");
      url.searchParams.set("size", `${req.query.width}x${req.query.height}`);
      url.searchParams.set("scale", String(req.query.scale));
      url.searchParams.set("maptype", "roadmap");
      url.searchParams.append("markers", `color:blue|label:A|${req.query.origin}`);
      url.searchParams.append("markers", `color:red|label:B|${req.query.dest}`);
      url.searchParams.set(
        "path",
        `color:0x3B82F6cc|weight:4|${req.query.origin}|${req.query.dest}`,
      );
      url.searchParams.set("key", config.GOOGLE_MAPS_API_KEY);

      const r = await fetch(url);
      if (!r.ok) {
        const text = await r.text();
        const e = new Error(`static map ${r.status}: ${text}`);
        (e as Error & { statusCode?: number }).statusCode = 502;
        throw e;
      }

      const buf = Buffer.from(await r.arrayBuffer());
      reply.header("content-type", r.headers.get("content-type") ?? "image/png");
      reply.header("cache-control", "public, max-age=300"); // 5 min — same as live cache TTL
      return reply.send(buf);
    },
  );
};
