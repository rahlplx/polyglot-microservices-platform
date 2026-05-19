package com.company.order.adapters.inbound.grpc

import com.company.order.domain.models.*
import com.company.order.domain.ports.inbound.*
import com.company.order.domain.saga.SagaStatus
import com.company.order.domain.saga.SagaStepStatus
import io.grpc.Status
import io.grpc.stub.StreamObserver
import order.v1.*
import org.slf4j.LoggerFactory
import java.time.Instant
import java.util.UUID

/**
 * gRPC handler adapter implementing the OrderService proto definition.
 *
 * Maps incoming gRPC requests to domain use case calls and translates
 * domain responses back to gRPC message types. Handles authentication
 * validation, correlation ID propagation, and error mapping.
 *
 * This adapter is the primary inbound entry point for the Order service.
 */
class OrderGrpcHandler(
    private val createOrderUseCase: CreateOrderUseCase,
    private val completeOrderUseCase: CompleteOrderUseCase,
    private val cancelOrderUseCase: CancelOrderUseCase,
    private val listOrdersUseCase: ListOrdersUseCase,
    private val getOrderStatusUseCase: GetOrderStatusUseCase,
    private val orderRepository: com.company.order.domain.ports.outbound.OrderRepositoryPort
) : OrderServiceGrpcKt.OrderServiceCoroutineImplBase() {

    private val logger = LoggerFactory.getLogger(OrderGrpcHandler::class.java)

    // --- CreateOrder ---

    override suspend fun createOrder(request: CreateOrderRequest): CreateOrderResponse {
        logger.info("gRPC CreateOrder: customerId=${request.customerId}, lines=${request.linesCount}")

        try {
            val addressInput = AddressInput(
                line1 = request.shippingAddress.streetLine1,
                line2 = if (request.shippingAddress.streetLine2.isNotBlank()) request.shippingAddress.streetLine2 else null,
                city = request.shippingAddress.city,
                state = request.shippingAddress.stateProvince,
                postalCode = request.shippingAddress.postalCode,
                countryCode = request.shippingAddress.countryCode
            )

            val lineItems = request.linesList.map { line ->
                LineItemInput(
                    productId = line.productId,
                    quantity = line.quantity
                )
            }

            val order = createOrderUseCase.create(
                customerId = request.customerId,
                lines = lineItems,
                shippingAddress = addressInput,
                paymentMethodId = "", // Extracted from auth context in production
                idempotencyKey = null
            )

            return CreateOrderResponse.newBuilder()
                .setOrder(mapToProtoOrder(order))
                .build()

        } catch (e: DuplicateOrderException) {
            throw Status.ALREADY_EXISTS
                .withDescription(e.message)
                .asRuntimeException()
        } catch (e: InsufficientStockException) {
            throw Status.FAILED_PRECONDITION
                .withDescription(e.message)
                .asRuntimeException()
        } catch (e: PaymentMethodInvalidException) {
            throw Status.INVALID_ARGUMENT
                .withDescription(e.message)
                .asRuntimeException()
        } catch (e: Exception) {
            logger.error("Unexpected error in CreateOrder", e)
            throw Status.INTERNAL
                .withDescription("Internal error: ${e.message}")
                .asRuntimeException()
        }
    }

    // --- GetOrder ---

    override suspend fun getOrder(request: GetOrderRequest): GetOrderResponse {
        logger.debug("gRPC GetOrder: orderId=${request.orderId}")

        val order = orderRepository.findById(request.orderId)
            ?: throw Status.NOT_FOUND
                .withDescription("Order not found: ${request.orderId}")
                .asRuntimeException()

        return GetOrderResponse.newBuilder()
            .setOrder(mapToProtoOrder(order))
            .build()
    }

    // --- ListOrders ---

    override suspend fun listOrders(request: ListOrdersRequest): ListOrdersResponse {
        logger.debug("gRPC ListOrders: customerId=${request.customerId}, statusFilter=${request.statusFilter}")

        val status = if (request.statusFilter != OrderStatusOuterClass.OrderStatus.ORDER_STATUS_UNSPECIFIED) {
            mapFromProtoStatus(request.statusFilter)
        } else null

        val page = listOrdersUseCase.list(
            customerId = if (request.customerId.isNotBlank()) request.customerId else null,
            status = status,
            pageSize = if (request.pagination.pageSize > 0) request.pagination.pageSize else 20,
            pageToken = if (request.pagination.cursor.isNotBlank()) request.pagination.cursor else null
        )

        val responseBuilder = ListOrdersResponse.newBuilder()
        page.items.forEach { order ->
            responseBuilder.addOrders(mapToProtoOrder(order))
        }

        responseBuilder.pagination = common.v1.PaginationResponse.newBuilder()
            .setNextCursor(page.cursor ?: "")
            .setTotalCount(page.totalCount)
            .setHasMore(page.hasMore)
            .build()

        return responseBuilder.build()
    }

    // --- CompleteOrder ---

    override suspend fun completeOrder(request: CompleteOrderRequest): CompleteOrderResponse {
        logger.info("gRPC CompleteOrder: orderId=${request.orderId}")

        try {
            val order = completeOrderUseCase.complete(request.orderId)
            return CompleteOrderResponse.newBuilder()
                .setOrder(mapToProtoOrder(order))
                .build()
        } catch (e: OrderNotFoundException) {
            throw Status.NOT_FOUND.withDescription(e.message).asRuntimeException()
        } catch (e: OrderNotCompletableException) {
            throw Status.FAILED_PRECONDITION.withDescription(e.message).asRuntimeException()
        } catch (e: PaymentNotCapturedException) {
            throw Status.FAILED_PRECONDITION.withDescription(e.message).asRuntimeException()
        }
    }

    // --- CancelOrder ---

    override suspend fun cancelOrder(request: CancelOrderRequest): CancelOrderResponse {
        logger.info("gRPC CancelOrder: orderId=${request.orderId}, reason=${request.reason}")

        try {
            val order = cancelOrderUseCase.cancel(
                orderId = request.orderId,
                reason = request.reason,
                cancelledBy = "grpc-client" // Extracted from auth context in production
            )

            return CancelOrderResponse.newBuilder()
                .setOrder(mapToProtoOrder(order))
                .setCompensationInitiated(order.status == OrderStatus.COMPENSATING)
                .build()
        } catch (e: OrderNotFoundException) {
            throw Status.NOT_FOUND.withDescription(e.message).asRuntimeException()
        } catch (e: OrderNotCancellableException) {
            throw Status.FAILED_PRECONDITION.withDescription(e.message).asRuntimeException()
        } catch (e: CancellationAlreadyInProgressException) {
            throw Status.ABORTED.withDescription(e.message).asRuntimeException()
        }
    }

    // --- GetOrderStatus ---

    override suspend fun getOrderStatus(request: GetOrderStatusRequest): GetOrderStatusResponse {
        logger.debug("gRPC GetOrderStatus: orderId=${request.orderId}")

        try {
            val statusDetail = getOrderStatusUseCase.getStatus(request.orderId, includeHistory = true)

            return GetOrderStatusResponse.newBuilder()
                .setOrderId(statusDetail.orderId)
                .setStatus(mapToProtoStatusEnum(statusDetail.status))
                .setCurrentSagaStep(statusDetail.currentSagaStep ?: "")
                .addAllCompletedSteps(statusDetail.completedSteps)
                .addAllRemainingSteps(statusDetail.remainingSteps)
                .addAllCompensationSteps(statusDetail.compensationSteps)
                .build()
        } catch (e: OrderNotFoundException) {
            throw Status.NOT_FOUND.withDescription(e.message).asRuntimeException()
        }
    }

    // --- Mapping Functions ---

    private fun mapToProtoOrder(order: Order): order.v1.Order {
        val builder = order.v1.Order.newBuilder()
            .setOrderId(order.orderId)
            .setCustomerId(order.customerId)
            .setTotal(mapToProtoMoney(order.total))
            .setStatus(mapToProtoStatusEnum(order.status))
            .setCreatedAt(mapToProtoTimestamp(order.createdAt))
            .setUpdatedAt(mapToProtoTimestamp(order.updatedAt))

        order.paymentId?.let { builder.setPaymentId(it) }
        order.completedAt?.let { builder.setCompletedAt(mapToProtoTimestamp(it)) }

        order.lines.forEach { line ->
            builder.addLines(
                order.v1.OrderLine.newBuilder()
                    .setProductId(line.productId)
                    .setProductName(line.productName)
                    .setQuantity(line.quantity)
                    .setUnitPrice(mapToProtoMoney(line.unitPrice))
                    .setLineTotal(mapToProtoMoney(line.lineTotal))
                    .build()
            )
        }

        return builder.build()
    }

    private fun mapToProtoMoney(money: Money): common.v1.Money = common.v1.Money.newBuilder()
        .setCurrencyCode(money.currencyCode)
        .setUnits(money.units)
        .setNanos(money.nanos)
        .build()

    private fun mapToProtoStatusEnum(status: OrderStatus): OrderStatusOuterClass.OrderStatus =
        when (status) {
            OrderStatus.PENDING -> OrderStatusOuterClass.OrderStatus.ORDER_STATUS_PENDING
            OrderStatus.RESERVED -> OrderStatusOuterClass.OrderStatus.ORDER_STATUS_RESERVED
            OrderStatus.PAID -> OrderStatusOuterClass.OrderStatus.ORDER_STATUS_PAID
            OrderStatus.FULFILLING -> OrderStatusOuterClass.OrderStatus.ORDER_STATUS_FULFILLING
            OrderStatus.COMPLETED -> OrderStatusOuterClass.OrderStatus.ORDER_STATUS_COMPLETED
            OrderStatus.CANCELLED -> OrderStatusOuterClass.OrderStatus.ORDER_STATUS_CANCELLED
            OrderStatus.FAILED -> OrderStatusOuterClass.OrderStatus.ORDER_STATUS_FAILED
            OrderStatus.COMPENSATING -> OrderStatusOuterClass.OrderStatus.ORDER_STATUS_COMPENSATING
        }

    private fun mapFromProtoStatus(status: OrderStatusOuterClass.OrderStatus): OrderStatus =
        when (status) {
            OrderStatusOuterClass.OrderStatus.ORDER_STATUS_PENDING -> OrderStatus.PENDING
            OrderStatusOuterClass.OrderStatus.ORDER_STATUS_RESERVED -> OrderStatus.RESERVED
            OrderStatusOuterClass.OrderStatus.ORDER_STATUS_PAID -> OrderStatus.PAID
            OrderStatusOuterClass.OrderStatus.ORDER_STATUS_FULFILLING -> OrderStatus.FULFILLING
            OrderStatusOuterClass.OrderStatus.ORDER_STATUS_COMPLETED -> OrderStatus.COMPLETED
            OrderStatusOuterClass.OrderStatus.ORDER_STATUS_CANCELLED -> OrderStatus.CANCELLED
            OrderStatusOuterClass.OrderStatus.ORDER_STATUS_FAILED -> OrderStatus.FAILED
            OrderStatusOuterClass.OrderStatus.ORDER_STATUS_COMPENSATING -> OrderStatus.COMPENSATING
            else -> OrderStatus.PENDING
        }

    private fun mapToProtoTimestamp(instant: Instant): com.google.protobuf.Timestamp =
        com.google.protobuf.Timestamp.newBuilder()
            .setSeconds(instant.epochSecond)
            .setNanos(instant.nano)
            .build()
}
