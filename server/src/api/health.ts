import type { FastifyInstance } from "fastify";
import { z } from "zod";

export async function healthRoutes(app: FastifyInstance) {
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
}
