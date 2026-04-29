import type { FastifyPluginAsyncZod } from "fastify-type-provider-zod";
import { z } from "zod";
import { findOptimalDeparture } from "../services/optimizer.js";

const LatLng = z.object({
  lat: z.number().gte(-90).lte(90),
  lng: z.number().gte(-180).lte(180),
});

const Body = z.object({
  origin: LatLng,
  dest: LatLng,
  arriveBy: z.string().datetime(),
  windowMinutes: z.number().int().min(15).max(180).default(90),
  budget: z.number().int().min(1).max(12).default(10),
});

const Candidate = z.object({
  depart: z.string(),
  arrive: z.string(),
  durationSec: z.number().int(),
});

const Response = z.object({
  status: z.enum(["OK", "IMPOSSIBLE"]),
  recommendedDeparture: z.string().optional(),
  expectedArrival: z.string().optional(),
  expectedDurationSec: z.number().int().optional(),
  alternatives: z.array(Candidate),
  earliestArrival: z.string().optional(),
  apiCallsUsed: z.number().int(),
  source: z.literal("live"),
});

export const predictDepartureRoutes: FastifyPluginAsyncZod = async (app) => {
  app.post(
    "/predict-departure",
    {
      schema: {
        body: Body,
        response: { 200: Response },
      },
    },
    async (req) => {
      const userId = (req.headers["x-device-id"] as string) ?? undefined;
      const result = await findOptimalDeparture({
        origin: req.body.origin,
        dest: req.body.dest,
        arriveBy: new Date(req.body.arriveBy),
        windowMinutes: req.body.windowMinutes,
        budget: req.body.budget,
        userId,
      });
      return {
        status: result.status,
        recommendedDeparture: result.recommendedDeparture?.toISOString(),
        expectedArrival: result.expectedArrival?.toISOString(),
        expectedDurationSec: result.expectedDurationSec,
        alternatives: result.alternatives.map((c) => ({
          depart: c.depart.toISOString(),
          arrive: c.arrive.toISOString(),
          durationSec: c.durationSec,
        })),
        earliestArrival: result.earliestArrival?.toISOString(),
        apiCallsUsed: result.apiCallsUsed,
        source: result.source,
      };
    },
  );
};
