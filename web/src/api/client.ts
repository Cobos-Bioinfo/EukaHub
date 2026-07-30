import createClient from "openapi-fetch";

import type { paths } from "./schema";

// Fully-typed client over the generated OpenAPI `paths`. In dev, Vite proxies
// /api -> the FastAPI service (see vite.config.ts); in prod the SPA is served
// behind a gateway that routes /api to the API. Because the types come from
// the API's own schema (which is driven by the METRICS config), request params
// and responses can't drift from the backend.
export const api = createClient<paths>({ baseUrl: "/api" });
