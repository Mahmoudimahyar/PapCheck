/** Shared base URL and error type of the RefCheck API client (lib/api.ts re-exports the calls). */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export class APIError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
