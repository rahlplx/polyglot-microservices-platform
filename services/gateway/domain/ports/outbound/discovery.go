// Package outbound defines the driven port interfaces (infrastructure interfaces)
// for the Gateway domain. These interfaces represent the capabilities that the
// Gateway needs from infrastructure components.
// ZERO external dependencies — only stdlib and domain types.
package outbound

import (
	"context"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
)

// EndpointChange represents a change in the set of available service endpoints.
type EndpointChange struct {
	Service string                   // Service name that changed
	Added   []models.ServiceEndpoint // Newly available endpoints
	Removed []models.ServiceEndpoint // Endpoints that are no longer available
}

// ServiceDiscoveryPort defines the interface for resolving service endpoints.
// The Gateway uses this to discover upstream service instances without
// hardcoding addresses, enabling dynamic routing as services scale.
type ServiceDiscoveryPort interface {
	// Resolve returns all currently available endpoints for the given service.
	// Returns an error if the service name is unknown or discovery fails.
	Resolve(ctx context.Context, serviceName string) ([]models.ServiceEndpoint, error)

	// Watch returns a channel that emits endpoint changes for the given service.
	// The caller should consume from the channel to keep its route table updated.
	// Call cancel on the context to stop watching.
	Watch(ctx context.Context, serviceName string) (<-chan EndpointChange, error)

	// ListServices returns the names of all currently registered services.
	ListServices(ctx context.Context) ([]string, error)
}
