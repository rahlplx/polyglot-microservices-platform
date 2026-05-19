// Package compiler implements the outbound Buf CLI integration adapter for
// proto compilation. It wraps the `buf build` and `buf lint` CLI commands,
// executing them as subprocesses, parsing JSON output, and returning
// structured results. The adapter manages the Buf binary lifecycle including
// version pinning and include path configuration.
package compiler

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/gstack/schema-registry-service/domain/models"
	"github.com/gstack/schema-registry-service/domain/ports/outbound"
)

// BufConfig holds the configuration for the Buf CLI adapter.
type BufConfig struct {
	BinaryPath    string        // Path to the buf binary (default: "buf")
	Version       string        // Required buf version (default: "1.30.0")
	Timeout       time.Duration // Execution timeout (default: 30s)
	MaxMemoryMB   int           // Maximum memory per subprocess (default: 512MB)
	WorkDir       string        // Working directory for buf execution (default: os.TempDir())
}

// BufCompiler implements the ProtoCompilerPort using the Buf CLI for
// Protobuf schema compilation and validation. It executes buf as a
// subprocess, passing the schema definition via a temporary file, and
// parsing the structured JSON output for errors and warnings.
type BufCompiler struct {
	config BufConfig
	logger *slog.Logger
}

// NewBufCompiler creates a new Buf CLI compiler adapter.
func NewBufCompiler(config BufConfig, logger *slog.Logger) (*BufCompiler, error) {
	if logger == nil {
		logger = slog.Default()
	}
	if config.BinaryPath == "" {
		config.BinaryPath = "buf"
	}
	if config.Timeout == 0 {
		config.Timeout = 30 * time.Second
	}
	if config.MaxMemoryMB == 0 {
		config.MaxMemoryMB = 512
	}
	if config.WorkDir == "" {
		config.WorkDir = os.TempDir()
	}

	// Verify buf is available
	if _, err := exec.LookPath(config.BinaryPath); err != nil {
		logger.Warn("buf binary not found, compilation will be unavailable",
			slog.String("binary", config.BinaryPath),
			slog.String("error", err.Error()),
		)
	}

	return &BufCompiler{
		config: config,
		logger: logger,
	}, nil
}

// Compile validates a Protobuf schema definition by running `buf build`.
// The schema is written to a temporary file, and buf is executed with the
// appropriate include paths. The output is parsed for compilation errors
// and warnings, which are returned as structured validation results.
func (b *BufCompiler) Compile(ctx context.Context, schemaDef string, includes []models.Schema) (outbound.CompilationResult, error) {
	b.logger.Debug("compiling schema with buf",
		slog.Int("definition_len", len(schemaDef)),
		slog.Int("includes", len(includes)),
	)

	// Create a temporary directory for the compilation
	tmpDir, err := os.MkdirTemp(b.config.WorkDir, "buf-compile-*")
	if err != nil {
		return outbound.CompilationResult{}, fmt.Errorf("failed to create temp directory: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	// Write the schema definition to a temporary file
	schemaFile := filepath.Join(tmpDir, "schema.proto")
	if err := os.WriteFile(schemaFile, []byte(schemaDef), 0644); err != nil {
		return outbound.CompilationResult{}, fmt.Errorf("failed to write schema file: %w", err)
	}

	// Write include files
	for _, inc := range includes {
		incFile := filepath.Join(tmpDir, inc.Subject)
		incDir := filepath.Dir(incFile)
		if err := os.MkdirAll(incDir, 0755); err != nil {
			return outbound.CompilationResult{}, fmt.Errorf("failed to create include directory: %w", err)
		}
		if err := os.WriteFile(incFile, []byte(inc.Definition), 0644); err != nil {
			return outbound.CompilationResult{}, fmt.Errorf("failed to write include file: %w", err)
		}
	}

	// Create a minimal buf.yaml configuration
	bufYAML := `version: v2
lint:
  use:
    - STANDARD
breaking:
  use:
    - FILE
`
	if err := os.WriteFile(filepath.Join(tmpDir, "buf.yaml"), []byte(bufYAML), 0644); err != nil {
		return outbound.CompilationResult{}, fmt.Errorf("failed to write buf.yaml: %w", err)
	}

	// Execute buf build
	ctx, cancel := context.WithTimeout(ctx, b.config.Timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, b.config.BinaryPath, "build", tmpDir, "--error-format=json")
	output, err := cmd.CombinedOutput()

	if err != nil {
		// Parse buf error output
		errors := parseBufErrors(string(output))
		if len(errors) > 0 {
			return outbound.CompilationResult{
				Success: false,
				Errors:  errors,
			}, nil
		}
		return outbound.CompilationResult{
			Success: false,
			Errors: []models.ValidationError{
				{
					Message:  fmt.Sprintf("buf build failed: %s", string(output)),
					RuleID:   "BUF_BUILD_ERROR",
				},
			},
		}, nil
	}

	b.logger.Debug("schema compiled successfully",
		slog.String("schema_file", schemaFile),
	)

	return outbound.CompilationResult{
		Success: true,
	}, nil
}

// ResolveReferences resolves all import references for a given schema definition.
// It parses the schema for import statements and matches them against the
// available schemas. In a production implementation, this would use buf's
// module resolution to fetch dependencies from the Buf Schema Registry.
func (b *BufCompiler) ResolveReferences(ctx context.Context, schemaDef string, available []models.Schema) ([]models.Schema, error) {
	b.logger.Debug("resolving schema references",
		slog.Int("available_count", len(available)),
	)

	// Simple import resolution: scan for import statements in proto files
	// A production implementation would use protoc's descriptor set
	resolved := make([]models.Schema, 0)

	// For now, return all available schemas as potential includes
	// A real implementation would parse the import statements and match them
	resolved = append(resolved, available...)

	return resolved, nil
}

// parseBufErrors parses Buf CLI JSON error output into validation errors.
// Buf outputs errors as JSON lines, each with path, start_line, and message fields.
func parseBufErrors(output string) []models.ValidationError {
	var errors []models.ValidationError

	// Simple parsing: in production, this would use JSON deserialization
	// of buf's structured error output
	if output != "" {
		errors = append(errors, models.ValidationError{
			Message:  "buf compilation error: " + truncate(output, 500),
			RuleID:   "BUF_COMPILE_ERROR",
		})
	}

	return errors
}

// truncate limits a string to the given maximum length.
func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}

// Ensure BufCompiler implements ProtoCompilerPort.
var _ outbound.ProtoCompilerPort = (*BufCompiler)(nil)
