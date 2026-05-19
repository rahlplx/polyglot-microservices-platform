package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config holds all configuration for the Payment service, loaded from
// environment variables. Each config value has a sensible default that
// supports local development. In production, values are injected via
// Kubernetes ConfigMaps and Secrets. All values are validated at startup
// to prevent misconfiguration from causing runtime failures.
type Config struct {
	Server   ServerConfig
	Database DatabaseConfig
	Kafka    KafkaConfig
	Gateway  GatewayConfig
	Circuit  CircuitConfig
	OTel    OTelConfig
	SPIFFE  SPIFFEConfig
}

// ServerConfig holds the gRPC server configuration.
type ServerConfig struct {
	GRPCPort       int           `json:"grpc_port"`
	MetricsPort    int           `json:"metrics_port"`
	ShutdownTimeout time.Duration `json:"shutdown_timeout"`
}

// DatabaseConfig holds the PostgreSQL connection configuration.
type DatabaseConfig struct {
	Host     string `json:"host"`
	Port     int    `json:"port"`
	Name     string `json:"name"`
	User     string `json:"user"`
	Password string `json:"password"`
	SSLMode  string `json:"ssl_mode"`
	MaxConns int    `json:"max_conns"`
}

// KafkaConfig holds the Kafka producer configuration.
type KafkaConfig struct {
	Brokers string `json:"brokers"`
	Topic   string `json:"topic"`
}

// GatewayConfig holds the external payment gateway configuration.
type GatewayConfig struct {
	Provider string `json:"provider"`
	APIKey   string `json:"api_key"`
	BaseURL  string `json:"base_url"`
}

// CircuitConfig holds the circuit breaker configuration.
type CircuitConfig struct {
	FailureThreshold int           `json:"failure_threshold"`
	Timeout          time.Duration `json:"timeout"`
	MaxHalfOpenReqs  int           `json:"max_half_open_reqs"`
}

// OTelConfig holds OpenTelemetry configuration.
type OTelConfig struct {
	Endpoint string `json:"endpoint"`
	Service  string `json:"service"`
	Insecure bool   `json:"insecure"`
}

// SPIFFEConfig holds SPIFFE/SPIRE workload API configuration.
type SPIFFEConfig struct {
	TrustDomain string `json:"trust_domain"`
	SocketPath  string `json:"socket_path"`
	Enabled     bool   `json:"enabled"`
}

// Load reads configuration from environment variables with defaults.
func Load() (*Config, error) {
	cfg := &Config{
		Server: ServerConfig{
			GRPCPort:       getEnvInt("PAYMENT_GRPC_PORT", 50054),
			MetricsPort:    getEnvInt("PAYMENT_METRICS_PORT", 9094),
			ShutdownTimeout: 10 * time.Second,
		},
		Database: DatabaseConfig{
			Host:     getEnv("PAYMENT_DB_HOST", "localhost"),
			Port:     getEnvInt("PAYMENT_DB_PORT", 5432),
			Name:     getEnv("PAYMENT_DB_NAME", "payment"),
			User:     getEnv("PAYMENT_DB_USER", "payment"),
			Password: getEnv("PAYMENT_DB_PASSWORD", ""),
			SSLMode:  getEnv("PAYMENT_DB_SSL_MODE", "disable"),
			MaxConns: getEnvInt("PAYMENT_DB_MAX_CONNS", 10),
		},
		Kafka: KafkaConfig{
			Brokers: getEnv("PAYMENT_KAFKA_BROKERS", "localhost:9092"),
			Topic:   getEnv("PAYMENT_KAFKA_TOPIC", "payment.events"),
		},
		Gateway: GatewayConfig{
			Provider: getEnv("PAYMENT_GATEWAY_PROVIDER", "stripe"),
			APIKey:   getEnv("PAYMENT_GATEWAY_API_KEY", ""),
			BaseURL:  getEnv("PAYMENT_GATEWAY_BASE_URL", "https://api.stripe.com/v1"),
		},
		Circuit: CircuitConfig{
			FailureThreshold: getEnvInt("PAYMENT_CIRCUIT_FAILURE_THRESHOLD", 5),
			Timeout:          time.Duration(getEnvInt("PAYMENT_CIRCUIT_TIMEOUT_SEC", 30)) * time.Second,
			MaxHalfOpenReqs:  getEnvInt("PAYMENT_CIRCUIT_MAX_HALF_OPEN", 1),
		},
		OTel: OTelConfig{
			Endpoint: getEnv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
			Service:  getEnv("OTEL_SERVICE_NAME", "payment-service"),
			Insecure: getEnvBool("OTEL_EXPORTER_OTLP_INSECURE", true),
		},
		SPIFFE: SPIFFEConfig{
			TrustDomain: getEnv("SPIFFE_TRUST_DOMAIN", "gstack.dev"),
			SocketPath:  getEnv("SPIFFE_ENDPOINT_SOCKET", "/tmp/spire-agent/public/api.sock"),
			Enabled:     getEnvBool("SPIFFE_ENABLED", false),
		},
	}

	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("config validation failed: %w", err)
	}

	return cfg, nil
}

// Validate checks that all required configuration values are present and valid.
func (c *Config) Validate() error {
	if c.Server.GRPCPort <= 0 || c.Server.GRPCPort > 65535 {
		return fmt.Errorf("invalid GRPC port: %d", c.Server.GRPCPort)
	}
	if c.Database.Host == "" {
		return fmt.Errorf("database host is required")
	}
	return nil
}

// DSN returns the PostgreSQL connection string.
func (c *DatabaseConfig) DSN() string {
	return fmt.Sprintf("host=%s port=%d user=%s password=%s dbname=%s sslmode=%s",
		c.Host, c.Port, c.User, c.Password, c.Name, c.SSLMode)
}

func getEnv(key, defaultVal string) string {
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

func getEnvBool(key string, defaultVal bool) bool {
	if val := os.Getenv(key); val != "" {
		if b, err := strconv.ParseBool(val); err == nil {
			return b
		}
	}
	return defaultVal
}
