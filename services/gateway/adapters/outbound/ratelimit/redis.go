// Package ratelimit implements the outbound Redis-based rate limiter adapter.
// It uses a token bucket algorithm backed by Redis for distributed rate limiting
// with atomic operations and TTL-based expiration.
package ratelimit

import (
        "context"
        "fmt"
        "log/slog"
        "strconv"
        "time"

        "github.com/redis/go-redis/v9"

        "github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
        "github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/ports/outbound"
)

// RedisConfig holds the configuration for the Redis rate limiter adapter.
type RedisConfig struct {
        Addr         string        // Redis server address (host:port)
        Password     string        // Redis password (empty = no auth)
        DB           int           // Redis database number
        PoolSize     int           // Connection pool size
        MinIdleConns int           // Minimum idle connections
        DialTimeout  time.Duration // Connection dial timeout
        ReadTimeout  time.Duration // Read operation timeout
        WriteTimeout time.Duration // Write operation timeout
        KeyPrefix    string        // Prefix for all rate limit keys in Redis
}

// RedisRateLimiter implements the RateLimiterPort using Redis for
// distributed token bucket rate limiting. It uses Lua scripts for
// atomic token bucket operations.
type RedisRateLimiter struct {
        client  *redis.Client
        config  RedisConfig
        logger  *slog.Logger

        // Lua script for atomic token bucket allow operation.
        // KEYS[1] = rate limit key
        // ARGV[1] = max tokens (burst size)
        // ARGV[2] = refill rate (tokens per second, as float string)
        // ARGV[3] = current timestamp (Unix nanoseconds)
        // ARGV[4] = requested tokens (usually 1)
        // Returns: {allowed (0/1), remaining_tokens, reset_timestamp_ns}
        allowScript *redis.Script

        // Lua script for getting current bucket status without consuming tokens.
        // Same keys/argv as allow, but does not decrement.
        // Returns: {allowed (always 1), remaining_tokens, reset_timestamp_ns}
        getStatusScript *redis.Script
}

// NewRedisRateLimiter creates a new Redis-backed rate limiter.
func NewRedisRateLimiter(config RedisConfig, logger *slog.Logger) (*RedisRateLimiter, error) {
        if logger == nil {
                logger = slog.Default()
        }
        if config.KeyPrefix == "" {
                config.KeyPrefix = "gateway:ratelimit:"
        }
        if config.PoolSize == 0 {
                config.PoolSize = 10
        }
        if config.DialTimeout == 0 {
                config.DialTimeout = 5 * time.Second
        }
        if config.ReadTimeout == 0 {
                config.ReadTimeout = 3 * time.Second
        }
        if config.WriteTimeout == 0 {
                config.WriteTimeout = 3 * time.Second
        }

        client := redis.NewClient(&redis.Options{
                Addr:         config.Addr,
                Password:     config.Password,
                DB:           config.DB,
                PoolSize:     config.PoolSize,
                MinIdleConns: config.MinIdleConns,
                DialTimeout:  config.DialTimeout,
                ReadTimeout:  config.ReadTimeout,
                WriteTimeout: config.WriteTimeout,
        })

        // Token bucket allow script: atomically check and consume a token.
        // The script maintains the bucket's last refill time and token count.
        allowScript := redis.NewScript(`
                local key = KEYS[1]
                local max_tokens = tonumber(ARGV[1])
                local refill_rate = tonumber(ARGV[2])
                local now_ns = tonumber(ARGV[3])
                local requested = tonumber(ARGV[4])

                -- Get current bucket state
                local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
                local tokens = tonumber(bucket[1])
                local last_refill = tonumber(bucket[2])

                -- Initialize bucket if it doesn't exist
                if tokens == nil then
                        tokens = max_tokens
                        last_refill = now_ns
                end

                -- Calculate tokens to add based on elapsed time
                local elapsed_ns = now_ns - last_refill
                local elapsed_sec = elapsed_ns / 1000000000.0
                local tokens_to_add = elapsed_sec * refill_rate
                tokens = math.min(max_tokens, tokens + tokens_to_add)
                last_refill = now_ns

                -- Check if request can be allowed
                local allowed = 0
                if tokens >= requested then
                        tokens = tokens - requested
                        allowed = 1
                end

                -- Calculate reset time (when bucket will be full)
                local tokens_needed = max_tokens - tokens
                local seconds_to_full = tokens_needed / refill_rate
                local reset_ns = now_ns + (seconds_to_full * 1000000000.0)

                -- Store updated bucket state
                redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)

                -- Set TTL to 2x the time to fill the bucket (auto-cleanup)
                local ttl_sec = math.ceil((max_tokens / refill_rate) * 2)
                if ttl_sec > 0 then
                        redis.call('EXPIRE', key, ttl_sec)
                end

                return {allowed, math.floor(tokens), math.floor(reset_ns)}
        `)

        // Get status script: check the bucket without consuming a token.
        getStatusScript := redis.NewScript(`
                local key = KEYS[1]
                local max_tokens = tonumber(ARGV[1])
                local refill_rate = tonumber(ARGV[2])
                local now_ns = tonumber(ARGV[3])

                -- Get current bucket state
                local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
                local tokens = tonumber(bucket[1])
                local last_refill = tonumber(bucket[2])

                -- Initialize bucket if it doesn't exist
                if tokens == nil then
                        tokens = max_tokens
                        last_refill = now_ns
                end

                -- Calculate tokens to add based on elapsed time
                local elapsed_ns = now_ns - last_refill
                local elapsed_sec = elapsed_ns / 1000000000.0
                local tokens_to_add = elapsed_sec * refill_rate
                tokens = math.min(max_tokens, tokens + tokens_to_add)

                -- Calculate reset time
                local tokens_needed = max_tokens - tokens
                local seconds_to_full = tokens_needed / refill_rate
                local reset_ns = now_ns + (seconds_to_full * 1000000000.0)

                return {1, math.floor(tokens), math.floor(reset_ns)}
        `)

        rl := &RedisRateLimiter{
                client:          client,
                config:          config,
                logger:          logger,
                allowScript:     allowScript,
                getStatusScript: getStatusScript,
        }

        return rl, nil
}

// Ping verifies the connection to Redis.
func (rl *RedisRateLimiter) Ping(ctx context.Context) error {
        if err := rl.client.Ping(ctx).Err(); err != nil {
                return fmt.Errorf("redis ping failed: %w", err)
        }
        return nil
}

// Close closes the Redis connection.
func (rl *RedisRateLimiter) Close() error {
        if err := rl.client.Close(); err != nil {
                return fmt.Errorf("failed to close redis client: %w", err)
        }
        return nil
}

// Allow checks whether a request with the given key is allowed under the
// specified rate limit policy. It atomically consumes one token if allowed.
func (rl *RedisRateLimiter) Allow(ctx context.Context, key string, policy models.RateLimitPolicy) (models.RateLimitStatus, error) {
        redisKey := rl.config.KeyPrefix + key
        now := time.Now().UTC().UnixNano()

        result, err := rl.allowScript.Run(ctx, rl.client,
                []string{redisKey},
                policy.BurstSize,
                strconv.FormatFloat(policy.RequestsPerSec, 'f', -1, 64),
                now,
                1, // request 1 token
        ).Int64Slice()

        if err != nil {
                return models.RateLimitStatus{}, fmt.Errorf("redis allow script failed for key %q: %w", key, err)
        }

        allowed := result[0] == 1
        remaining := int(result[1])
        resetAt := time.Unix(0, result[2])

        var retryAfter time.Duration
        if !allowed {
                // Calculate how long until at least 1 token is available
                if policy.RequestsPerSec > 0 {
                        retryAfter = time.Duration(float64(time.Second) / policy.RequestsPerSec)
                } else {
                        retryAfter = policy.Window
                }
        }

        rl.logger.Debug("rate limit check",
                slog.String("key", key),
                slog.Bool("allowed", allowed),
                slog.Int("remaining", remaining),
        )

        return models.RateLimitStatus{
                Key:        key,
                Allowed:    allowed,
                Remaining:  remaining,
                Limit:      policy.BurstSize,
                ResetAt:    resetAt,
                Policy:     policy.Name,
                RetryAfter: retryAfter,
        }, nil
}

// GetStatus returns the current rate limit status for the given key
// without consuming a token.
func (rl *RedisRateLimiter) GetStatus(ctx context.Context, key string, policy models.RateLimitPolicy) (models.RateLimitStatus, error) {
        redisKey := rl.config.KeyPrefix + key
        now := time.Now().UTC().UnixNano()

        result, err := rl.getStatusScript.Run(ctx, rl.client,
                []string{redisKey},
                policy.BurstSize,
                strconv.FormatFloat(policy.RequestsPerSec, 'f', -1, 64),
                now,
        ).Int64Slice()

        if err != nil {
                return models.RateLimitStatus{}, fmt.Errorf("redis get-status script failed for key %q: %w", key, err)
        }

        remaining := int(result[1])
        resetAt := time.Unix(0, result[2])

        var retryAfter time.Duration
        if remaining <= 0 && policy.RequestsPerSec > 0 {
                retryAfter = time.Duration(float64(time.Second) / policy.RequestsPerSec)
        }

        return models.RateLimitStatus{
                Key:        key,
                Allowed:    remaining > 0,
                Remaining:  remaining,
                Limit:      policy.BurstSize,
                ResetAt:    resetAt,
                Policy:     policy.Name,
                RetryAfter: retryAfter,
        }, nil
}

// Reset clears the rate limit counter for the given key.
func (rl *RedisRateLimiter) Reset(ctx context.Context, key string) error {
        redisKey := rl.config.KeyPrefix + key
        if err := rl.client.Del(ctx, redisKey).Err(); err != nil {
                return fmt.Errorf("redis delete failed for key %q: %w", key, err)
        }
        rl.logger.Debug("rate limit counter reset", slog.String("key", key))
        return nil
}

// Ensure RedisRateLimiter implements RateLimiterPort.
var _ outbound.RateLimiterPort = (*RedisRateLimiter)(nil)
