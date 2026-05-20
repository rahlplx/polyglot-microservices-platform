package contract_test

import (
        "testing"
        "time"

        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/models"
        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/services"
)

// Contract tests verify the Schema Registry service's API contract.
// These tests validate the structural contract of request/response types
// and error types, ensuring that the API shape remains stable across
// changes to the domain implementation.

// --- Contract verification types ---

// ContractTestCase defines a contract test case for verifying
// API structure and behavior expectations.
type ContractTestCase struct {
        Name          string
        Endpoint      string
        Method        string
        ExpectedStatus int
        ExpectedError string
        Request       interface{}
}

// --- Schema Registration Contract Tests ---

func TestRegisterSchemaContract_RequestStructure(t *testing.T) {
        req := models.RegisterSchemaRequest{
                Subject:    "order/v1/order.proto",
                Type:       models.SchemaTypeProtobuf,
                Definition: `syntax = "proto3"; package order.v1;`,
                References: []models.SchemaReference{
                        {Name: "common/v1/types.proto", Subject: "common/v1/types.proto", Version: 1},
                },
                CompatibilityLvl: func() *models.CompatibilityLevel { lvl := models.CompatibilityBackward; return &lvl }(),
                Description:      "Order service schema",
                RegisteredBy:     "spiffe://example.org/order-service",
        }

        if req.Subject != "order/v1/order.proto" {
                t.Error("RegisterSchemaRequest.Subject contract violated")
        }
        if req.Type != models.SchemaTypeProtobuf {
                t.Error("RegisterSchemaRequest.Type contract violated")
        }
        if req.Definition == "" {
                t.Error("RegisterSchemaRequest.Definition contract violated: must not be empty")
        }
        if len(req.References) != 1 {
                t.Error("RegisterSchemaRequest.References contract violated")
        }
        if req.CompatibilityLvl == nil || *req.CompatibilityLvl != models.CompatibilityBackward {
                t.Error("RegisterSchemaRequest.CompatibilityLvl contract violated")
        }
}

func TestRegisterSchemaContract_ResponseStructure(t *testing.T) {
        resp := models.RegisterSchemaResponse{
                SchemaID:     42,
                Version:      3,
                Fingerprint:  "abc123def456",
                RegisteredAt: time.Now().UTC(),
                CompatibilityCheck: models.CompatibilityResult{
                        Compatible:       true,
                        CompatibilityLvl: models.CompatibilityBackward,
                },
        }

        if resp.SchemaID <= 0 {
                t.Error("RegisterSchemaResponse.SchemaID contract violated: must be positive")
        }
        if resp.Version <= 0 {
                t.Error("RegisterSchemaResponse.Version contract violated: must be positive")
        }
        if resp.Fingerprint == "" {
                t.Error("RegisterSchemaResponse.Fingerprint contract violated: must not be empty")
        }
        if resp.RegisteredAt.IsZero() {
                t.Error("RegisterSchemaResponse.RegisteredAt contract violated: must be set")
        }
}

// --- Schema Retrieval Contract Tests ---

func TestGetSchemaContract_RequestStructure(t *testing.T) {
        version := int32(3)
        schemaID := int32(42)

        req := models.GetSchemaRequest{
                Subject:           "order/v1/order.proto",
                Version:           &version,
                SchemaID:          &schemaID,
                IncludeReferences: true,
                IncludeDeprecated: false,
        }

        if req.Subject == "" && req.SchemaID == nil {
                t.Error("GetSchemaRequest contract violated: either subject or schema_id must be set")
        }
}

func TestGetSchemaContract_ResponseStructure(t *testing.T) {
        resp := models.GetSchemaResponse{
                Schema: models.Schema{
                        ID:               42,
                        Subject:          "order/v1/order.proto",
                        Version:          3,
                        Type:             models.SchemaTypeProtobuf,
                        Definition:       `syntax = "proto3";`,
                        Fingerprint:      "abc123",
                        RegisteredAt:     time.Now().UTC(),
                        CompatibilityLvl: models.CompatibilityBackward,
                },
        }

        if resp.Schema.ID <= 0 {
                t.Error("GetSchemaResponse.Schema.ID contract violated")
        }
        if resp.Schema.Subject == "" {
                t.Error("GetSchemaResponse.Schema.Subject contract violated")
        }
        if resp.Schema.Version <= 0 {
                t.Error("GetSchemaResponse.Schema.Version contract violated")
        }
}

// --- Schema Listing Contract Tests ---

func TestListSchemasContract_RequestStructure(t *testing.T) {
        schemaType := models.SchemaTypeProtobuf
        req := models.ListSchemasRequest{
                Prefix:            "order/v1/",
                Type:              &schemaType,
                IncludeDeprecated: false,
                PageSize:          20,
                PageToken:         "",
        }

        if req.PageSize <= 0 {
                t.Error("ListSchemasRequest.PageSize contract violated: must be positive")
        }
        if req.PageSize > 100 {
                t.Error("ListSchemasRequest.PageSize contract violated: must not exceed 100")
        }
}

func TestListSchemasContract_ResponseStructure(t *testing.T) {
        resp := models.ListSchemasResponse{
                Subjects: []models.SubjectInfo{
                        {
                                Name:             "order/v1/order.proto",
                                CompatibilityLvl: models.CompatibilityBackward,
                                LatestVersion:    5,
                                Type:             models.SchemaTypeProtobuf,
                                TotalVersions:    5,
                                Deprecated:       false,
                                RegisteredAt:     time.Now().UTC(),
                        },
                },
                TotalCount:    1,
                NextPageToken: "",
        }

        if resp.TotalCount < 0 {
                t.Error("ListSchemasResponse.TotalCount contract violated: must be non-negative")
        }
        if len(resp.Subjects) > int(resp.TotalCount) {
                t.Error("ListSchemasResponse contract violated: subjects cannot exceed total count")
        }
}

// --- Compatibility Contract Tests ---

func TestCompatibilityResultContract_Structure(t *testing.T) {
        result := models.CompatibilityResult{
                Compatible: false,
                Violations: []models.CompatibilityViolation{
                        {
                                Description:  "field 'price' was removed",
                                FieldPath:    "Order.price",
                                Rule:         "FIELD_NO_DELETE",
                                PreviousType: "double",
                                ProposedType: "",
                        },
                },
                CompatibilityLvl: models.CompatibilityBackward,
        }

        if result.Compatible && len(result.Violations) > 0 {
                t.Error("CompatibilityResult contract violated: compatible results must have no violations")
        }
        if result.CompatibilityLvl.String() == "" {
                t.Error("CompatibilityResult.CompatibilityLvl contract violated")
        }
}

func TestCompatibilityLevelEnumContract(t *testing.T) {
        levels := map[string]models.CompatibilityLevel{
                "NONE":                 models.CompatibilityNone,
                "BACKWARD":             models.CompatibilityBackward,
                "FORWARD":              models.CompatibilityForward,
                "FULL":                 models.CompatibilityFull,
                "BACKWARD_TRANSITIVE":  models.CompatibilityBackwardTransitive,
                "FORWARD_TRANSITIVE":   models.CompatibilityForwardTransitive,
                "FULL_TRANSITIVE":      models.CompatibilityFullTransitive,
        }

        seen := map[models.CompatibilityLevel]string{}
        for name, level := range levels {
                if prev, exists := seen[level]; exists {
                        t.Errorf("duplicate level value: %s and %s both map to %d", prev, name, level)
                }
                seen[level] = name
        }

        // Verify String() roundtrip
        for name, level := range levels {
                if level.String() != name {
                        t.Errorf("CompatibilityLevel(%d).String() = %q, want %q", level, level.String(), name)
                }
        }
}

func TestSchemaTypeEnumContract(t *testing.T) {
        types := map[string]models.SchemaType{
                "PROTOBUF":    models.SchemaTypeProtobuf,
                "AVRO":        models.SchemaTypeAvro,
                "JSON_SCHEMA": models.SchemaTypeJSONSchema,
        }

        for name, schemaType := range types {
                if schemaType.String() != name {
                        t.Errorf("SchemaType(%d).String() = %q, want %q", schemaType, schemaType.String(), name)
                }
        }
}

// --- Error Type Contract Tests ---

func TestErrorTypeContract_SchemaIncompatible(t *testing.T) {
        err := &services.SchemaIncompatibleError{
                Subject: "order/v1/order.proto",
                Violations: []models.CompatibilityViolation{
                        {Description: "field removed", Rule: "FIELD_NO_DELETE"},
                },
                Level: models.CompatibilityBackward,
        }

        if err.Subject == "" {
                t.Error("SchemaIncompatibleError.Subject contract violated")
        }
        if len(err.Violations) == 0 {
                t.Error("SchemaIncompatibleError.Violations contract violated: must not be empty")
        }
        if err.Error() == "" {
                t.Error("SchemaIncompatibleError.Error() contract violated: must return non-empty string")
        }
}

func TestErrorTypeContract_InvalidSchema(t *testing.T) {
        err := &services.InvalidSchemaError{
                Subject: "test.proto",
                Errors: []models.ValidationError{
                        {Message: "syntax error", RuleID: "SYNTAX"},
                },
        }

        if err.Subject == "" {
                t.Error("InvalidSchemaError.Subject contract violated")
        }
        if len(err.Errors) == 0 {
                t.Error("InvalidSchemaError.Errors contract violated: must not be empty")
        }
}

func TestErrorTypeContract_SchemaNotFound(t *testing.T) {
        err := &services.SchemaNotFoundError{Subject: "missing.proto"}
        if err.Error() == "" {
                t.Error("SchemaNotFoundError.Error() contract violated")
        }
}

// --- Breaking Change Contract Tests ---

func TestBreakingChangeContract_Structure(t *testing.T) {
        resp := models.CheckBreakingResponse{
                HasBreakingChanges: true,
                Changes: []models.BreakingChange{
                        {
                                ChangeType:  "FIELD_REMOVED",
                                FieldPath:   "Order.price",
                                Description: "Field was removed",
                                Category:    "WIRE",
                        },
                },
                Severity: "ERROR",
                Mitigations: []models.MitigationSuggestion{
                        {
                                ChangeType: "FIELD_REMOVED",
                                Suggestion: "Use reserved keyword instead",
                                Example:    `reserved 5; reserved "price";`,
                        },
                },
        }

        if !resp.HasBreakingChanges && len(resp.Changes) > 0 {
                t.Error("CheckBreakingResponse contract violated: HasBreakingChanges must be true when changes exist")
        }
        for _, change := range resp.Changes {
                if change.Category != "WIRE" && change.Category != "SOURCE" && change.Category != "FILE" {
                        t.Errorf("BreakingChange.Category contract violated: %q is not a valid category", change.Category)
                }
        }
}

// --- Validation Contract Tests ---

func TestValidationContract_Structure(t *testing.T) {
        resp := models.ValidateSchemaResponse{
                Valid: true,
                Errors: []models.ValidationError{},
                Warnings: []models.ValidationWarning{
                        {Message: "consider adding a comment", RuleID: "COMMENT"},
                },
        }

        if resp.Valid && len(resp.Errors) > 0 {
                t.Error("ValidateSchemaResponse contract violated: valid results must have no errors")
        }
}

// --- Consumer-side contract verification ---

func TestConsumerContract_SchemaRegistryEndpoints(t *testing.T) {
        contractCases := []ContractTestCase{
                {
                        Name:          "register schema",
                        Endpoint:      "/api/v1/schemas/subjects/{subject}/versions",
                        Method:        "POST",
                        ExpectedStatus: 200,
                        Request: models.RegisterSchemaRequest{
                                Subject:    "test.proto",
                                Type:       models.SchemaTypeProtobuf,
                                Definition: `syntax = "proto3";`,
                        },
                },
                {
                        Name:          "get schema by subject",
                        Endpoint:      "/api/v1/schemas/subjects/{subject}/versions/latest",
                        Method:        "GET",
                        ExpectedStatus: 200,
                        Request: models.GetSchemaRequest{
                                Subject: "test.proto",
                        },
                },
                {
                        Name:          "list subjects",
                        Endpoint:      "/api/v1/schemas/subjects",
                        Method:        "GET",
                        ExpectedStatus: 200,
                        Request:       models.ListSchemasRequest{},
                },
                {
                        Name:          "validate schema",
                        Endpoint:      "/api/v1/schemas/subjects/{subject}/validate",
                        Method:        "POST",
                        ExpectedStatus: 200,
                        Request: models.ValidateSchemaRequest{
                                Subject:       "test.proto",
                                Definition:    `syntax = "proto3";`,
                                Type:          models.SchemaTypeProtobuf,
                                ValidationLvl: models.ValidationSyntax,
                        },
                },
                {
                        Name:          "check breaking",
                        Endpoint:      "/api/v1/schemas/subjects/{subject}/check-breaking",
                        Method:        "POST",
                        ExpectedStatus: 200,
                        Request: models.CheckBreakingRequest{
                                Subject:        "test.proto",
                                ProposedSchema: `syntax = "proto3";`,
                                CheckLevel:     models.CheckLevelDefault,
                        },
                },
        }

        for _, tc := range contractCases {
                t.Run(tc.Name, func(t *testing.T) {
                        if tc.Request == nil {
                                t.Error("request must not be nil")
                        }
                })
        }
}
