import type { FastifyPluginAsyncZod } from "fastify-type-provider-zod";
import { z } from "zod";
import { config } from "../config.js";

const ConfigResponse = z.object({
  googleMapsBrowserKey: z.string(),
  ammanCenter: z.object({ lat: z.number(), lng: z.number() }),
  defaultZoom: z.number().int(),
});

/**
 * Returns config the mobile app needs at boot. The "browser key" is the
 * Google Maps key that gets embedded in the JS Map API loader URL — it MUST
 * be restricted by HTTP referer in Google Cloud Console before any public
 * deployment. For local dev we just reuse the server key.
 */
export const configRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get(
    "/config",
    {
      schema: { response: { 200: ConfigResponse } },
    },
    async () => ({
      googleMapsBrowserKey: config.GOOGLE_MAPS_API_KEY,
      ammanCenter: { lat: 31.95, lng: 35.92 },
      defaultZoom: 12,
    }),
  );
};
