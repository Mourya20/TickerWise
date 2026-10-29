import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { InstrumentDetail } from '../InstrumentDetail';
import * as api from '../../services/api';
import type { InstrumentDetailResponse } from '../../types/instrument';
import { ThemeProvider } from '../../context/ThemeContext';

// Mock lightweight-charts
vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({
      setData: vi.fn(),
      priceScale: vi.fn().mockReturnValue({ applyOptions: vi.fn() }),
    })),
    applyOptions: vi.fn(),
    subscribeCrosshairMove: vi.fn(),
    timeScale: vi.fn().mockReturnValue({ fitContent: vi.fn() }),
    remove: vi.fn(),
  })),
  CandlestickSeries: function CandlestickSeries() {},
  HistogramSeries: function HistogramSeries() {},
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
}));

describe('InstrumentDetail Component', () => {
  const mockInstrumentWithSnapshot: InstrumentDetailResponse = {
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
      snapshot_date: '2026-10-26',
      ltp: '2350.000000',
      percentage_change_pct: '1.950000',
      market_capitalization_crores: '850250.570000',
      market_cap_price_basis: 'LTP',
      market_cap_price_date: '2026-10-26',
      share_count: 3618087520,
      share_count_date: '2026-09-30',
      share_count_source: 'NSE Shareholding Pattern Disclosure (XBRL)',
      share_count_status: 'valid',
      market_cap_explanation: '₹2,350.00 (LTP 2026-10-26) × 3,618,087,520 shares (2026-09-30)',
      volume_lakhs: '121.460000',
      volume: 12146000,
      traded_value_crores: '2805.170000',
      turnover: '28051700000.00',
      source_name: 'TejHQ EOD Market Data',
    },
  };

  const mockInstrumentWithStaleShareCount: InstrumentDetailResponse = {
    ...mockInstrumentWithSnapshot,
    snapshot: {
      ...mockInstrumentWithSnapshot.snapshot!,
      share_count_status: 'stale',
    },
  };

  const mockInstrumentWithoutSnapshot: InstrumentDetailResponse = {
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
    vi.clearAllMocks();
    vi.spyOn(api, 'getInstrumentPrices').mockResolvedValue([]);
    vi.spyOn(api, 'getInstrumentCorporateActions').mockResolvedValue([]);
    vi.spyOn(api, 'getInstrumentShareCounts').mockResolvedValue([]);
    vi.spyOn(api, 'getInstrumentCorporateActionsStatus').mockResolvedValue({
      instrument_id: 2304,
      symbol: 'TCS',
      status: 'synced',
      last_checked_at: '2026-10-28T00:00:00Z',
      last_success_at: '2026-10-28T00:00:00Z',
      events_count: 2,
      provider_name: 'TejHQ',
      error_message: null,
    });
  });

  it('renders hero price, delta, and dated market notice', () => {
    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    expect(screen.getByText('₹2,350.00')).toBeInTheDocument();
    expect(screen.getByText('+1.95%')).toBeInTheDocument();
    expect(screen.getByText(/sourced from TejHQ EOD Market Data/i)).toBeInTheDocument();
  });

  it('renders market capitalization, volume, and turnover with provenance', () => {
    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    // Market cap
    expect(screen.getByText('₹8,50,250.57 Cr')).toBeInTheDocument();
    expect(screen.getByText(/3,61,80,87,520 shares/)).toBeInTheDocument();

    // Volume
    expect(screen.getByText('121.46 lakh')).toBeInTheDocument();
    expect(screen.getByText('1,21,46,000 shares')).toBeInTheDocument();

    // Traded Value
    expect(screen.getByText('₹2,805.17 Cr')).toBeInTheDocument();
  });

  it('shows stale badge when share count is older than 120 days', () => {
    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithStaleShareCount} onBack={vi.fn()} />
      </ThemeProvider>
    );

    expect(screen.getByText('Stale >120d')).toBeInTheDocument();
  });

  it('renders unavailable state when instrument has no snapshot', () => {
    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithoutSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    expect(
      screen.getByText(/no end-of-day snapshot for this instrument/i)
    ).toBeInTheDocument();
  });

  it('switches to Prices tab and displays historical price section', async () => {
    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    const pricesTab = screen.getByRole('tab', { name: /prices/i });
    fireEvent.click(pricesTab);

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /tcs · historical daily prices & volume/i })
      ).toBeInTheDocument();
    });
  });

  it('navigates back to search when Back button is clicked', () => {
    const onBackMock = vi.fn();
    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={onBackMock} />
      </ThemeProvider>
    );

    const backButton = screen.getByRole('button', { name: /return to search results/i });
    fireEvent.click(backButton);
    expect(onBackMock).toHaveBeenCalledTimes(1);
  });

  it('switches to Corporate Actions tab and displays actions and share capital tables', async () => {
    vi.spyOn(api, 'getInstrumentCorporateActions').mockResolvedValue([
      {
        id: 1,
        instrument_id: 2304,
        exchange: 'NSE',
        symbol: 'TCS',
        event_type: 'bonus',
        dedup_key: 'NSE:TCS:bonus:2026-10-01:R1_1',
        ex_date: '2026-10-01',
        ratio_num: 1,
        ratio_den: 1,
        status: 'completed',
        source_id: 1,
        source_name: 'TejHQ Corporate Actions',
        retrieved_at: '2026-10-28T00:00:00Z',
        validation_status: 'valid',
      },
      {
        id: 2,
        instrument_id: 2304,
        exchange: 'NSE',
        symbol: 'TCS',
        event_type: 'dividend',
        dedup_key: 'NSE:TCS:dividend:2026-10-15:C12',
        ex_date: '2026-10-15',
        cash_amount: '12.00',
        status: 'completed',
        source_id: 1,
        source_name: 'TejHQ Corporate Actions',
        retrieved_at: '2026-10-28T00:00:00Z',
        validation_status: 'valid',
      },
    ]);

    vi.spyOn(api, 'getInstrumentShareCounts').mockResolvedValue([
      {
        id: 1,
        instrument_id: 2304,
        symbol: 'TCS',
        series: 'EQ',
        share_class: 'EQUITY',
        reported_share_count: 3618087520,
        reporting_date: '2026-09-30',
        retrieved_at: '2026-10-28T00:00:00Z',
        extraction_method: 'directly_reported',
        validation_status: 'valid',
        corporate_action_adjusted: false,
      },
    ]);

    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    const actionsTab = screen.getByRole('tab', { name: /corporate actions/i });
    fireEvent.click(actionsTab);

    await waitFor(() => {
      expect(screen.getByTestId('corporate-actions-heading')).toBeInTheDocument();
      expect(screen.getByText(/bonus issue 1:1/i)).toBeInTheDocument();
      expect(screen.getByText(/dividend ₹12.00 per share/i)).toBeInTheDocument();
      expect(screen.getByText('3,61,80,87,520')).toBeInTheDocument();
      expect(screen.getByText('Direct XBRL')).toBeInTheDocument();
    });
  });

  it('displays verified empty state when provider reports 0 actions', async () => {
    vi.spyOn(api, 'getInstrumentCorporateActions').mockResolvedValue([]);
    vi.spyOn(api, 'getInstrumentCorporateActionsStatus').mockResolvedValue({
      instrument_id: 2304,
      symbol: 'TCS',
      status: 'empty',
      last_checked_at: '2026-10-28T00:00:00Z',
      last_success_at: '2026-10-28T00:00:00Z',
      events_count: 0,
      provider_name: 'TejHQ',
      error_message: null,
    });

    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    const actionsTab = screen.getByRole('tab', { name: /corporate actions/i });
    fireEvent.click(actionsTab);

    await waitFor(() => {
      expect(screen.getByTestId('corporate-actions-empty')).toBeInTheDocument();
      expect(screen.getByText('Verified Empty')).toBeInTheDocument();
      expect(screen.getByText(/no corporate actions on record/i)).toBeInTheDocument();
    });
  });

  it('displays not synchronized state with CLI instructions when instrument is not synced', async () => {
    vi.spyOn(api, 'getInstrumentCorporateActions').mockResolvedValue([]);
    vi.spyOn(api, 'getInstrumentCorporateActionsStatus').mockResolvedValue({
      instrument_id: 2304,
      symbol: 'TCS',
      status: 'not_synced',
      last_checked_at: null,
      last_success_at: null,
      events_count: 0,
      provider_name: 'TejHQ',
      error_message: null,
    });

    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    const actionsTab = screen.getByRole('tab', { name: /corporate actions/i });
    fireEvent.click(actionsTab);

    await waitFor(() => {
      expect(screen.getByTestId('corporate-actions-not-synced')).toBeInTheDocument();
      expect(screen.getByText('Not Synchronized')).toBeInTheDocument();
      expect(screen.getByText(/python scripts\/sync_corporate_actions.py --symbols TCS/i)).toBeInTheDocument();
    });
  });

  it('displays sync failed state when provider synchronization failed', async () => {
    vi.spyOn(api, 'getInstrumentCorporateActions').mockResolvedValue([]);
    vi.spyOn(api, 'getInstrumentCorporateActionsStatus').mockResolvedValue({
      instrument_id: 2304,
      symbol: 'TCS',
      status: 'failed',
      last_checked_at: '2026-10-28T00:00:00Z',
      last_success_at: null,
      events_count: 0,
      provider_name: 'TejHQ',
      error_message: 'HTTP 502 Bad Gateway from TejHQ upstream endpoint.',
    });

    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    const actionsTab = screen.getByRole('tab', { name: /corporate actions/i });
    fireEvent.click(actionsTab);

    await waitFor(() => {
      expect(screen.getByTestId('corporate-actions-failed')).toBeInTheDocument();
      expect(screen.getByText('Sync Failed')).toBeInTheDocument();
      expect(screen.getByText(/HTTP 502 Bad Gateway/i)).toBeInTheDocument();
    });
  });

  it('displays partial coverage state when ingestion has partial issues', async () => {
    vi.spyOn(api, 'getInstrumentCorporateActions').mockResolvedValue([]);
    vi.spyOn(api, 'getInstrumentCorporateActionsStatus').mockResolvedValue({
      instrument_id: 2304,
      symbol: 'TCS',
      status: 'partial',
      last_checked_at: '2026-10-28T00:00:00Z',
      last_success_at: '2026-10-28T00:00:00Z',
      events_count: 1,
      provider_name: 'TejHQ',
      error_message: '2 rows were skipped due to malformed date format.',
    });

    render(
      <ThemeProvider>
        <InstrumentDetail instrument={mockInstrumentWithSnapshot} onBack={vi.fn()} />
      </ThemeProvider>
    );

    const actionsTab = screen.getByRole('tab', { name: /corporate actions/i });
    fireEvent.click(actionsTab);

    await waitFor(() => {
      expect(screen.getByTestId('corporate-actions-partial')).toBeInTheDocument();
      expect(screen.getAllByText('Partial Coverage').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/2 rows were skipped due to malformed date format/i)).toBeInTheDocument();
    });
  });
});

