/**
 * Axios API client with silent JWT refresh + 401 request queue.
 */

import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";

import {
  clearAuthTokens,
  getAccessToken,
  getRefreshToken,
  redirectToLoginExpired,
  setTokenPair,
} from "@/lib/auth/tokens";
import { buildApiUrl } from "@/lib/api/baseUrl";

type QueueItem = {
  resolve: (token: string | null) => void;
  reject: (error: unknown) => void;
};

let isRefreshing = false;
let failedQueue: QueueItem[] = [];

function processQueue(error: unknown, token: string | null = null): void {
  failedQueue.forEach((item) => {
    if (error) {
      item.reject(error);
    } else {
      item.resolve(token);
    }
  });
  failedQueue = [];
}

function attachBearer(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const accessToken = getAccessToken();
  if (accessToken && !config.headers.get("Authorization")) {
    config.headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const isFormData =
    typeof FormData !== "undefined" && config.data instanceof FormData;
  if (isFormData) {
    // Browser must set multipart boundary; a JSON Content-Type breaks FormData.
    config.headers.delete("Content-Type");
  } else if (!config.headers.has("Content-Type") && config.data) {
    config.headers.set("Content-Type", "application/json");
  }
  return config;
}

export interface TokenPairResponse {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in?: number;
  company_id?: string | null;
  role?: string | null;
}

async function refreshAccessToken(): Promise<string> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new Error("Missing refresh token");
  }

  // Use plain axios (no interceptors) to avoid recursive 401 handling.
  const response = await axios.post<TokenPairResponse>(
    buildApiUrl("/api/v1/auth/refresh"),
    { refresh_token: refreshToken },
    {
      headers: { "Content-Type": "application/json" },
      timeout: 20000,
    },
  );

  const data = response.data;
  setTokenPair({
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    expiresIn: data.expires_in ?? 60 * 60 * 24 * 7,
  });
  return data.access_token;
}

function attachAuthInterceptor(instance: AxiosInstance): void {
  instance.interceptors.request.use((config: InternalAxiosRequestConfig) => attachBearer(config));

  instance.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
      const original = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined;
      const status = error.response?.status;

      if (!original || status !== 401 || original._retry) {
        return Promise.reject(error);
      }

      // Never try to refresh the refresh call itself.
      const url = original.url || "";
      if (url.includes("/auth/refresh") || url.includes("/auth/login")) {
        return Promise.reject(error);
      }

      // Impersonation sessions don't use refresh tokens — surface 401 as-is.
      const access = getAccessToken();
      if (access?.startsWith("imp_") || !getRefreshToken()) {
        return Promise.reject(error);
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({
            resolve: (token: string | null) => {
              if (!token) {
                reject(error);
                return;
              }
              original.headers = {
                ...original.headers,
                Authorization: `Bearer ${token}`,
              };
              resolve(instance(original));
            },
            reject,
          });
        });
      }

      original._retry = true;
      isRefreshing = true;

      try {
        const newToken = await refreshAccessToken();
        processQueue(null, newToken);
        original.headers = {
          ...original.headers,
          Authorization: `Bearer ${newToken}`,
        };
        return instance(original);
      } catch (refreshError) {
        processQueue(refreshError, null);
        clearAuthTokens();
        redirectToLoginExpired();
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    },
  );
}

export const apiClient: AxiosInstance = axios.create({
  timeout: 60000,
});

attachAuthInterceptor(apiClient);

/**
 * Fetch-compatible helper used by existing `apiRequest` wrappers.
 * Shares the same axios instance (and thus the refresh queue).
 */
export async function apiClientRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  let data: unknown = undefined;
  if (options.body != null) {
    data =
      typeof options.body === "string"
        ? (() => {
            try {
              return JSON.parse(options.body as string);
            } catch {
              return options.body;
            }
          })()
        : options.body;
  }

  const headers: Record<string, string> = {};
  if (options.headers) {
    const h = new Headers(options.headers);
    h.forEach((value, key) => {
      headers[key] = value;
    });
  }

  try {
    const response = await apiClient.request<T>({
      url: buildApiUrl(path),
      method,
      data: method === "GET" || method === "HEAD" ? undefined : data,
      headers,
    });
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status ?? 0;
      const body = (error.response?.data ?? undefined) as
        | {
            detail?: unknown;
            message?: string;
            error?: string;
            code?: string;
            fields?: Array<{ field?: string; message?: string }>;
          }
        | undefined;

      let message =
        (typeof body?.detail === "string" && body.detail.trim() && body.detail) ||
        (typeof body?.message === "string" && body.message) ||
        (typeof body?.error === "string" && body.error) ||
        (error.message.includes("Network Error")
          ? "Cannot reach API. Ensure the backend is running and Next.js rewrites are active."
          : `Request failed (${status || "network"})`);

      if (
        body?.code === "VALIDATION_ERROR" &&
        Array.isArray(body.fields) &&
        body.fields.length > 0
      ) {
        const fieldText = body.fields
          .map((item) =>
            item.field ? `${item.field}: ${item.message || "invalid"}` : item.message || "",
          )
          .filter(Boolean)
          .join("; ");
        if (fieldText) {
          message = typeof body.detail === "string" && body.detail.trim()
            ? `${body.detail}: ${fieldText}`
            : fieldText;
        }
      }

      const err = new Error(message) as Error & { status: number; body?: unknown };
      err.status = status;
      err.body = body;
      throw err;
    }
    throw error;
  }
}

export { isRefreshing as __isRefreshingForTests };
