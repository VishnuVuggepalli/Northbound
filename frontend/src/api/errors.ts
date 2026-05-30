/**
 * Typed transport error surfaced by the real client. TanStack Query carries
 * this through `error` so UI code can branch on `status` / `code` instead of
 * string-matching messages.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}
