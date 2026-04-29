import Fastify from "fastify";
import cors from "@fastify/cors";
import rateLimit from "@fastify/rate-limit";
import { serializerCompiler, validatorCompiler, ZodTypeProvider } from "fastify-type-provider-zod";

import { config } from "./config.js";
import { healthRoutes } from "./api/health.js";
import { predictDepartureRoutes } from "./api/predict-departure.js";
import { placesRoutes } from "./api/places.js";

export async function buildServer() {
  const app = Fastify({
    logger: { level: config.LOG_LEVEL },
    trustProxy: true,
  }).withTypeProvider<ZodTypeProvider>();

  app.setValidatorCompiler(validatorCompiler);
  app.setSerializerCompiler(serializerCompiler);

  await app.register(cors, { origin: true });
  await app.register(rateLimit, {
    max: 30,
    timeWindow: "1 hour",
    keyGenerator: (req) => (req.headers["x-device-id"] as string) ?? req.ip,
    errorResponseBuilder: () => ({
      error: "rate_limited",
      message: "Too many requests. Try again later.",
    }),
  });

  await app.register(healthRoutes, { prefix: "/v1" });
  await app.register(predictDepartureRoutes, { prefix: "/v1" });
  await app.register(placesRoutes, { prefix: "/v1" });

  return app;
}
