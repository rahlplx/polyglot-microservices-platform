package com.company.order.domain.models

/**
 * Order status enum with state machine transitions.
 *
 * Happy path: PENDING → RESERVED → PAID → FULFILLING → COMPLETED
 * Failure paths: Any state → CANCELLED (via COMPENSATING if saga partial)
 *                PENDING → FAILED (before any saga step completes)
 *
 * Domain core has ZERO external dependencies.
 */
enum class OrderStatus {
    PENDING,       // Order created, awaiting processing
    RESERVED,      // Inventory reserved by catalog service
    PAID,          // Payment authorized and captured
    FULFILLING,    // Order being prepared for shipment
    COMPLETED,     // Order delivered and finalized
    CANCELLED,     // Order cancelled, all compensations applied
    FAILED,        // Order creation failed before any saga step completed
    COMPENSATING;  // Saga is executing compensation actions

    companion object {
        /**
         * Valid state transitions defined as a map from source status
         * to the set of allowed target statuses.
         */
        private val TRANSITIONS: Map<OrderStatus, Set<OrderStatus>> = mapOf(
            PENDING to setOf(RESERVED, FAILED, CANCELLED),
            RESERVED to setOf(PAID, CANCELLED, COMPENSATING),
            PAID to setOf(FULFILLING, CANCELLED, COMPENSATING),
            FULFILLING to setOf(COMPLETED, CANCELLED, COMPENSATING),
            COMPENSATING to setOf(CANCELLED, FAILED),
            COMPLETED to emptySet(),      // Terminal state
            CANCELLED to emptySet(),      // Terminal state
            FAILED to emptySet()          // Terminal state
        )

        /**
         * Check if a transition from [from] to [to] is valid.
         */
        fun canTransition(from: OrderStatus, to: OrderStatus): Boolean {
            return TRANSITIONS[from]?.contains(to) == true
        }

        /**
         * Validate and return the transition, or throw if invalid.
         */
        fun requireTransition(from: OrderStatus, to: OrderStatus) {
            require(canTransition(from, to)) {
                "Invalid state transition: $from → $to. Allowed transitions from $from: ${TRANSITIONS[from]}"
            }
        }

        /** Terminal states where no further transitions are possible */
        val TERMINAL_STATES: Set<OrderStatus> = setOf(COMPLETED, CANCELLED, FAILED)

        /** States from which an order can be cancelled */
        val CANCELLABLE_STATES: Set<OrderStatus> = setOf(PENDING, RESERVED, PAID, FULFILLING)
    }

    /** Whether this status allows further transitions */
    val isTerminal: Boolean get() = this in TERMINAL_STATES

    /** Whether an order in this status can be cancelled */
    val isCancellable: Boolean get() = this in CANCELLABLE_STATES
}
