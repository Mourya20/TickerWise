import type {
  InstrumentDetailResponse,
  InstrumentSearchResult,
  PriceBar,
  ProviderStatusResponse,
  ShareCountHistory,
} from '../types/instrument';

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';

export function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (typeof envUrl === 'string' && envUrl.trim().length > 0) {
    return envUrl.trim().replace(/\/+$/, '');
  }
  return DEFAULT_BASE_URL;
}

export class ApiRequestError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorDetail = `Request failed with status ${response.status}`;
    try {
      const errorJson = await response.json();
      if (errorJson && typeof errorJson.detail === 'string') {
        errorDetail = errorJson.detail;
      } else if (errorJson && Array.isArray(errorJson.detail)) {
        // FastAPI validation errors format
        errorDetail = errorJson.detail
          .map((item: { msg?: string }) => item.msg || JSON.stringify(item))
          .join(', ');
      }
    } catch {
      // Non-JSON error body or connection error
      const text = await response.text().catch(() => '');
      if (text.trim()) {
        errorDetail = text.slice(0, 150);
      }
    }
    throw new ApiRequestError(errorDetail, response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiRequestError(
      'Received malformed response from server.',
      response.status
    );
  }
}

export async function checkHealth(signal?: AbortSignal): Promise<{ status: string }> {
  const baseUrl = getApiBaseUrl();
  try {
    const response = await fetch(`${baseUrl}/health`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<{ status: string }>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiRequestError('Unable to connect to the backend server. Please verify it is running.');
  }
}

export async function getProviderStatus(signal?: AbortSignal): Promise<ProviderStatusResponse> {
  const baseUrl = getApiBaseUrl();
  try {
    const response = await fetch(`${baseUrl}/api/v1/providers/status`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<ProviderStatusResponse>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiRequestError('Unable to retrieve provider status from backend.');
  }
}

export async function searchInstruments(
  query: string,
  limit: number = 20,
  offset: number = 0,
  signal?: AbortSignal
): Promise<InstrumentSearchResult[]> {
  const trimmed = query.trim();
  if (!trimmed) {
    throw new ApiRequestError('Query must contain non-whitespace text.', 400);
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams({
    query: trimmed,
    limit: String(Math.max(1, Math.min(100, limit))),
    offset: String(Math.max(0, offset)),
  });

  const url = `${baseUrl}/api/v1/instruments?${params.toString()}`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<InstrumentSearchResult[]>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiRequestError(
      'Unable to connect to the backend server. Please check your network or server connection.'
    );
  }
}

export async function getInstrumentDetail(
  instrumentId: number,
  signal?: AbortSignal
): Promise<InstrumentDetailResponse> {
  if (!Number.isInteger(instrumentId) || instrumentId <= 0) {
    throw new ApiRequestError('Invalid instrument ID.', 400);
  }

  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/instruments/${instrumentId}`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<InstrumentDetailResponse>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiRequestError(
      'Unable to load instrument details. Please check your network or server connection.'
    );
  }
}

export async function getInstrumentPrices(
  instrumentId: number,
  fromDate?: string,
  toDate?: string,
  limit: number = 500,
  signal?: AbortSignal
): Promise<PriceBar[]> {
  if (!Number.isInteger(instrumentId) || instrumentId <= 0) {
    throw new ApiRequestError('Invalid instrument ID.', 400);
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (fromDate) params.set('from', fromDate);
  if (toDate) params.set('to', toDate);
  if (limit) params.set('limit', String(limit));

  const queryStr = params.toString();
  const url = `${baseUrl}/api/v1/instruments/${instrumentId}/prices${queryStr ? `?${queryStr}` : ''}`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<PriceBar[]>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiRequestError(
      'Unable to load historical price data. Please check your network or server connection.'
    );
  }
}

export async function getInstrumentShareCounts(
  instrumentId: number,
  signal?: AbortSignal
): Promise<ShareCountHistory[]> {
  if (!Number.isInteger(instrumentId) || instrumentId <= 0) {
    throw new ApiRequestError('Invalid instrument ID.', 400);
  }

  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/instruments/${instrumentId}/share-counts`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<ShareCountHistory[]>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiRequestError(
      'Unable to load share count history. Please check your network or server connection.'
    );
  }
}

