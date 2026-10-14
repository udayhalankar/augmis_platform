/** AUGMIS suggestions, not a claim of variables understood by every hosted application.
 * The uploaded application must explicitly read each variable to have any effect.
 */
export type RuntimeVariableTemplate = {
  name: string;
  category: "Application" | "Logging" | "Features" | "Web & API" | "Worker" | "Caching" | "Localization" | "Observability";
  description: string;
  defaultValue: string;
  values?: readonly string[];
};

export const RUNTIME_VARIABLE_CATALOG: readonly RuntimeVariableTemplate[] = [
  { name: "APP_ENV", category: "Application", description: "Application environment label", defaultValue: "development", values: ["development", "staging", "production"] },
  { name: "APP_MODE", category: "Application", description: "Application operating mode", defaultValue: "standard", values: ["standard", "maintenance", "readonly"] },
  { name: "APP_REGION", category: "Application", description: "Logical region identifier", defaultValue: "sa-central-1" },
  { name: "APP_DISPLAY_NAME", category: "Application", description: "Optional user-facing display name", defaultValue: "My Application" },
  { name: "APP_DEBUG", category: "Application", description: "Enable debugging only when supported by the app", defaultValue: "false", values: ["false", "true"] },
  { name: "LOG_LEVEL", category: "Logging", description: "Requested application log detail", defaultValue: "INFO", values: ["DEBUG", "INFO", "WARNING", "ERROR"] },
  { name: "LOG_FORMAT", category: "Logging", description: "Preferred application log format", defaultValue: "text", values: ["text", "json"] },
  { name: "LOG_JSON", category: "Logging", description: "Request structured log lines", defaultValue: "false", values: ["false", "true"] },
  { name: "FEATURE_ENABLED", category: "Features", description: "Generic demonstration feature switch", defaultValue: "false", values: ["false", "true"] },
  { name: "FEATURE_FLAGS", category: "Features", description: "Comma-separated, application-defined feature names", defaultValue: "" },
  { name: "READ_ONLY_MODE", category: "Features", description: "Request read-only application mode", defaultValue: "false", values: ["false", "true"] },
  { name: "REQUEST_TIMEOUT_SECONDS", category: "Web & API", description: "Application outbound request timeout", defaultValue: "30" },
  { name: "RETRY_COUNT", category: "Web & API", description: "Number of retry attempts", defaultValue: "3" },
  { name: "RETRY_BACKOFF_MS", category: "Web & API", description: "Milliseconds between retry attempts", defaultValue: "500" },
  { name: "PUBLIC_BASE_URL", category: "Web & API", description: "Public application base URL, if the app uses one", defaultValue: "" },
  { name: "WORKER_CONCURRENCY", category: "Worker", description: "Requested application worker concurrency", defaultValue: "2" },
  { name: "BATCH_SIZE", category: "Worker", description: "Generic batch-processing size", defaultValue: "100" },
  { name: "SCHEDULER_ENABLED", category: "Worker", description: "Enable an application-owned scheduler", defaultValue: "false", values: ["false", "true"] },
  { name: "CACHE_ENABLED", category: "Caching", description: "Enable application cache, if supported", defaultValue: "false", values: ["false", "true"] },
  { name: "CACHE_TTL_SECONDS", category: "Caching", description: "Requested application cache TTL", defaultValue: "300" },
  { name: "TZ", category: "Localization", description: "Process time zone", defaultValue: "Asia/Riyadh" },
  { name: "DEFAULT_LANGUAGE", category: "Localization", description: "Default application language", defaultValue: "en" },
  { name: "PAGE_SIZE", category: "Localization", description: "Default pagination size", defaultValue: "25" },
  { name: "METRICS_ENABLED", category: "Observability", description: "App-owned metrics collection switch", defaultValue: "false", values: ["false", "true"] },
  { name: "HEALTH_CHECK_INTERVAL_SECONDS", category: "Observability", description: "Application-side health interval if supported", defaultValue: "30" },
];

export const RUNTIME_CONFIG_PROFILES: readonly { id: string; title: string; description: string; names: readonly string[] }[] = [
  { id: "web", title: "Web/API baseline", description: "Environment, logging, request timeout and metrics", names: ["APP_ENV", "LOG_LEVEL", "REQUEST_TIMEOUT_SECONDS", "METRICS_ENABLED"] },
  { id: "worker", title: "Background worker", description: "Worker concurrency, batch size and logging", names: ["APP_ENV", "LOG_LEVEL", "WORKER_CONCURRENCY", "BATCH_SIZE"] },
  { id: "features", title: "Feature testing", description: "Optional switches for application testing", names: ["APP_DEBUG", "FEATURE_ENABLED", "READ_ONLY_MODE"] },
];
