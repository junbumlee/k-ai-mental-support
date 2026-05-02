import { inject } from "/static/vendor/vercel-analytics.mjs";

const hostname = window.location.hostname;
const isLocalhost =
  hostname === "localhost" ||
  hostname === "127.0.0.1" ||
  hostname === "[::1]";

inject({
  mode: isLocalhost ? "development" : "production",
});
