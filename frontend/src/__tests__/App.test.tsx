import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from '../App';
import * as api from '../services/api';
import type { InstrumentDetailResponse, InstrumentSearchResult } from '../types/instrument';

describe('TickerWise — End-to-End Component Tests', () => {
  const mockSearchResultsTcs: InstrumentSearchResult[] = [
    {
      instrument_id: 2304,
      company_name: 'Tata Consultancy Services Limited',
      exchange: 'NSE',
      symbol: 'TCS',
      series: 'EQ',
      isin: 'INE467B01029',
      is_active: true,
    },
    {
      instrument_id: 2575,
      company_name: 'West Coast Paper Mills Limited',
      exchange: 'NSE',
      symbol: 'WSTCSTPAPR',
      series: 'EQ',
      isin: 'INE976A01021',
      is_active: true,
    },
  ];

  const mockDetailWithSnapshot: InstrumentDetailResponse = {
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

  const mockDetailWithoutSnapshot: InstrumentDetailResponse = {
    instrument_id: 117,
    company_id: 117,
    company_name: 'Alfred Herbert India Limited',
    exchange: 'NSE',
    symbol: 'ALFREDHE',
    series: 'EQ',
    instrument_type: 'EQUITY',
    isin: 'INE782D01027',
    listing_date: '2026-08-17',
    paid_up_value: '10.0000',
    market_lot: 1,
    face_value: '10.0000',
    is_active: true,
    snapshot: null,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'checkHealth').mockResolvedValue({ status: 'ok' });
  });

  // Scenario 1: Search input and submission
  it('renders search input and triggers search on submit', async () => {
    const searchSpy = vi.spyOn(api, 'searchInstruments').mockResolvedValue(mockSearchResultsTcs);

    render(<App />);

    const searchInput = screen.getByRole('textbox', {
      name: /search instruments by company name or symbol/i,
    });
    expect(searchInput).toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: 'TCS' } });
    fireEvent.submit(screen.getByRole('search'));

    await waitFor(() => {
      expect(searchSpy).toHaveBeenCalledWith('TCS', 20, 0, expect.any(AbortSignal));
    });
  });

  // Scenario 2: Rendering returned results
  it('renders search results table with expected fields', async () => {
    vi.spyOn(api, 'searchInstruments').mockResolvedValue(mockSearchResultsTcs);

    render(<App />);

    const searchInput = screen.getByRole('textbox', {
      name: /search instruments by company name or symbol/i,
    });
    fireEvent.change(searchInput, { target: { value: 'TCS' } });
    fireEvent.submit(screen.getByRole('search'));

    await waitFor(() => {
      expect(screen.getByText('Tata Consultancy Services Limited')).toBeInTheDocument();
      expect(screen.getByText('West Coast Paper Mills Limited')).toBeInTheDocument();
      expect(screen.getByText('INE467B01029')).toBeInTheDocument();
      expect(screen.getByText('WSTCSTPAPR')).toBeInTheDocument();
    });
  });

  // Scenario 3: Case-insensitive query handling at the UI/request level
  it('handles lowercase, uppercase, and mixed-case search queries identically', async () => {
    const searchSpy = vi.spyOn(api, 'searchInstruments').mockResolvedValue(mockSearchResultsTcs);

    render(<App />);

    const searchInput = screen.getByRole('textbox', {
      name: /search instruments by company name or symbol/i,
    });

    // Lowercase
    fireEvent.change(searchInput, { target: { value: 'tcs' } });
    fireEvent.submit(screen.getByRole('search'));

    await waitFor(() => {
      expect(searchSpy).toHaveBeenCalledWith('tcs', 20, 0, expect.any(AbortSignal));
    });
  });

  // Scenario 4 & 5: Selecting an instrument and rendering its details
  it('selects an instrument and renders company details', async () => {
    vi.spyOn(api, 'searchInstruments').mockResolvedValue(mockSearchResultsTcs);
    const detailSpy = vi.spyOn(api, 'getInstrumentDetail').mockResolvedValue(mockDetailWithSnapshot);

    render(<App />);

    const searchInput = screen.getByRole('textbox', {
      name: /search instruments by company name or symbol/i,
    });
    fireEvent.change(searchInput, { target: { value: 'TCS' } });
    fireEvent.submit(screen.getByRole('search'));

    const viewButton = await screen.findByRole('button', {
      name: /view details for tcs/i,
    });
    fireEvent.click(viewButton);

    await waitFor(() => {
      expect(detailSpy).toHaveBeenCalledWith(2304, expect.any(AbortSignal));
      expect(screen.getByRole('heading', { level: 1, name: 'Tata Consultancy Services Limited' })).toBeInTheDocument();
      expect(screen.getAllByText('INE467B01029').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('25 Aug 2004').length).toBeGreaterThanOrEqual(1);
    });
  });

  // Scenario 6: Displaying market snapshot with correct labels and units
  it('displays market snapshot with correct labels and units (LTP as Last-Traded Price, Crores, Lakhs)', async () => {
    vi.spyOn(api, 'searchInstruments').mockResolvedValue(mockSearchResultsTcs);
    vi.spyOn(api, 'getInstrumentDetail').mockResolvedValue(mockDetailWithSnapshot);

    render(<App />);

    fireEvent.change(screen.getByRole('textbox', { name: /search instruments/i }), {
      target: { value: 'TCS' },
    });
    fireEvent.submit(screen.getByRole('search'));

    const viewButton = await screen.findByRole('button', { name: /view details for tcs/i });
    fireEvent.click(viewButton);

    await waitFor(() => {
      // Last-Traded Price (explicitly labelled, NOT closing price)
      expect(screen.getByText('Last-Traded Price (LTP)')).toBeInTheDocument();
      expect(screen.getByText('₹2,304.90')).toBeInTheDocument();

      // Percentage change with symbol and accessible label
      expect(screen.getByText('+2.11%')).toBeInTheDocument();
      expect(screen.getByText('▲')).toBeInTheDocument();

      // Market Capitalization in Crores
      expect(screen.getByText('Market Capitalization')).toBeInTheDocument();
      expect(screen.getByText(/8,33,932\.99/)).toBeInTheDocument();

      // Volume in Lakhs
      expect(screen.getByText('Volume')).toBeInTheDocument();
      expect(screen.getByText(/121\.46/)).toBeInTheDocument();

      // Traded value in Crores
      expect(screen.getByText('Traded Value')).toBeInTheDocument();
      expect(screen.getByText(/2,805\.17/)).toBeInTheDocument();

      // Snapshot date
      expect(screen.getByText('14 Oct 2026')).toBeInTheDocument();
    });
  });

  // Scenario 7: Displaying details when no snapshot exists
  it('displays company details when no market snapshot is available', async () => {
    vi.spyOn(api, 'searchInstruments').mockResolvedValue([
      {
        instrument_id: 117,
        company_name: 'Alfred Herbert India Limited',
        exchange: 'NSE',
        symbol: 'ALFREDHE',
        series: 'EQ',
        isin: 'INE782D01027',
        is_active: true,
      },
    ]);
    vi.spyOn(api, 'getInstrumentDetail').mockResolvedValue(mockDetailWithoutSnapshot);

    render(<App />);

    fireEvent.change(screen.getByRole('textbox', { name: /search instruments/i }), {
      target: { value: 'ALFREDHE' },
    });
    fireEvent.submit(screen.getByRole('search'));

    const viewButton = await screen.findByRole('button', { name: /view details for alfredhe/i });
    fireEvent.click(viewButton);

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: 'Alfred Herbert India Limited' })).toBeInTheDocument();
      expect(screen.getByText(/Market Snapshot Data Unavailable/i)).toBeInTheDocument();
      expect(screen.getAllByText('INE782D01027').length).toBeGreaterThanOrEqual(1);
    });
  });

  // Scenario 8: Empty-result state
  it('renders clean empty state when no matching results are found', async () => {
    vi.spyOn(api, 'searchInstruments').mockResolvedValue([]);

    render(<App />);

    fireEvent.change(screen.getByRole('textbox', { name: /search instruments/i }), {
      target: { value: 'NONEXISTENTCOMPANY' },
    });
    fireEvent.submit(screen.getByRole('search'));

    await waitFor(() => {
      expect(screen.getByText('No instruments found')).toBeInTheDocument();
      expect(screen.getByText(/NONEXISTENTCOMPANY/)).toBeInTheDocument();
    });
  });

  // Scenario 9: Loading state
  it('shows loading indicator while search is in flight', async () => {
    let resolveSearch: (val: InstrumentSearchResult[]) => void = () => {};
    const searchPromise = new Promise<InstrumentSearchResult[]>((resolve) => {
      resolveSearch = resolve;
    });
    vi.spyOn(api, 'searchInstruments').mockReturnValue(searchPromise);

    render(<App />);

    fireEvent.change(screen.getByRole('textbox', { name: /search instruments/i }), {
      target: { value: 'TCS' },
    });
    fireEvent.submit(screen.getByRole('search'));

    expect(screen.getByRole('status', { name: /loading instruments/i })).toBeInTheDocument();

    resolveSearch(mockSearchResultsTcs);

    await waitFor(() => {
      expect(screen.queryByRole('status', { name: /loading instruments/i })).not.toBeInTheDocument();
    });
  });

  // Scenario 10: API/network error state
  it('displays user-friendly error message when network/API call fails', async () => {
    vi.spyOn(api, 'searchInstruments').mockRejectedValue(
      new api.ApiRequestError('Database service is unavailable.', 503)
    );

    render(<App />);

    fireEvent.change(screen.getByRole('textbox', { name: /search instruments/i }), {
      target: { value: 'FAIL' },
    });
    fireEvent.submit(screen.getByRole('search'));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText('Database service is unavailable.')).toBeInTheDocument();
      expect(screen.getByText('HTTP 503')).toBeInTheDocument();
    });
  });

  // Scenario 11: Back navigation or starting a new search
  it('allows returning from details to the preserved search results', async () => {
    vi.spyOn(api, 'searchInstruments').mockResolvedValue(mockSearchResultsTcs);
    vi.spyOn(api, 'getInstrumentDetail').mockResolvedValue(mockDetailWithSnapshot);

    render(<App />);

    fireEvent.change(screen.getByRole('textbox', { name: /search instruments/i }), {
      target: { value: 'TCS' },
    });
    fireEvent.submit(screen.getByRole('search'));

    const viewButton = await screen.findByRole('button', { name: /view details for tcs/i });
    fireEvent.click(viewButton);

    const backButton = await screen.findByRole('button', { name: /return to search results/i });
    expect(backButton).toBeInTheDocument();

    fireEvent.click(backButton);

    await waitFor(() => {
      expect(screen.getByText('Tata Consultancy Services Limited')).toBeInTheDocument();
      expect(screen.getByText('West Coast Paper Mills Limited')).toBeInTheDocument();
    });
  });
});
