package di

import (
        "context"
        "log/slog"
        "os"

        "github.com/rahlplx/polyglot-microservices-platform/services/payment/adapters/inbound/grpc"
        "github.com/rahlplx/polyglot-microservices-platform/services/payment/adapters/outbound/gateway"
        "github.com/rahlplx/polyglot-microservices-platform/services/payment/adapters/outbound/messaging"
        "github.com/rahlplx/polyglot-microservices-platform/services/payment/adapters/outbound/persistence"
        "github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
        "github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/services"
        "github.com/rahlplx/polyglot-microservices-platform/services/payment/infrastructure/config"
)

// Container holds all wired dependencies for the Payment service.
// It follows the composition root pattern — all concrete implementations
// are created here and injected as interfaces into the services that need them.
// This manual DI approach avoids reflection-based frameworks, keeping the
// dependency graph explicit and compile-time verified.
type Container struct {
        Config          *config.Config
        PaymentService  *services.PaymentService
        CircuitBreaker  *services.CircuitBreakerService
        GRPCHandler     *grpc.Handler
        PaymentRepo     *persistence.PostgresTransactionRepo
        EventPublisher  *messaging.KafkaEventPublisher
        StripeAdapter   *gateway.StripeAdapter
}

// NewContainer creates and wires all dependencies for the Payment service.
// The wiring follows the dependency graph:
//
//      GRPCHandler → PaymentService → { StripeAdapter, PostgresRepo, KafkaPublisher, CircuitBreaker }
func NewContainer(cfg *config.Config) *Container {
        logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))

        // Outbound adapters (infrastructure layer).
        paymentRepo := persistence.NewPostgresTransactionRepo(logger)
        eventPublisher := messaging.NewKafkaEventPublisher(cfg.Kafka.Brokers, cfg.Kafka.Topic, logger)
        stripeAdapter := gateway.NewStripeAdapter(cfg.Gateway.APIKey, logger)

        // Circuit breaker service (domain service with infrastructure config).
        circuitConfig := models.CircuitConfig{
                Name:                "stripe-gateway",
                FailureThreshold:    cfg.Circuit.FailureThreshold,
                Timeout:             cfg.Circuit.Timeout,
                MaxHalfOpenRequests: cfg.Circuit.MaxHalfOpenReqs,
                OnStateChange: func(from, to models.CircuitState) {
                        event := models.CircuitBreakerEvent{
                                CircuitName: "stripe-gateway",
                                FromState:   from,
                                ToState:     to,
                                Reason:      "threshold_exceeded",
                        }
                        _ = eventPublisher.PublishCircuitEvent(context.Background(), event)
                },
        }
        circuitBreaker := services.NewCircuitBreakerService(circuitConfig, logger)

        // Application service (domain layer).
        paymentService := services.NewPaymentService(
                stripeAdapter,
                paymentRepo,
                eventPublisher,
                circuitBreaker,
                logger,
        )

        // Inbound adapters (driving adapters).
        grpcHandler := grpc.NewHandler(paymentService, logger)

        return &Container{
                Config:         cfg,
                PaymentService: paymentService,
                CircuitBreaker: circuitBreaker,
                GRPCHandler:    grpcHandler,
                PaymentRepo:    paymentRepo,
                EventPublisher: eventPublisher,
                StripeAdapter:  stripeAdapter,
        }
}
