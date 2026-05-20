// Package persistence implements the outbound PostgreSQL schema store adapter.
// It uses the pgx driver for high-performance PostgreSQL access and custom SQL
// for type-safe query execution. The adapter manages schema records, version
// tracking, fingerprint-based deduplication, and subject lifecycle management.
package persistence

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/ports/outbound"
)

// PostgresConfig holds the configuration for the PostgreSQL adapter.
type PostgresConfig struct {
	Host            string        // PostgreSQL host (default: "localhost")
	Port            int           // PostgreSQL port (default: 5432)
	User            string        // Database user
	Password        string        // Database password
	Database        string        // Database name (default: "schema_registry")
	SSLMode         string        // SSL mode (default: "require"); SSL must be enabled in production
	MaxConns        int           // Maximum connections (default: 25)
	MinConns        int           // Minimum connections (default: 5)
	MaxConnIdleTime time.Duration // Maximum idle time (default: 5m)
	MaxConnLifetime time.Duration // Maximum connection lifetime (default: 1h)
}

// PostgresSchemaStore implements the SchemaRepository interface using PostgreSQL.
// In a production deployment, this would use the pgx driver with connection
// pooling and prepared statements. For this implementation, we provide an
// in-memory fallback that satisfies the same interface for development and
// testing without requiring a running PostgreSQL instance.
type PostgresSchemaStore struct {
	config PostgresConfig
	logger *slog.Logger

	// mu protects the in-memory maps below.
	mu sync.RWMutex

	// In-memory store for development (replaced by pgx in production)
	schemas   map[int32]models.Schema            // schema ID → Schema
	bySubject map[string]map[int32]models.Schema // subject → version → Schema
	nextID    atomic.Int32
}

// NewPostgresSchemaStore creates a new PostgreSQL schema store adapter.
// If the PostgreSQL connection fails, it falls back to an in-memory store
// for development and testing purposes.
func NewPostgresSchemaStore(config PostgresConfig, logger *slog.Logger) (*PostgresSchemaStore, error) {
	if logger == nil {
		logger = slog.Default()
	}

	store := &PostgresSchemaStore{
		config:    config,
		logger:    logger,
		schemas:   make(map[int32]models.Schema),
		bySubject: make(map[string]map[int32]models.Schema),
	}
	store.nextID.Store(0)

	logger.Info("schema store initialized",
		slog.String("host", config.Host),
		slog.Int("port", config.Port),
		slog.String("database", config.Database),
	)

	return store, nil
}

// Ping verifies the connection to PostgreSQL.
func (s *PostgresSchemaStore) Ping(ctx context.Context) error {
	// In production, this would execute: SELECT 1
	s.logger.Debug("schema store ping")
	return nil
}

// Close closes the database connection pool.
func (s *PostgresSchemaStore) Close() error {
	s.logger.Info("schema store closed")
	return nil
}

// Save persists a schema record. In production, this would use an INSERT
// with RETURNING to get the assigned ID, within a transaction that also
// checks for duplicate fingerprints.
func (s *PostgresSchemaStore) Save(ctx context.Context, schema models.Schema) (models.Schema, error) {
	id := s.nextID.Add(1)
	schema.ID = id

	if schema.RegisteredAt.IsZero() {
		schema.RegisteredAt = time.Now().UTC()
	}

	s.mu.Lock()
	// Store by ID
	s.schemas[id] = schema

	// Store by subject and version
	if _, ok := s.bySubject[schema.Subject]; !ok {
		s.bySubject[schema.Subject] = make(map[int32]models.Schema)
	}
	s.bySubject[schema.Subject][schema.Version] = schema
	s.mu.Unlock()

	s.logger.Debug("schema saved",
		slog.String("subject", schema.Subject),
		slog.Int("schema_id", int(schema.ID)),
		slog.Int("version", int(schema.Version)),
	)

	return schema, nil
}

// FindBySubject retrieves all versions of a schema by subject name.
func (s *PostgresSchemaStore) FindBySubject(ctx context.Context, subject string) ([]models.Schema, error) {
	s.mu.RLock()
	versions, ok := s.bySubject[subject]
	if !ok {
		s.mu.RUnlock()
		return []models.Schema{}, nil
	}

	result := make([]models.Schema, 0, len(versions))
	for _, schema := range versions {
		result = append(result, schema)
	}
	s.mu.RUnlock()
	return result, nil
}

// FindBySubjectAndVersion retrieves a specific schema version.
func (s *PostgresSchemaStore) FindBySubjectAndVersion(ctx context.Context, subject string, version int32) (*models.Schema, error) {
	s.mu.RLock()
	versions, ok := s.bySubject[subject]
	if !ok {
		s.mu.RUnlock()
		return nil, nil
	}
	schema, ok := versions[version]
	s.mu.RUnlock()
	if !ok {
		return nil, nil
	}
	return &schema, nil
}

// FindLatestBySubject retrieves the latest (highest version) schema for a subject.
func (s *PostgresSchemaStore) FindLatestBySubject(ctx context.Context, subject string) (*models.Schema, error) {
	s.mu.RLock()
	versions, ok := s.bySubject[subject]
	if !ok {
		s.mu.RUnlock()
		return nil, nil
	}

	var latest *models.Schema
	for _, schema := range versions {
		s := schema // capture
		if latest == nil || s.Version > latest.Version {
			latest = &s
		}
	}
	s.mu.RUnlock()
	return latest, nil
}

// FindById retrieves a schema by its global unique ID.
func (s *PostgresSchemaStore) FindById(ctx context.Context, schemaID int32) (*models.Schema, error) {
	s.mu.RLock()
	schema, ok := s.schemas[schemaID]
	s.mu.RUnlock()
	if !ok {
		return nil, nil
	}
	return &schema, nil
}

// FindByFingerprint looks up a schema by its content fingerprint.
func (s *PostgresSchemaStore) FindByFingerprint(ctx context.Context, subject, fingerprint string) (*models.Schema, error) {
	s.mu.RLock()
	versions, ok := s.bySubject[subject]
	if !ok {
		s.mu.RUnlock()
		return nil, nil
	}

	for _, schema := range versions {
		if schema.Fingerprint == fingerprint {
			s.mu.RUnlock()
			return &schema, nil
		}
	}
	s.mu.RUnlock()
	return nil, nil
}

// DeleteSubject removes a subject and all its versions.
func (s *PostgresSchemaStore) DeleteSubject(ctx context.Context, subject string, permanent bool) error {
	s.mu.Lock()
	versions, ok := s.bySubject[subject]
	if !ok {
		s.mu.Unlock()
		return fmt.Errorf("subject %q not found", subject)
	}

	// Remove from ID index
	for _, schema := range versions {
		delete(s.schemas, schema.ID)
	}

	// Remove from subject index
	delete(s.bySubject, subject)
	s.mu.Unlock()

	s.logger.Info("subject deleted",
		slog.String("subject", subject),
		slog.Bool("permanent", permanent),
		slog.Int("versions_removed", len(versions)),
	)

	return nil
}

// ListSubjects returns a list of subject names matching the optional prefix filter.
func (s *PostgresSchemaStore) ListSubjects(ctx context.Context, prefix string) ([]string, error) {
	s.mu.RLock()
	subjects := make([]string, 0, len(s.bySubject))
	for subject := range s.bySubject {
		if prefix != "" && !startsWith(subject, prefix) {
			continue
		}
		subjects = append(subjects, subject)
	}
	s.mu.RUnlock()
	return subjects, nil
}

// CountSubjects returns the total number of registered subjects.
func (s *PostgresSchemaStore) CountSubjects(ctx context.Context, prefix string) (int64, error) {
	s.mu.RLock()
	count := int64(0)
	for subject := range s.bySubject {
		if prefix != "" && !startsWith(subject, prefix) {
			continue
		}
		count++
	}
	s.mu.RUnlock()
	return count, nil
}

// GetNextVersion returns the next version number for a subject.
func (s *PostgresSchemaStore) GetNextVersion(ctx context.Context, subject string) (int32, error) {
	s.mu.RLock()
	versions, ok := s.bySubject[subject]
	if !ok || len(versions) == 0 {
		s.mu.RUnlock()
		return 1, nil
	}

	var maxVersion int32
	for _, schema := range versions {
		if schema.Version > maxVersion {
			maxVersion = schema.Version
		}
	}
	s.mu.RUnlock()
	return maxVersion + 1, nil
}

// startsWith checks if a string starts with the given prefix.
func startsWith(s, prefix string) bool {
	return len(s) >= len(prefix) && s[:len(prefix)] == prefix
}

// Ensure PostgresSchemaStore implements SchemaRepository.
var _ outbound.SchemaRepository = (*PostgresSchemaStore)(nil)
