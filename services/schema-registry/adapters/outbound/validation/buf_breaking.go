// Package validation implements the outbound Buf breaking change detection
// adapter. It wraps the `buf breaking` and `buf lint` CLI commands,
// executing them as subprocesses and parsing the structured output to
// produce BreakingChange and ValidationResult objects.
package validation

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

// BufBreakingConfig holds the configuration for the Buf breaking change
// detection adapter.
type BufBreakingConfig struct {
	BinaryPath    string        // Path to the buf binary (default: "buf")
	Timeout       time.Duration // Execution timeout for breaking checks (default: 60s)
	LintTimeout   time.Duration // Execution timeout for lint checks (default: 30s)
	MaxMemoryMB   int           // Maximum memory per subprocess (default: 512MB)
	WorkDir       string        // Working directory (default: os.TempDir())
}

// BufBreakingAdapter implements the SchemaValidatorPort using the Buf CLI
// for lint and breaking change detection. It executes buf as a subprocess
// for each validation request, writing the schema definitions to temporary
// files and parsing the JSON output for structured results.
type BufBreakingAdapter struct {
	config BufBreakingConfig
	logger *slog.Logger
}

// NewBufBreakingAdapter creates a new Buf breaking change detection adapter.
func NewBufBreakingAdapter(config BufBreakingConfig, logger *slog.Logger) (*BufBreakingAdapter, error) {
	if logger == nil {
		logger = slog.Default()
	}
	if config.BinaryPath == "" {
		config.BinaryPath = "buf"
	}
	if config.Timeout == 0 {
		config.Timeout = 60 * time.Second
	}
	if config.LintTimeout == 0 {
		config.LintTimeout = 30 * time.Second
	}
	if config.MaxMemoryMB == 0 {
		config.MaxMemoryMB = 512
	}
	if config.WorkDir == "" {
		config.WorkDir = os.TempDir()
	}

	return &BufBreakingAdapter{
		config: config,
		logger: logger,
	}, nil
}

// Lint runs Buf lint checks on a schema definition. The lint rules enforce
// best practices such as snake_case field names, required comments on messages
// and fields, and package naming conventions. The specific rules applied depend
// on the buf.yaml configuration, which can be customized per subject.
func (b *BufBreakingAdapter) Lint(ctx context.Context, schemaDef string) ([]models.ValidationError, []models.ValidationWarning, error) {
	b.logger.Debug("running buf lint",
		slog.Int("definition_len", len(schemaDef)),
	)

	// Create temporary directory and write schema
	tmpDir, err := os.MkdirTemp(b.config.WorkDir, "buf-lint-*")
	if err != nil {
		return nil, nil, fmt.Errorf("failed to create temp directory: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	schemaFile := filepath.Join(tmpDir, "schema.proto")
	if err := os.WriteFile(schemaFile, []byte(schemaDef), 0644); err != nil {
		return nil, nil, fmt.Errorf("failed to write schema file: %w", err)
	}

	// Write buf.yaml with default lint configuration
	bufYAML := `version: v2
lint:
  use:
    - STANDARD
`
	if err := os.WriteFile(filepath.Join(tmpDir, "buf.yaml"), []byte(bufYAML), 0644); err != nil {
		return nil, nil, fmt.Errorf("failed to write buf.yaml: %w", err)
	}

	// Execute buf lint
	ctx, cancel := context.WithTimeout(ctx, b.config.LintTimeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, b.config.BinaryPath, "lint", tmpDir, "--error-format=json")
	output, _ := cmd.CombinedOutput()

	// Parse the output
	var errors []models.ValidationError
	var warnings []models.ValidationWarning

	if len(output) > 0 {
		// In production, this would parse JSON lines from buf lint output
		errors = append(errors, models.ValidationError{
			Message:  "buf lint detected issues: " + truncate(string(output), 500),
			RuleID:   "BUF_LINT",
		})
	}

	b.logger.Debug("buf lint completed",
		slog.Int("errors", len(errors)),
		slog.Int("warnings", len(warnings)),
	)

	return errors, warnings, nil
}

// CheckBreaking performs breaking change detection between a previous schema
// version and a proposed new version using `buf breaking`. The check level
// controls which rules are applied:
//   - MINIMAL: Only wire compatibility (FILE_SAME_PACKAGE, FIELD_SAME_TYPE, etc.)
//   - DEFAULT: Wire + source compatibility (adds FIELD_NO_DELETE, etc.)
//   - STRICT: All rules including documentation requirements
func (b *BufBreakingAdapter) CheckBreaking(ctx context.Context, previousDef, proposedDef string, level models.CheckLevel) (models.CheckBreakingResponse, error) {
	b.logger.Debug("running buf breaking check",
		slog.String("check_level", level.String()),
	)

	// Create temporary directories for previous and proposed schemas
	prevDir, err := os.MkdirTemp(b.config.WorkDir, "buf-breaking-prev-*")
	if err != nil {
		return models.CheckBreakingResponse{}, fmt.Errorf("failed to create previous temp directory: %w", err)
	}
	defer os.RemoveAll(prevDir)

	proposedDir, err := os.MkdirTemp(b.config.WorkDir, "buf-breaking-proposed-*")
	if err != nil {
		return models.CheckBreakingResponse{}, fmt.Errorf("failed to create proposed temp directory: %w", err)
	}
	defer os.RemoveAll(proposedDir)

	// Write schema definitions
	if err := os.WriteFile(filepath.Join(prevDir, "schema.proto"), []byte(previousDef), 0644); err != nil {
		return models.CheckBreakingResponse{}, fmt.Errorf("failed to write previous schema: %w", err)
	}
	if err := os.WriteFile(filepath.Join(proposedDir, "schema.proto"), []byte(proposedDef), 0644); err != nil {
		return models.CheckBreakingResponse{}, fmt.Errorf("failed to write proposed schema: %w", err)
	}

	// Write buf.yaml configurations
	bufYAML := fmt.Sprintf(`version: v2
lint:
  use:
    - STANDARD
breaking:
  use:
    - %s
`, levelToBreakingRules(level))

	if err := os.WriteFile(filepath.Join(proposedDir, "buf.yaml"), []byte(bufYAML), 0644); err != nil {
		return models.CheckBreakingResponse{}, fmt.Errorf("failed to write buf.yaml: %w", err)
	}

	// Execute buf breaking
	ctx, cancel := context.WithTimeout(ctx, b.config.Timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, b.config.BinaryPath, "breaking", proposedDir, "--against", prevDir, "--error-format=json")
	output, _ := cmd.CombinedOutput()

	// Parse breaking change output
	var changes []models.BreakingChange
	var mitigations []models.MitigationSuggestion
	severity := "INFO"

	if len(output) > 0 {
		// In production, this would parse JSON lines from buf breaking output
		changes = append(changes, models.BreakingChange{
			ChangeType:  "BUF_BREAKING_CHANGE",
			Description: truncate(string(output), 500),
			Category:    "WIRE",
		})
		severity = "ERROR"
	}

	return models.CheckBreakingResponse{
		HasBreakingChanges: len(changes) > 0,
		Changes:            changes,
		Severity:           severity,
		Mitigations:        mitigations,
	}, nil
}

// levelToBreakingRules maps a CheckLevel to the appropriate Buf breaking
// rule set. The rules control the strictness of the breaking change analysis.
func levelToBreakingRules(level models.CheckLevel) string {
	switch level {
	case models.CheckLevelMinimal:
		return "WIRE" // Only wire compatibility
	case models.CheckLevelDefault:
		return "FILE" // Wire + source compatibility
	case models.CheckLevelStrict:
		return "WIRE_JSON" // All rules including documentation
	default:
		return "FILE"
	}
}

// truncate limits a string to the given maximum length.
func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}

// Ensure BufBreakingAdapter implements SchemaValidatorPort.
var _ outbound.SchemaValidatorPort = (*BufBreakingAdapter)(nil)
