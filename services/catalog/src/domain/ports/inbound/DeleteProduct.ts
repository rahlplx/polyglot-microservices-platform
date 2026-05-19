/**
 * DeleteProduct Use Case Port (Inbound)
 *
 * Defines the interface for deleting a product from the catalog,
 * supporting both soft-delete (mark as discontinued) and hard-delete
 * (permanent removal).
 * This is a driving port — adapters on the inbound side call this use case.
 *
 * Domain core has ZERO external dependencies.
 */
import type {
  DeleteReason,
  ProductNotFoundError,
  ProductHasActiveOrdersError,
  DeleteNotAuthorizedError,
} from '../../models';

export interface DeleteProductRequest {
  readonly productId: string;
  readonly reason: DeleteReason;
  readonly hardDelete: boolean;
  readonly replacementProductId?: string;
}

export interface DeleteProductResponse {
  readonly productId: string;
  readonly deleted: boolean;
  readonly hardDeleted: boolean;
  readonly replacementRedirect?: string;
  readonly deletedAt: Date;
}

export type DeleteProductError =
  | ProductNotFoundError
  | ProductHasActiveOrdersError
  | DeleteNotAuthorizedError;

export interface DeleteProduct {
  execute(request: DeleteProductRequest): Promise<DeleteProductResponse>;
}
