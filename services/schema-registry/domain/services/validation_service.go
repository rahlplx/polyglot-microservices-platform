// Package services implements the ValidationService domain service for the
// Schema Registry. This service handles schema validation at multiple levels,
// from basic syntax checking to full Buf lint and breaking change analysis.
// It coordinates with the compiler and validator ports to perform each
// validation stage and aggregates the results.
package services

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/ports/outbound"
)

// ValidationService handles schema validation at multiple levels. It supports
// four validation levels: SYNTAX (parseability), SEMANTIC (naming conventions),
// COMPATIBILITY (breaking change detection), and FULL (all checks including
// Buf lint). The service is used by CI/CD pipelines and IDE plugins to
// validate schema changes before they are merged or registered.
type ValidationService struct {
	repo        outbound.SchemaRepository
	compiler    outbound.ProtoCompilerPort
	validator   outbound.SchemaValidatorPort
	compatSvc   *CompatibilityService
	logger      *slog.Logger
}

// NewValidationService creates a new ValidationService with the given
// outbound ports and compatibility service. The logger may be nil.
func NewValidationService(
	repo outbound.SchemaRepository,
	compiler outbound.ProtoCompilerPort,
	validator outbound.SchemaValidatorPort,
	compatSvc *CompatibilityService,
	logger *slog.Logger,
) *ValidationService {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(nil, nil))
	}
	return &ValidationService{
		repo:      repo,
		compiler:  compiler,
		validator: validator,
		compatSvc: compatSvc,
		logger:    logger,
	}
}

// Validate checks a schema definition without persisting it. The validation
// level controls the depth of analysis:
//   - SYNTAX: Verifies the schema is well-formed and parseable.
//   - SEMANTIC: Adds naming convention and style checks (Buf lint).
//   - COMPATIBILITY: Adds compatibility checking against the latest version.
//   - FULL: All checks including comprehensive Buf lint and breaking change detection.
//
// The response includes all errors and warnings found. Errors must be fixed
// before the schema can be registered; warnings should be reviewed but do
// not block registration.
func (s *ValidationService) Validate(ctx context.Context, req models.ValidateSchemaRequest) (models.ValidateSchemaResponse, error) {
	s.logger.Debug("validating schema",
		slog.String("subject", req.Subject),
		slog.String("level", req.ValidationLvl.String()),
		slog.String("type", req.Type.String()),
	)

	var allErrors []models.ValidationError
	var allWarnings []models.ValidationWarning
	var compatResult *models.CompatibilityResult

	// Stage 1: Syntax validation (always performed)
	syntaxErrors, syntaxWarnings := s.validateSyntax(ctx, req)
	allErrors = append(allErrors, syntaxErrors...)
	allWarnings = append(allWarnings, syntaxWarnings...)

	// If syntax validation fails, skip further checks
	if len(allErrors) > 0 {
		return models.ValidateSchemaResponse{
			Valid:    false,
			Errors:   allErrors,
			Warnings: allWarnings,
		}, nil
	}

	// Stage 2: Semantic validation (SEMANTIC and above)
	if req.ValidationLvl >= models.ValidationSemantic {
		semErrors, semWarnings := s.validateSemantic(ctx, req)
		allErrors = append(allErrors, semErrors...)
		allWarnings = append(allWarnings, semWarnings...)
	}

	// Stage 3: Compatibility checking (COMPATIBILITY and above)
	if req.ValidationLvl >= models.ValidationCompatibility {
		result, err := s.validateCompatibility(ctx, req)
		if err != nil {
			s.logger.Warn("compatibility validation failed",
				slog.String("subject", req.Subject),
				slog.String("error", err.Error()),
			)
		} else {
			compatResult = &result
			if !result.Compatible {
				for _, violation := range result.Violations {
					allErrors = append(allErrors, models.ValidationError{
						Message:  violation.Description,
						Location: violation.FieldPath,
						RuleID:   violation.Rule,
					})
				}
			}
		}
	}

	// Stage 4: Full validation (Buf lint + breaking change detection)
	if req.ValidationLvl >= models.ValidationFull {
		fullErrors, fullWarnings := s.validateFull(ctx, req)
		allErrors = append(allErrors, fullErrors...)
		allWarnings = append(allWarnings, fullWarnings...)
	}

	return models.ValidateSchemaResponse{
		Valid:              len(allErrors) == 0,
		Errors:             allErrors,
		Warnings:           allWarnings,
		CompatibilityResult: compatResult,
	}, nil
}

// CheckBreaking performs a detailed breaking change analysis between a
// proposed schema and a reference version. It uses the validator port to
// perform the analysis, which integrates with Buf's breaking change
// detection engine for comprehensive analysis.
func (s *ValidationService) CheckBreaking(ctx context.Context, req models.CheckBreakingRequest) (models.CheckBreakingResponse, error) {
	s.logger.Debug("checking for breaking changes",
		slog.String("subject", req.Subject),
		slog.String("check_level", req.CheckLevel.String()),
	)

	// Fetch the reference version
	var previousDef string
	if req.PreviousVersion != nil {
		refSchema, err := s.repo.FindBySubjectAndVersion(ctx, req.Subject, *req.PreviousVersion)
		if err != nil {
			return models.CheckBreakingResponse{}, fmt.Errorf("failed to fetch reference version %d: %w", *req.PreviousVersion, err)
		}
		if refSchema == nil {
			return models.CheckBreakingResponse{}, &SchemaNotFoundError{
				Subject: req.Subject,
				Version: req.PreviousVersion,
			}
		}
		previousDef = refSchema.Definition
	} else {
		refSchema, err := s.repo.FindLatestBySubject(ctx, req.Subject)
		if err != nil {
			return models.CheckBreakingResponse{}, fmt.Errorf("failed to fetch latest version: %w", err)
		}
		if refSchema == nil {
			return models.CheckBreakingResponse{}, &SchemaNotFoundError{Subject: req.Subject}
		}
		previousDef = refSchema.Definition
	}

	// Use the validator port to perform the breaking change check
	if s.validator == nil {
		return models.CheckBreakingResponse{}, fmt.Errorf("schema validator not available")
	}

	resp, err := s.validator.CheckBreaking(ctx, previousDef, req.ProposedSchema, req.CheckLevel)
	if err != nil {
		return models.CheckBreakingResponse{}, fmt.Errorf("breaking change check failed: %w", err)
	}

	return resp, nil
}

// validateSyntax performs syntax-level validation using the compiler port.
func (s *ValidationService) validateSyntax(ctx context.Context, req models.ValidateSchemaRequest) ([]models.ValidationError, []models.ValidationWarning) {
	if s.compiler == nil {
		// Without a compiler, we perform basic content validation
		if req.Definition == "" {
			return []models.ValidationError{{
				Message: "schema definition is empty",
				RuleID:  "EMPTY_DEFINITION",
			}}, nil
		}
		return nil, nil
	}

	// For Protobuf schemas, use the compiler for syntax validation
	if req.Type == models.SchemaTypeProtobuf {
		result, err := s.compiler.Compile(ctx, req.Definition, nil)
		if err != nil {
			return []models.ValidationError{{
				Message:  "schema compilation failed: " + err.Error(),
				RuleID:   "COMPILE_ERROR",
			}}, nil
		}
		if !result.Success {
			return result.Errors, result.Warnings
		}
	}

	return nil, nil
}

// validateSemantic performs semantic-level validation using the validator port.
func (s *ValidationService) validateSemantic(ctx context.Context, req models.ValidateSchemaRequest) ([]models.ValidationError, []models.ValidationWarning) {
	if s.validator == nil {
		return nil, nil
	}

	// For Protobuf schemas, run Buf lint
	if req.Type == models.SchemaTypeProtobuf {
		errors, warnings, err := s.validator.Lint(ctx, req.Definition)
		if err != nil {
			s.logger.Warn("lint check failed",
				slog.String("subject", req.Subject),
				slog.String("error", err.Error()),
			)
			return nil, nil
		}
		return errors, warnings
	}

	return nil, nil
}

// validateCompatibility performs compatibility-level validation against
// the latest registered version for the subject.
func (s *ValidationService) validateCompatibility(ctx context.Context, req models.ValidateSchemaRequest) (models.CompatibilityResult, error) {
	if s.compatSvc == nil {
		return models.CompatibilityResult{Compatible: true}, nil
	}

	// Determine the compatibility level from the subject's latest version
	level := models.CompatibilityBackward // default
	latest, err := s.repo.FindLatestBySubject(ctx, req.Subject)
	if err == nil && latest != nil {
		level = latest.CompatibilityLvl
	}

	return s.compatSvc.CheckCompatibility(ctx, req.Subject, req.Definition, level, req.TargetVersion)
}

// validateFull performs full validation including all Buf lint rules and
// breaking change detection at the strict level.
func (s *ValidationService) validateFull(ctx context.Context, req models.ValidateSchemaRequest) ([]models.ValidationError, []models.ValidationWarning) {
	if s.validator == nil {
		return nil, nil
	}

	// Run strict lint rules
	if req.Type == models.SchemaTypeProtobuf {
		errors, warnings, err := s.validator.Lint(ctx, req.Definition)
		if err != nil {
			s.logger.Warn("strict lint check failed",
				slog.String("subject", req.Subject),
				slog.String("error", err.Error()),
			)
			return nil, nil
		}
		return errors, warnings
	}

	return nil, nil
}
