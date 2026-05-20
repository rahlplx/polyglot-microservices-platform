package grpc

import (
        "context"
        "log/slog"

        "google.golang.org/grpc/codes"
        "google.golang.org/grpc/status"

        "github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
        "github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/services"
)

// Handler implements the gRPC PaymentService defined in the Protobuf schema.
// It translates between the gRPC message format and the domain layer's native
// types, ensuring that no gRPC-specific concerns leak into the domain. All
// error responses use gRPC status codes mapped from domain error types.
type Handler struct {
        paymentService *services.PaymentService
        logger         *slog.Logger
        // UnimplementedPaymentServiceServer would be embedded here in a real
        // implementation with generated proto stubs. For the hexagonal scaffold,
        // we define the RPC methods directly.
}

// NewHandler creates a new gRPC handler with its required dependencies.
func NewHandler(paymentService *services.PaymentService, logger *slog.Logger) *Handler {
        return &Handler{
                paymentService: paymentService,
                logger:         logger,
        }
}

// ProcessPayment handles the gRPC ProcessPayment RPC. It validates the request,
// maps it to a domain command, delegates to the payment service, and maps the
// result back to a gRPC response. Idempotency is enforced through the
// idempotency_key field in the request message.
func (h *Handler) ProcessPayment(ctx context.Context, req *ProcessPaymentRequest) (*ProcessPaymentResponse, error) {
        h.logger.InfoContext(ctx, "gRPC ProcessPayment", "order_id", req.OrderId)

        // Map gRPC request to domain command.
        amount := models.NewMoneyFromCents(req.AmountCents, req.Currency)
        method := mapPaymentMethod(req.Method)

        cmd := services.ProcessPaymentCommand{
                OrderID:        req.OrderId,
                Amount:         amount,
                Method:         method,
                CustomerID:     req.CustomerId,
                IdempotencyKey: req.IdempotencyKey,
        }

        payment, err := h.paymentService.ProcessPayment(ctx, cmd)
        if err != nil {
                h.logger.ErrorContext(ctx, "payment processing failed", "error", err)
                return nil, mapDomainError(err)
        }

        // Map domain payment to gRPC response.
        return &ProcessPaymentResponse{
                PaymentId:    payment.ID,
                OrderId:      payment.OrderID,
                Status:       string(payment.Status),
                GatewayTxnId: payment.GatewayTxnID,
                CreatedAt:    payment.CreatedAt.Unix(),
        }, nil
}

// RefundPayment handles the gRPC RefundPayment RPC.
func (h *Handler) RefundPayment(ctx context.Context, req *RefundPaymentRequest) (*RefundPaymentResponse, error) {
        h.logger.InfoContext(ctx, "gRPC RefundPayment", "payment_id", req.PaymentId)

        amount := models.NewMoneyFromCents(req.RefundAmountCents, req.Currency)
        reason := mapRefundReason(req.Reason)

        cmd := services.RefundPaymentCommand{
                PaymentID:      req.PaymentId,
                Amount:         amount,
                Reason:         reason,
                IdempotencyKey: req.IdempotencyKey,
        }

        refund, err := h.paymentService.RefundPaymentCmd(ctx, cmd)
        if err != nil {
                return nil, mapDomainError(err)
        }

        return &RefundPaymentResponse{
                RefundId:        refund.ID,
                PaymentId:       refund.PaymentID,
                Status:          string(refund.Status),
                GatewayRefundId: refund.GatewayRefundID,
        }, nil
}

// GetTransaction handles the gRPC GetTransaction RPC.
func (h *Handler) GetTransaction(ctx context.Context, req *GetTransactionRequest) (*GetTransactionResponse, error) {
        payment, err := h.paymentService.GetTransaction(ctx, req.PaymentId)
        if err != nil {
                return nil, mapDomainError(err)
        }

        return &GetTransactionResponse{
                PaymentId:    payment.ID,
                OrderId:      payment.OrderID,
                Status:       string(payment.Status),
                AmountCents:  payment.Amount.Amount,
                Currency:     payment.Amount.Currency,
                GatewayTxnId: payment.GatewayTxnID,
                CreatedAt:    payment.CreatedAt.Unix(),
        }, nil
}

// ListTransactions handles the gRPC ListTransactions RPC.
func (h *Handler) ListTransactions(ctx context.Context, req *ListTransactionsRequest) (*ListTransactionsResponse, error) {
        // ListTransactions is not yet implemented on the PaymentService
        return nil, status.Errorf(codes.Unimplemented, "ListTransactions not yet implemented")
}

// GetCircuitStatus handles the gRPC GetCircuitStatus RPC.
func (h *Handler) GetCircuitStatus(ctx context.Context, req *GetCircuitStatusRequest) (*GetCircuitStatusResponse, error) {
        info, err := h.paymentService.GetCircuitStatus(ctx)
        _ = info // suppress unused warning
        if err != nil {
                return nil, mapDomainError(err)
        }

        return &GetCircuitStatusResponse{
                CircuitName:   info.Name,
                State:         string(info.State),
                FailureCount:  int32(info.FailureCount),
                SuccessCount:  int32(info.SuccessCount),
        }, nil
}

// mapPaymentMethod converts a gRPC payment method enum to a domain PaymentMethod.
func mapPaymentMethod(method string) models.PaymentMethod {
        switch method {
        case "CREDIT_CARD":
                return models.PaymentMethodCreditCard
        case "DEBIT_CARD":
                return models.PaymentMethodDebitCard
        case "BANK_TRANSFER":
                return models.PaymentMethodBankTransfer
        case "DIGITAL_WALLET":
                return models.PaymentMethodDigitalWallet
        case "CRYPTO":
                return models.PaymentMethodCrypto
        default:
                return models.PaymentMethodCreditCard
        }
}

// mapRefundReason converts a gRPC refund reason to a domain RefundReason.
func mapRefundReason(reason string) models.RefundReason {
        switch reason {
        case "CUSTOMER_REQUEST":
                return models.RefundReasonCustomerRequest
        case "PRODUCT_DEFECT":
                return models.RefundReasonProductDefect
        case "FRAUD":
                return models.RefundReasonFraud
        case "DUPLICATE":
                return models.RefundReasonDuplicate
        case "ADMIN_DECISION":
                return models.RefundReasonAdminDecision
        default:
                return models.RefundReasonCustomerRequest
        }
}

// mapDomainError maps domain errors to appropriate gRPC status codes.
// This ensures that clients receive meaningful error codes that map
// correctly to HTTP status codes via grpc-gateway.
func mapDomainError(err error) error {
        switch err.(type) {
        case models.ErrInvalidTransition:
                return status.Errorf(codes.FailedPrecondition, "%s", err.Error())
        default:
                return status.Errorf(codes.Internal, "%s", err.Error())
        }
}

// gRPC message types (would be generated from proto in production).
// Defined here for the hexagonal scaffold.

type ProcessPaymentRequest struct {
        OrderId        string `json:"order_id"`
        AmountCents    int64  `json:"amount_cents"`
        Currency       string `json:"currency"`
        Method         string `json:"method"`
        CustomerId     string `json:"customer_id"`
        IdempotencyKey string `json:"idempotency_key"`
}

type ProcessPaymentResponse struct {
        PaymentId    string `json:"payment_id"`
        OrderId      string `json:"order_id"`
        Status       string `json:"status"`
        GatewayTxnId string `json:"gateway_txn_id"`
        CreatedAt    int64  `json:"created_at"`
}

type RefundPaymentRequest struct {
        PaymentId         string `json:"payment_id"`
        RefundAmountCents int64  `json:"refund_amount_cents"`
        Currency          string `json:"currency"`
        Reason            string `json:"reason"`
        IdempotencyKey    string `json:"idempotency_key"`
}

type RefundPaymentResponse struct {
        RefundId        string `json:"refund_id"`
        PaymentId       string `json:"payment_id"`
        Status          string `json:"status"`
        GatewayRefundId string `json:"gateway_refund_id"`
}

type GetTransactionRequest struct {
        PaymentId string `json:"payment_id"`
}

type GetTransactionResponse struct {
        PaymentId    string `json:"payment_id"`
        OrderId      string `json:"order_id"`
        Status       string `json:"status"`
        AmountCents  int64  `json:"amount_cents"`
        Currency     string `json:"currency"`
        GatewayTxnId string `json:"gateway_txn_id"`
        CreatedAt    int64  `json:"created_at"`
}

type ListTransactionsRequest struct {
        CustomerId string `json:"customer_id"`
        Status     string `json:"status"`
        Cursor     string `json:"cursor"`
        PageSize   int32  `json:"page_size"`
}

type ListTransactionsResponse struct {
        Transactions []*TransactionItem `json:"transactions"`
        NextCursor   string             `json:"next_cursor"`
}

type TransactionItem struct {
        PaymentId   string `json:"payment_id"`
        OrderId     string `json:"order_id"`
        Status      string `json:"status"`
        AmountCents int64  `json:"amount_cents"`
        Currency    string `json:"currency"`
        CreatedAt   int64  `json:"created_at"`
}

type GetCircuitStatusRequest struct {
        CircuitName string `json:"circuit_name"`
}

type GetCircuitStatusResponse struct {
        CircuitName  string `json:"circuit_name"`
        State        string `json:"state"`
        FailureCount int32  `json:"failure_count"`
        SuccessCount int32  `json:"success_count"`
}
