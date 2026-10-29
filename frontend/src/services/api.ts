import type {
  CorporateAction,
  CorporateActionSyncStatusResponse,
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
  limit: number = 1000,
  offset: number = 0,
  arg6?: AbortSignal | boolean,
  arg7?: AbortSignal
): Promise<PriceBar[]> {
  if (!Number.isInteger(instrumentId) || instrumentId <= 0) {
    throw new ApiRequestError('Invalid instrument ID.', 400);
  }

  let abortSignal: AbortSignal | undefined = undefined;
  let autoBackfill: boolean = false;

  if (typeof arg6 === 'boolean') {
    autoBackfill = arg6;
    abortSignal = arg7;
  } else if (arg6 && typeof (arg6 as AbortSignal).aborted === 'boolean') {
    abortSignal = arg6 as AbortSignal;
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (fromDate) params.set('from', fromDate);
  if (toDate) params.set('to', toDate);
  if (limit) params.set('limit', String(limit));
  if (offset !== undefined && offset !== null) params.set('offset', String(offset));
  if (autoBackfill) params.set('auto_backfill', 'true');

  const queryStr = params.toString();
  const url = `${baseUrl}/api/v1/instruments/${instrumentId}/prices${queryStr ? `?${queryStr}` : ''}`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: abortSignal,
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

/**
 * Fetches the complete price history for an instrument over the requested range,
 * paginating automatically through subsequent 1,000-row pages until exhausted.
 * Deduplicates by trading date and returns ascending chronological bars.
 */
export async function fetchAllInstrumentPrices(
  instrumentId: number,
  fromDate?: string,
  toDate?: string,
  pageSize: number = 1000,
  arg5?: AbortSignal | boolean,
  arg6?: AbortSignal
): Promise<PriceBar[]> {
  let abortSignal: AbortSignal | undefined = undefined;

  if (typeof arg5 === 'boolean') {
    abortSignal = arg6;
  } else if (arg5 && typeof (arg5 as AbortSignal).aborted === 'boolean') {
    abortSignal = arg5 as AbortSignal;
  }

  const barsMap = new Map<string, PriceBar>();
  let currentOffset = 0;
  const maxPages = 50; // Safety cap: 50 pages * 1,000 = 50,000 trading sessions

  for (let page = 0; page < maxPages; page++) {
    if (abortSignal?.aborted) {
      throw new DOMException('Price history fetch was cancelled.', 'AbortError');
    }

    const pageBars = await getInstrumentPrices(
      instrumentId,
      fromDate,
      toDate,
      pageSize,
      currentOffset,
      abortSignal
    );

    if (!pageBars || pageBars.length === 0) {
      break;
    }

    for (const bar of pageBars) {
      barsMap.set(bar.trading_date, bar);
    }

    if (pageBars.length < pageSize) {
      break;
    }

    currentOffset += pageSize;
  }

  // Sort ascending chronologically
  return Array.from(barsMap.values()).sort((a, b) =>
    a.trading_date.localeCompare(b.trading_date)
  );
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

export async function getInstrumentCorporateActions(
  instrumentId: number,
  signal?: AbortSignal
): Promise<CorporateAction[]> {
  if (!Number.isInteger(instrumentId) || instrumentId <= 0) {
    throw new ApiRequestError('Invalid instrument ID.', 400);
  }

  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/instruments/${instrumentId}/corporate-actions`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<CorporateAction[]>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiRequestError(
      'Unable to load corporate actions. Please check your network or server connection.'
    );
  }
}

export async function getInstrumentCorporateActionsStatus(
  instrumentId: number,
  signal?: AbortSignal
): Promise<CorporateActionSyncStatusResponse> {
  if (!Number.isInteger(instrumentId) || instrumentId <= 0) {
    throw new ApiRequestError('Invalid instrument ID.', 400);
  }

  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/instruments/${instrumentId}/corporate-actions/status`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<CorporateActionSyncStatusResponse>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiRequestError(
      'Unable to load corporate actions synchronization status. Please check your network or server connection.'
    );
  }
}

export async function backfillInstrumentPrices(
  instrumentId: number,
  fromDate?: string,
  toDate?: string,
  signal?: AbortSignal
): Promise<{ status: string; symbol: string; bars_read: number; bars_inserted: number }> {
  if (!Number.isInteger(instrumentId) || instrumentId <= 0) {
    throw new ApiRequestError('Invalid instrument ID.', 400);
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (fromDate) params.set('from', fromDate);
  if (toDate) params.set('to', toDate);
  const queryStr = params.toString();
  const url = `${baseUrl}/api/v1/instruments/${instrumentId}/prices/backfill${queryStr ? `?${queryStr}` : ''}`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiRequestError('Unable to backfill historical prices. Please check your network or server connection.');
  }
}

export async function syncInstrumentCorporateActions(
  instrumentId: number,
  signal?: AbortSignal
): Promise<CorporateActionSyncStatusResponse> {
  if (!Number.isInteger(instrumentId) || instrumentId <= 0) {
    throw new ApiRequestError('Invalid instrument ID.', 400);
  }

  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/instruments/${instrumentId}/corporate-actions/sync`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      signal,
    });
    return await handleResponse<CorporateActionSyncStatusResponse>(response);
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiRequestError('Unable to synchronize corporate actions. Please check your network or server connection.');
  }
}



