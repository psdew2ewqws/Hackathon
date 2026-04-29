import type { FastifyPluginAsyncZod } from "fastify-type-provider-zod";
import { z } from "zod";

export const healthRoutes: FastifyPluginAsyncZod = async (app) => {
  app.get(
    "/health",
    {
      schema: {
        response: {
          200: z.object({
            status: z.literal("ok"),
            uptimeSec: z.number(),
            now: z.string(),
          }),
        },
      },
    },
    async () => ({
      status: "ok" as const,
      uptimeSec: Math.round(process.uptime()),
      now: new Date().toISOString(),
    }),
  );
};
