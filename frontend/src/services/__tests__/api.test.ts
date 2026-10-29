import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  checkHealth,
  searchInstruments,
  getInstrumentDetail,
  fetchAllInstrumentPrices,
  getInstrumentCorporateActions,
  getInstrumentCorporateActionsStatus,
  ApiRequestError,
  getApiBaseUrl,
} from '../api';

describe('API Service Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('provides a valid default base URL', () => {
    const url = getApiBaseUrl();
    expect(url).toBeDefined();
    expect(url.startsWith('http')).toBe(true);
  });

  it('rejects empty and whitespace-only search queries client-side', async () => {
    await expect(searchInstruments('   ')).rejects.toThrow(ApiRequestError);
    await expect(searchInstruments('')).rejects.toThrow(
      'Query must contain non-whitespace text.'
    );
  });

  it('rejects invalid instrument IDs', async () => {
    await expect(getInstrumentDetail(-1)).rejects.toThrow(ApiRequestError);
    await expect(getInstrumentDetail(0)).rejects.toThrow('Invalid instrument ID.');
  });

  it('calls search endpoint with trimmed query and pagination params', async () => {
    const mockData = [
      {
        instrument_id: 2304,
        company_name: 'Tata Consultancy Services Limited',
        exchange: 'NSE',
        symbol: 'TCS',
        series: 'EQ',
        isin: 'INE467B01029',
        is_active: true,
      },
    ];

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await searchInstruments('  TCS  ', 20, 0);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const callUrl = fetchMock.mock.calls[0][0];
    expect(callUrl).toContain('query=TCS');
    expect(callUrl).toContain('limit=20');
    expect(callUrl).toContain('offset=0');
    expect(result).toEqual(mockData);
  });

  it('calls detail endpoint with instrument ID', async () => {
    const mockDetail = {
      instrument_id: 2304,
      company_id: 2301,
      company_name: 'Tata Consultancy Services Limited',
      exchange: 'NSE',
      symbol: 'TCS',
      series: 'EQ',
      instrument_type: 'EQUITY',
      isin: 'INE467B01029',
      listing_date: '2004-08-25',
      paid_up_value: '1.0000',
      market_lot: 1,
      face_value: '1.0000',
      is_active: true,
      snapshot: {
        snapshot_date: '2026-10-14',
        ltp: '2304.900000',
        percentage_change_pct: '2.110000',
        market_capitalization_crores: '833932.990000',
        volume_lakhs: '121.460000',
        traded_value_crores: '2805.170000',
      },
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockDetail),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await getInstrumentDetail(2304);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/instruments/2304');
    expect(result.symbol).toBe('TCS');
    expect(result.snapshot?.ltp).toBe('2304.900000');
  });

  it('handles backend 404 error responses with detail message', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ detail: 'Instrument not found.' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(getInstrumentDetail(999999)).rejects.toThrow('Instrument not found.');
  });

  it('handles network failure gracefully without unhandled crashes', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(searchInstruments('TCS')).rejects.toThrow(
      'Unable to connect to the backend server.'
    );
  });

  it('checks health endpoint successfully', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: 'ok' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const res = await checkHealth();
    expect(res).toEqual({ status: 'ok' });
  });

  it('paginates price history across multiple 1,000-bar pages and deduplicates', async () => {
    // Generate page 0 (1,000 bars from 2022-01-01)
    const page0 = Array.from({ length: 1000 }, (_, i) => ({
      trading_date: `2024-01-${String((i % 28) + 1).padStart(2, '0')}-${i}`,
      open: '100',
      high: '110',
      low: '90',
      close: '105',
    }));
    // Page 1 (250 bars)
    const page1 = Array.from({ length: 250 }, (_, i) => ({
      trading_date: `2020-01-${String((i % 28) + 1).padStart(2, '0')}-${i}`,
      open: '80',
      high: '85',
      low: '75',
      close: '82',
    }));

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(page0),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(page1),
      });
    vi.stubGlobal('fetch', fetchMock);

    const results = await fetchAllInstrumentPrices(1879, undefined, undefined, 1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Verify offset progression
    const call0 = fetchMock.mock.calls[0][0];
    const call1 = fetchMock.mock.calls[1][0];
    expect(call0).toContain('offset=0');
    expect(call1).toContain('offset=1000');

    // Total unique bars
    expect(results.length).toBe(1250);

    // Verify chronological ordering
    for (let i = 1; i < results.length; i++) {
      expect(results[i].trading_date >= results[i - 1].trading_date).toBe(true);
    }
  });

  it('respects AbortController cancellation during price pagination', async () => {
    const controller = new AbortController();
    controller.abort();

    await expect(
      fetchAllInstrumentPrices(1879, undefined, undefined, 1000, controller.signal)
    ).rejects.toThrow();
  });

  it('rejects invalid instrument IDs for corporate actions status', async () => {
    await expect(getInstrumentCorporateActionsStatus(-1)).rejects.toThrow(ApiRequestError);
    await expect(getInstrumentCorporateActionsStatus(0)).rejects.toThrow('Invalid instrument ID.');
  });

  it('fetches corporate actions status successfully with correct URL', async () => {
    const mockStatus = {
      instrument_id: 2304,
      symbol: 'TCS',
      status: 'synced',
      last_checked_at: '2026-10-29T10:00:00Z',
      last_success_at: '2026-10-29T10:00:00Z',
      events_count: 5,
      provider_name: 'TejHQ',
      error_message: null,
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockStatus),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await getInstrumentCorporateActionsStatus(2304);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/instruments/2304/corporate-actions/status');
    expect(result.status).toBe('synced');
    expect(result.events_count).toBe(5);
  });

  it('fetches corporate actions list successfully with correct URL', async () => {
    const mockActions = [
      {
        id: 1,
        instrument_id: 2304,
        symbol: 'TCS',
        event_type: 'dividend',
        ex_date: '2026-10-15',
        cash_amount: '12.00',
      },
    ];

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockActions),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await getInstrumentCorporateActions(2304);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/instruments/2304/corporate-actions');
    expect(result.length).toBe(1);
    expect(result[0].event_type).toBe('dividend');
  });
});

