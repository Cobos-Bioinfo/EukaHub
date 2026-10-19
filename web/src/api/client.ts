import createClient from "openapi-fetch";

import type { paths } from "./schema";

// Where the API is served: Vite (dev) and nginx (prod) proxy it to the FastAPI service.
export const API_BASE = "/api/v1";

// Fully-typed client over the generated OpenAPI `paths`. Because the types come from
// the API's own schema (which is driven by the METRICS config), request params
// and responses can't drift from the backend.
export const api = createClient<paths>({ baseUrl: API_BASE });
