// Package config provides configuration management for the Gateway service.
// It reads configuration from environment variables with sensible defaults
// and supports feature flags for gradual rollout.
package config

import (
        "fmt"
        "log/slog"
        "os"
        "strconv"
        "strings"
        "time"
)

// Config holds the complete configuration for the Gateway service.
type Config struct {
        // Server configuration
        Server ServerConfig

        // Redis configuration (for rate limiting)
        Redis RedisConfig

        // Kubernetes configuration (for service discovery)
        Kubernetes KubernetesConfig

        // OpenTelemetry configuration
        OTel OTelConfig

        // SPIFFE configuration
        SPIFFE SPIFFEConfig

        // Rate limit policies (keyed by policy name)
        RateLimitPolicies map[string]RateLimitPolicyConfig

        // Routes (keyed by route ID)
        Routes map[string]RouteConfig

        // Feature flags
        Features FeatureFlags

        // Deployment environment (e.g. "development", "staging", "production")
        Environment string
}

// ServerConfig holds HTTP and gRPC server configuration.
type ServerConfig struct {
        HTTPPort         int           // HTTP server port (default: 8080)
        GRPCPort         int           // gRPC server port (default: 9090)
        ReadTimeout      time.Duration // HTTP read timeout (default: 30s)
        WriteTimeout     time.Duration // HTTP write timeout (default: 30s)
        IdleTimeout      time.Duration // HTTP idle timeout (default: 120s)
        MaxRequestBody   int64         // Maximum request body size in bytes (default: 10MB)
        ShutdownTimeout  time.Duration // Graceful shutdown timeout (default: 15s)
        // SECURITY: AllowedOrigins must be explicitly configured in production.
        // An empty default ensures no origins are allowed unless explicitly
        // specified via the GATEWAY_ALLOWED_ORIGINS environment variable.
        // A wildcard "*" is rejected in production environments (see Validate).
        AllowedOrigins []string // CORS allowed origins
}

// RedisConfig holds Redis connection configuration.
type RedisConfig struct {
        Addr         string        // Redis address (default: "localhost:6379")
        Password     string        // Redis password
        DB           int           // Redis database number (default: 0)
        PoolSize     int           // Connection pool size (default: 10)
        MinIdleConns int           // Minimum idle connections (default: 5)
        DialTimeout  time.Duration // Dial timeout (default: 5s)
        ReadTimeout  time.Duration // Read timeout (default: 3s)
        WriteTimeout time.Duration // Write timeout (default: 3s)
        KeyPrefix    string        // Key prefix for rate limit counters
}

// KubernetesConfig holds Kubernetes service discovery configuration.
type KubernetesConfig struct {
        Namespace      string        // Kubernetes namespace (default: "default")
        ResyncInterval time.Duration // Resync interval (default: 30s)
        LabelSelector  string        // Label selector for filtering services
        InCluster      bool          // Whether running inside a cluster
        KubeconfigPath string        // Path to kubeconfig for out-of-cluster
}

// OTelConfig holds OpenTelemetry configuration.
type OTelConfig struct {
        Enabled         bool          // Whether OTel is enabled (default: true)
        Endpoint        string        // OTel Collector endpoint (default: "localhost:4317")
        ServiceName     string        // Service name (default: "gateway")
        ServiceVersion  string        // Service version (default: "0.1.0")
        TraceEnabled    bool          // Whether tracing is enabled (default: true)
        MetricsEnabled  bool          // Whether metrics are enabled (default: true)
        SampleRate      float64       // Trace sampling rate 0.0-1.0 (default: 0.1)
        ExportInterval  time.Duration // Metric export interval (default: 15s)
        ExportTimeout   time.Duration // Metric export timeout (default: 5s)
}

// SPIFFEConfig holds SPIFFE/SPIRE workload API configuration.
type SPIFFEConfig struct {
        Enabled        bool   // Whether SPIFFE validation is enabled (default: false)
        TrustDomain    string // SPIFFE trust domain (default: "example.org")
        WorkloadAPIAddr string // SPIRE Agent Workload API address (default: "unix:///tmp/spire-agent/public/api.sock")
        SVIDTTL        time.Duration // Expected SVID TTL (default: 1h)
}

// RateLimitPolicyConfig holds rate limit policy configuration.
type RateLimitPolicyConfig struct {
        RequestsPerSec float64       // Token refill rate
        BurstSize      int           // Maximum burst tokens
        Window         time.Duration // Sliding window
        KeyTemplate    string        // Rate limit key template
}

// RouteConfig holds a single route configuration entry.
type RouteConfig struct {
        ID              string        // Unique route identifier
        Pattern         string        // Path pattern
        Methods         []string      // Allowed HTTP methods
        UpstreamService string        // Target service name
        UpstreamPath    string        // Rewritten upstream path
        Timeout         time.Duration // Request timeout
        RetryCount      int           // Retry count
        RateLimitPolicy string        // Rate limit policy name
        RequireAuth     bool          // Whether auth is required
        Middleware      []string      // Middleware chain
}

// FeatureFlags holds feature flag configuration.
type FeatureFlags struct {
        EnableRateLimiting  bool // Enable/disable rate limiting (default: true)
        EnableAuth          bool // Enable/disable authentication (default: false)
        EnableCircuitBreaker bool // Enable/disable circuit breaker (default: false)
        EnableHotReload     bool // Enable/disable route hot-reload (default: true)
}

// Load reads configuration from environment variables and returns a Config.
// All config values have sensible defaults for local development.
func Load() (*Config, error) {
        cfg := &Config{
                Server: ServerConfig{
                        HTTPPort:        getEnvInt("GATEWAY_HTTP_PORT", 8080),
                        GRPCPort:        getEnvInt("GATEWAY_GRPC_PORT", 9090),
                        ReadTimeout:     getEnvDuration("GATEWAY_READ_TIMEOUT", 30*time.Second),
                        WriteTimeout:    getEnvDuration("GATEWAY_WRITE_TIMEOUT", 30*time.Second),
                        IdleTimeout:     getEnvDuration("GATEWAY_IDLE_TIMEOUT", 120*time.Second),
                        MaxRequestBody:  getEnvInt64("GATEWAY_MAX_REQUEST_BODY", 10*1024*1024),
                        ShutdownTimeout: getEnvDuration("GATEWAY_SHUTDOWN_TIMEOUT", 15*time.Second),
                        AllowedOrigins:  getEnvStringSlice("GATEWAY_ALLOWED_ORIGINS", []string{}),
                },
                Redis: RedisConfig{
                        Addr:         getEnvString("GATEWAY_REDIS_ADDR", "localhost:6379"),
                        Password:     getEnvString("GATEWAY_REDIS_PASSWORD", ""),
                        DB:           getEnvInt("GATEWAY_REDIS_DB", 0),
                        PoolSize:     getEnvInt("GATEWAY_REDIS_POOL_SIZE", 10),
                        MinIdleConns: getEnvInt("GATEWAY_REDIS_MIN_IDLE_CONNS", 5),
                        DialTimeout:  getEnvDuration("GATEWAY_REDIS_DIAL_TIMEOUT", 5*time.Second),
                        ReadTimeout:  getEnvDuration("GATEWAY_REDIS_READ_TIMEOUT", 3*time.Second),
                        WriteTimeout: getEnvDuration("GATEWAY_REDIS_WRITE_TIMEOUT", 3*time.Second),
                        KeyPrefix:    getEnvString("GATEWAY_REDIS_KEY_PREFIX", "gateway:ratelimit:"),
                },
                Kubernetes: KubernetesConfig{
                        Namespace:      getEnvString("GATEWAY_K8S_NAMESPACE", "default"),
                        ResyncInterval: getEnvDuration("GATEWAY_K8S_RESYNC_INTERVAL", 30*time.Second),
                        LabelSelector:  getEnvString("GATEWAY_K8S_LABEL_SELECTOR", ""),
                        InCluster:      getEnvBool("GATEWAY_K8S_IN_CLUSTER", true),
                        KubeconfigPath: getEnvString("GATEWAY_K8S_KUBECONFIG", ""),
                },
                OTel: OTelConfig{
                        Enabled:        getEnvBool("GATEWAY_OTEL_ENABLED", true),
                        Endpoint:       getEnvString("GATEWAY_OTEL_ENDPOINT", "localhost:4317"),
                        ServiceName:    getEnvString("GATEWAY_OTEL_SERVICE_NAME", "gateway"),
                        ServiceVersion: getEnvString("GATEWAY_OTEL_SERVICE_VERSION", "0.1.0"),
                        TraceEnabled:   getEnvBool("GATEWAY_OTEL_TRACE_ENABLED", true),
                        MetricsEnabled: getEnvBool("GATEWAY_OTEL_METRICS_ENABLED", true),
                        SampleRate:     getEnvFloat("GATEWAY_OTEL_SAMPLE_RATE", 0.1),
                        ExportInterval: getEnvDuration("GATEWAY_OTEL_EXPORT_INTERVAL", 15*time.Second),
                        ExportTimeout:  getEnvDuration("GATEWAY_OTEL_EXPORT_TIMEOUT", 5*time.Second),
                },
                SPIFFE: SPIFFEConfig{
                        Enabled:        getEnvBool("GATEWAY_SPIFFE_ENABLED", false),
                        TrustDomain:    getEnvString("GATEWAY_SPIFFE_TRUST_DOMAIN", "example.org"),
                        WorkloadAPIAddr: getEnvString("GATEWAY_SPIFFE_WORKLOAD_API", "unix:///tmp/spire-agent/public/api.sock"),
                        SVIDTTL:        getEnvDuration("GATEWAY_SPIFFE_SVID_TTL", 1*time.Hour),
                },
                RateLimitPolicies: defaultRateLimitPolicies(),
                Routes:            defaultRoutes(),
                Environment: getEnvString("GATEWAY_ENVIRONMENT", "development"),
                Features: FeatureFlags{
                        EnableRateLimiting:   getEnvBool("GATEWAY_FEATURE_RATE_LIMITING", true),
                        EnableAuth:           getEnvBool("GATEWAY_FEATURE_AUTH", false),
                        EnableCircuitBreaker: getEnvBool("GATEWAY_FEATURE_CIRCUIT_BREAKER", false),
                        EnableHotReload:      getEnvBool("GATEWAY_FEATURE_HOT_RELOAD", true),
                },
        }

        if err := cfg.Validate(); err != nil {
                return nil, fmt.Errorf("configuration validation failed: %w", err)
        }

        return cfg, nil
}

// Validate checks the configuration for errors.
func (c *Config) Validate() error {
        if c.Server.HTTPPort < 1 || c.Server.HTTPPort > 65535 {
                return fmt.Errorf("invalid HTTP port: %d", c.Server.HTTPPort)
        }
        if c.Server.GRPCPort < 1 || c.Server.GRPCPort > 65535 {
                return fmt.Errorf("invalid gRPC port: %d", c.Server.GRPCPort)
        }
        if c.Server.HTTPPort == c.Server.GRPCPort {
                return fmt.Errorf("HTTP and gRPC ports must be different, got %d", c.Server.HTTPPort)
        }
        if c.OTel.SampleRate < 0 || c.OTel.SampleRate > 1 {
                return fmt.Errorf("invalid OTel sample rate: %f (must be 0.0-1.0)", c.OTel.SampleRate)
        }
        for name, policy := range c.RateLimitPolicies {
                if policy.RequestsPerSec <= 0 {
                        return fmt.Errorf("rate limit policy %q has invalid requests_per_sec: %f", name, policy.RequestsPerSec)
                }
                if policy.BurstSize <= 0 {
                        return fmt.Errorf("rate limit policy %q has invalid burst_size: %d", name, policy.BurstSize)
                }
        }
        // SECURITY: Reject wildcard CORS origins in production environments.
        // Allowing "*" permits any origin to make cross-origin requests,
        // which is unacceptable in production. Origins must be explicitly
        // enumerated via the GATEWAY_ALLOWED_ORIGINS environment variable.
        if c.Environment == "production" {
                for _, origin := range c.Server.AllowedOrigins {
                        if origin == "*" {
                                return fmt.Errorf(
                                        "CORS wildcard '*' is not allowed in production; " +
                                                "explicitly set GATEWAY_ALLOWED_ORIGINS to a list of trusted origin URLs " +
                                                "(e.g. 'https://app.example.com,https://admin.example.com')",
                                )
                        }
                }
        }
        return nil
}

// LogConfig logs the current configuration at info level (secrets are redacted).
func (c *Config) LogConfig(logger *slog.Logger) {
        logger.Info("gateway configuration",
                slog.Int("http_port", c.Server.HTTPPort),
                slog.Int("grpc_port", c.Server.GRPCPort),
                slog.String("redis_addr", c.Redis.Addr),
                slog.Bool("redis_password_set", c.Redis.Password != ""),
                slog.String("k8s_namespace", c.Kubernetes.Namespace),
                slog.Bool("otel_enabled", c.OTel.Enabled),
                slog.String("otel_endpoint", c.OTel.Endpoint),
                slog.Bool("spiffe_enabled", c.SPIFFE.Enabled),
                slog.Int("route_count", len(c.Routes)),
                slog.Int("policy_count", len(c.RateLimitPolicies)),
        )
}

// --- Default configuration ---

func defaultRateLimitPolicies() map[string]RateLimitPolicyConfig {
        return map[string]RateLimitPolicyConfig{
                "default": {
                        RequestsPerSec: 100,
                        BurstSize:      200,
                        Window:         60 * time.Second,
                        KeyTemplate:    "{{.ClientID}}:{{.Route}}",
                },
                "high-throughput": {
                        RequestsPerSec: 1000,
                        BurstSize:      2000,
                        Window:         60 * time.Second,
                        KeyTemplate:    "{{.ClientID}}:{{.Route}}",
                },
                "strict": {
                        RequestsPerSec: 10,
                        BurstSize:      20,
                        Window:         60 * time.Second,
                        KeyTemplate:    "{{.ClientID}}:{{.Route}}",
                },
        }
}

func defaultRoutes() map[string]RouteConfig {
        return map[string]RouteConfig{
                "catalog-api": {
                        ID:              "catalog-api",
                        Pattern:         "/api/v1/catalog/*",
                        Methods:         []string{"GET", "POST"},
                        UpstreamService: "catalog",
                        Timeout:         10 * time.Second,
                        RetryCount:      3,
                        RateLimitPolicy: "default",
                        RequireAuth:     false,
                        Middleware:      []string{"logging", "ratelimit"},
                },
                "order-api": {
                        ID:              "order-api",
                        Pattern:         "/api/v1/orders/*",
                        Methods:         []string{"GET", "POST", "PUT", "PATCH"},
                        UpstreamService: "order",
                        Timeout:         30 * time.Second,
                        RetryCount:      2,
                        RateLimitPolicy: "strict",
                        RequireAuth:     true,
                        Middleware:      []string{"logging", "auth", "ratelimit"},
                },
                "payment-api": {
                        ID:              "payment-api",
                        Pattern:         "/api/v1/payments/*",
                        Methods:         []string{"POST"},
                        UpstreamService: "payment",
                        Timeout:         15 * time.Second,
                        RetryCount:      1,
                        RateLimitPolicy: "strict",
                        RequireAuth:     true,
                        Middleware:      []string{"logging", "auth", "ratelimit", "circuit-breaker"},
                },
                "health": {
                        ID:              "health",
                        Pattern:         "/health",
                        Methods:         []string{"GET"},
                        UpstreamService: "",
                        Timeout:         5 * time.Second,
                        RetryCount:      0,
                        RateLimitPolicy: "",
                        RequireAuth:     false,
                        Middleware:      []string{},
                },
        }
}

// --- Environment variable helpers ---

func getEnvString(key, defaultVal string) string {
        if val := os.Getenv(key); val != "" {
                return val
        }
        return defaultVal
}

func getEnvInt(key string, defaultVal int) int {
        if val := os.Getenv(key); val != "" {
                if n, err := strconv.Atoi(val); err == nil {
                        return n
                }
        }
        return defaultVal
}

func getEnvInt64(key string, defaultVal int64) int64 {
        if val := os.Getenv(key); val != "" {
                if n, err := strconv.ParseInt(val, 10, 64); err == nil {
                        return n
                }
        }
        return defaultVal
}

func getEnvBool(key string, defaultVal bool) bool {
        if val := os.Getenv(key); val != "" {
                if b, err := strconv.ParseBool(val); err == nil {
                        return b
                }
        }
        return defaultVal
}

func getEnvFloat(key string, defaultVal float64) float64 {
        if val := os.Getenv(key); val != "" {
                if f, err := strconv.ParseFloat(val, 64); err == nil {
                        return f
                }
        }
        return defaultVal
}

func getEnvDuration(key string, defaultVal time.Duration) time.Duration {
        if val := os.Getenv(key); val != "" {
                if d, err := time.ParseDuration(val); err == nil {
                        return d
                }
        }
        return defaultVal
}

func getEnvStringSlice(key string, defaultVal []string) []string {
        if val := os.Getenv(key); val != "" {
                return strings.Split(val, ",")
        }
        return defaultVal
}
