// Package services implements the CompatibilityService domain service for the
// Schema Registry. This service encapsulates the business logic for checking
// schema compatibility at various levels (BACKWARD, FORWARD, FULL, and their
// transitive variants). It coordinates with the repository and validator ports
// to perform comprehensive compatibility analysis.
package services

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/gstack/schema-registry-service/domain/models"
	"github.com/gstack/schema-registry-service/domain/ports/outbound"
)

// CompatibilityService handles schema compatibility checking. It supports
// four primary compatibility levels (NONE, BACKWARD, FORWARD, FULL) plus
// their transitive variants. The service uses the validator port to perform
// the actual compatibility analysis and the repository port to fetch
// reference schema versions for comparison.
type CompatibilityService struct {
	repo      outbound.SchemaRepository
	validator outbound.SchemaValidatorPort
	logger    *slog.Logger
}

// NewCompatibilityService creates a new CompatibilityService with the given
// outbound ports. The logger may be nil — a default discard logger is used.
func NewCompatibilityService(
	repo outbound.SchemaRepository,
	validator outbound.SchemaValidatorPort,
	logger *slog.Logger,
) *CompatibilityService {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(nil, nil))
	}
	return &CompatibilityService{
		repo:      repo,
		validator: validator,
		logger:    logger,
	}
}

// CheckCompatibility checks whether a proposed schema is compatible with the
// reference versions according to the specified compatibility level. The check
// is performed against the latest version for non-transitive levels, or against
// all previous versions for transitive levels.
//
// Compatibility levels:
//   - NONE: No compatibility checking is performed. Any change is allowed.
//   - BACKWARD: New schema can read data produced by the previous version.
//   - FORWARD: Old schema can read data produced by the new version.
//   - FULL: Both BACKWARD and FORWARD compatibility must hold.
//   - BACKWARD_TRANSITIVE: New schema can read data from ALL previous versions.
//   - FORWARD_TRANSITIVE: ALL previous schemas can read data from the new version.
//   - FULL_TRANSITIVE: Both backward and forward transitive compatibility.
func (s *CompatibilityService) CheckCompatibility(
	ctx context.Context,
	subject string,
	proposedDef string,
	level models.CompatibilityLevel,
	targetVersion *int32,
) (models.CompatibilityResult, error) {
	s.logger.Debug("checking compatibility",
		slog.String("subject", subject),
		slog.String("level", level.String()),
	)

	// NONE level always returns compatible
	if level == models.CompatibilityNone {
		return models.CompatibilityResult{
			Compatible:       true,
			CompatibilityLvl: level,
		}, nil
	}

	// Fetch reference schemas for comparison
	var referenceSchemas []models.Schema
	var err error

	if level.IsTransitive() {
		// For transitive levels, check against ALL previous versions
		referenceSchemas, err = s.repo.FindBySubject(ctx, subject)
		if err != nil {
			return models.CompatibilityResult{}, fmt.Errorf("failed to fetch versions for subject %q: %w", subject, err)
		}
	} else {
		// For non-transitive levels, check only against the specified or latest version
		var refSchema *models.Schema
		if targetVersion != nil {
			refSchema, err = s.repo.FindBySubjectAndVersion(ctx, subject, *targetVersion)
			if err != nil {
				return models.CompatibilityResult{}, fmt.Errorf("failed to fetch version %d for subject %q: %w", *targetVersion, subject, err)
			}
		} else {
			refSchema, err = s.repo.FindLatestBySubject(ctx, subject)
			if err != nil {
				return models.CompatibilityResult{}, fmt.Errorf("failed to fetch latest version for subject %q: %w", subject, err)
			}
		}
		if refSchema != nil {
			referenceSchemas = []models.Schema{*refSchema}
		}
	}

	// If no reference schemas exist, any proposed schema is compatible
	if len(referenceSchemas) == 0 {
		return models.CompatibilityResult{
			Compatible:       true,
			CompatibilityLvl: level,
		}, nil
	}

	// Perform compatibility checks against all reference schemas
	allViolations := make([]models.CompatibilityViolation, 0)
	compatible := true

	for _, refSchema := range referenceSchemas {
		result, err := s.checkAgainstReference(ctx, refSchema.Definition, proposedDef, level)
		if err != nil {
			return models.CompatibilityResult{}, fmt.Errorf("compatibility check against version %d failed: %w", refSchema.Version, err)
		}
		if !result.Compatible {
			compatible = false
			allViolations = append(allViolations, result.Violations...)
		}
	}

	return models.CompatibilityResult{
		Compatible:       compatible,
		Violations:       allViolations,
		CompatibilityLvl: level,
	}, nil
}

// checkAgainstReference performs a single compatibility check between the
// proposed schema and a specific reference version. It checks both backward
// and forward compatibility as required by the specified level.
func (s *CompatibilityService) checkAgainstReference(
	ctx context.Context,
	previousDef string,
	proposedDef string,
	level models.CompatibilityLevel,
) (models.CompatibilityResult, error) {
	violations := make([]models.CompatibilityViolation, 0)

	// Backward compatibility: new schema can read old data
	if level.IsBackward() {
		breakingResp, err := s.validator.CheckBreaking(ctx, previousDef, proposedDef, models.CheckLevelDefault)
		if err != nil {
			return models.CompatibilityResult{}, fmt.Errorf("backward compatibility check failed: %w", err)
		}
		if breakingResp.HasBreakingChanges {
			for _, change := range breakingResp.Changes {
				violations = append(violations, models.CompatibilityViolation{
					Description:  "backward: " + change.Description,
					FieldPath:    change.FieldPath,
					Rule:         change.ChangeType,
					PreviousType: change.Category,
				})
			}
		}
	}

	// Forward compatibility: old schema can read new data
	if level.IsForward() {
		breakingResp, err := s.validator.CheckBreaking(ctx, proposedDef, previousDef, models.CheckLevelDefault)
		if err != nil {
			return models.CompatibilityResult{}, fmt.Errorf("forward compatibility check failed: %w", err)
		}
		if breakingResp.HasBreakingChanges {
			for _, change := range breakingResp.Changes {
				violations = append(violations, models.CompatibilityViolation{
					Description:  "forward: " + change.Description,
					FieldPath:    change.FieldPath,
					Rule:         change.ChangeType,
					PreviousType: change.Category,
				})
			}
		}
	}

	return models.CompatibilityResult{
		Compatible:       len(violations) == 0,
		Violations:       violations,
		CompatibilityLvl: level,
	}, nil
}
