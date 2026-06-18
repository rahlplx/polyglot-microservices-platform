package grpc

import (
	"errors"
	"testing"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/domain/models"
)

func TestMapDomainError_InformationLeakage(t *testing.T) {
	internalErr := errors.New("sensitive database connection error: password=secret")

	t.Run("Internal error does not leak details", func(t *testing.T) {
		err := mapDomainError(internalErr)
		st, ok := status.FromError(err)
		if !ok {
			t.Fatalf("expected gRPC status error, got %T", err)
		}

		if st.Code() != codes.Internal {
			t.Errorf("expected code %v, got %v", codes.Internal, st.Code())
		}

		if st.Message() == internalErr.Error() {
			t.Errorf("leaked sensitive error message: %q", st.Message())
		}

		expected := "an internal error occurred during payment processing"
		if st.Message() != expected {
			t.Errorf("expected message %q, got %q", expected, st.Message())
		}
	})

	t.Run("ErrInvalidTransition includes error details", func(t *testing.T) {
		transitionErr := models.ErrInvalidTransition{
			From: models.PaymentStatusCompleted,
			To:   models.PaymentStatusPending,
		}

		err := mapDomainError(transitionErr)
		st, ok := status.FromError(err)
		if !ok {
			t.Fatalf("expected gRPC status error, got %T", err)
		}

		if st.Code() != codes.FailedPrecondition {
			t.Errorf("expected code %v, got %v", codes.FailedPrecondition, st.Code())
		}

		if st.Message() != "invalid payment state transition: " + transitionErr.Error() {
			t.Errorf("expected message to contain transition details, got %q", st.Message())
		}
	})
}
