import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { PriceChart } from '../PriceChart';
import * as api from '../../services/api';
import type { PriceBar } from '../../types/instrument';
import { ThemeProvider } from '../../context/ThemeContext';

// Mock lightweight-charts
const mockCandleSeries = {
  setData: vi.fn(),
};
const mockVolumeSeries = {
  setData: vi.fn(),
  priceScale: vi.fn().mockReturnValue({
    applyOptions: vi.fn(),
  }),
};
const mockTimeScale = {
  fitContent: vi.fn(),
};
const mockChartApi = {
  addSeries: vi.fn((seriesType: unknown) => {
    // If CandlestickSeries
    if (seriesType && typeof seriesType === 'function' && seriesType.name === 'CandlestickSeries') {
      return mockCandleSeries;
    }
    return mockVolumeSeries;
  }),
  applyOptions: vi.fn(),
  subscribeCrosshairMove: vi.fn(),
  timeScale: vi.fn().mockReturnValue(mockTimeScale),
  priceScale: vi.fn().mockReturnValue({ applyOptions: vi.fn() }),
  remove: vi.fn(),
};

vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => mockChartApi),
  CandlestickSeries: function CandlestickSeries() {},
  HistogramSeries: function HistogramSeries() {},
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
}));

describe('PriceChart Component', () => {
  const mockBars: PriceBar[] = [
    {
      trading_date: '2026-10-23',
      open: '2300.00',
      high: '2325.00',
      low: '2295.00',
      close: '2320.00',
      ltp: '2320.00',
      prev_close: '2290.00',
      volume: 1500000,
      volume_lakhs: '15.00',
      turnover: '348000000',
      traded_value_crores: '34.80',
      percentage_change_pct: '1.31',
    },
    {
      trading_date: '2026-10-24',
      open: '2320.00',
      high: '2350.00',
      low: '2310.00',
      close: '2345.00',
      ltp: '2345.00',
      prev_close: '2320.00',
      volume: 2000000,
      volume_lakhs: '20.00',
      turnover: '469000000',
      traded_value_crores: '46.90',
      percentage_change_pct: '1.08',
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading state and then chart controls when data resolves', async () => {
    vi.spyOn(api, 'getInstrumentPrices').mockResolvedValue(mockBars);

    render(
      <ThemeProvider>
        <PriceChart instrumentId={2304} symbol="TCS" />
      </ThemeProvider>
    );

    // Initial loading indicator
    expect(screen.getByText(/loading historical price bars/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Daily OHLCV Chart')).toBeInTheDocument();
    });

    // Check range selector buttons
    expect(screen.getByText('1M')).toBeInTheDocument();
    expect(screen.getByText('3M')).toBeInTheDocument();
    expect(screen.getByText('6M')).toBeInTheDocument();
    expect(screen.getByText('1Y')).toBeInTheDocument();
    expect(screen.getByText('ALL')).toBeInTheDocument();
  });

  it('displays hover inspect panel with initial latest bar data', async () => {
    vi.spyOn(api, 'getInstrumentPrices').mockResolvedValue(mockBars);

    render(
      <ThemeProvider>
        <PriceChart instrumentId={2304} symbol="TCS" />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('24 Oct 2026')).toBeInTheDocument();
      expect(screen.getByText('2,320.00')).toBeInTheDocument(); // Open
      expect(screen.getByText('2,350.00')).toBeInTheDocument(); // High
      expect(screen.getByText('2,310.00')).toBeInTheDocument(); // Low
      expect(screen.getByText('2,345.00')).toBeInTheDocument(); // Close
      expect(screen.getByText('20.00 lakh')).toBeInTheDocument(); // Volume
      expect(screen.getByText('₹46.90 Cr')).toBeInTheDocument(); // Traded value
    });
  });

  it('changes range and refetches historical data when a button is clicked', async () => {
    const fetchSpy = vi.spyOn(api, 'getInstrumentPrices').mockResolvedValue(mockBars);

    render(
      <ThemeProvider>
        <PriceChart instrumentId={2304} symbol="TCS" />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('1M')).toBeInTheDocument();
    });

    // Click 1M button
    fireEvent.click(screen.getByText('1M'));

    await waitFor(() => {
      // 2 calls: first for 6M default, second for 1M
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });
  });

  it('displays empty state message when no bars are returned', async () => {
    vi.spyOn(api, 'getInstrumentPrices').mockResolvedValue([]);

    render(
      <ThemeProvider>
        <PriceChart instrumentId={9999} symbol="EMPTY" />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('No Historical Price Data')).toBeInTheDocument();
      expect(screen.getByText(/no daily price bars found/i)).toBeInTheDocument();
    });
  });

  it('displays error state and retries on button click', async () => {
    const fetchSpy = vi
      .spyOn(api, 'getInstrumentPrices')
      .mockRejectedValueOnce(new Error('Network connection timeout'))
      .mockResolvedValueOnce(mockBars);

    render(
      <ThemeProvider>
        <PriceChart instrumentId={2304} symbol="TCS" />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/failed to load price history/i)).toBeInTheDocument();
      expect(screen.getByText(/network connection timeout/i)).toBeInTheDocument();
    });

    // Click Retry
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getByText('24 Oct 2026')).toBeInTheDocument();
      expect(screen.queryByText(/failed to load price history/i)).not.toBeInTheDocument();
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('fetches all available history without from date and shows coverage notice for limited sets', async () => {
    // Generate 10 bars (simulating initial snapshot-only instrument)
    const tenBars: PriceBar[] = Array.from({ length: 10 }, (_, i) => ({
      trading_date: `2026-10-${String(14 + i).padStart(2, '0')}`,
      open: '100.00',
      high: '105.00',
      low: '99.00',
      close: '102.00',
      ltp: '102.00',
      prev_close: '100.00',
      volume: 10000,
      volume_lakhs: '0.10',
      turnover: '1020000',
      traded_value_crores: '0.10',
      percentage_change_pct: '2.00',
    }));

    const fetchSpy = vi.spyOn(api, 'getInstrumentPrices').mockResolvedValue(tenBars);

    render(
      <ThemeProvider>
        <PriceChart instrumentId={1} symbol="20MICRONS" />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('ALL')).toBeInTheDocument();
    });

    // Click ALL
    fireEvent.click(screen.getByText('ALL'));

    await waitFor(() => {
      // The second call (for ALL) should have undefined fromDate
      expect(fetchSpy).toHaveBeenLastCalledWith(1, undefined, undefined, 1000, 0, expect.anything());
      // Session pill should show 10 sessions
      expect(screen.getByTitle(/Available history/i)).toHaveTextContent(/10 sessions/);
      // Honest coverage notice is rendered
      expect(screen.getByRole('note')).toHaveTextContent(/Displaying all 10 sessions currently stored in the database/i);
    });
  });

  it('handles multi-page pagination for histories exceeding 1000 bars without duplicates', async () => {
    // Page 0: 1000 bars
    const page0: PriceBar[] = Array.from({ length: 1000 }, (_, i) => ({
      trading_date: `2024-01-${String((i % 28) + 1).padStart(2, '0')}-${i}`,
      open: '500.00',
      high: '510.00',
      low: '495.00',
      close: '505.00',
      ltp: '505.00',
      prev_close: '500.00',
      volume: 50000,
      volume_lakhs: '0.50',
      turnover: '25250000',
      traded_value_crores: '2.52',
      percentage_change_pct: '1.00',
    }));

    // Page 1: 250 bars
    const page1: PriceBar[] = Array.from({ length: 250 }, (_, i) => ({
      trading_date: `2020-01-${String((i % 28) + 1).padStart(2, '0')}-${i}`,
      open: '400.00',
      high: '410.00',
      low: '395.00',
      close: '405.00',
      ltp: '405.00',
      prev_close: '400.00',
      volume: 30000,
      volume_lakhs: '0.30',
      turnover: '12150000',
      traded_value_crores: '1.21',
      percentage_change_pct: '1.25',
    }));

    const fetchSpy = vi.spyOn(api, 'getInstrumentPrices')
      .mockResolvedValueOnce(page0)
      .mockResolvedValueOnce(page1);

    render(
      <ThemeProvider>
        <PriceChart instrumentId={1879} symbol="RELIANCE" />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/1250 sessions/i)).toBeInTheDocument();
    });

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    // Page 0 requested with offset 0
    expect(fetchSpy).toHaveBeenNthCalledWith(1, 1879, expect.anything(), undefined, 1000, 0, expect.anything());
    // Page 1 requested with offset 1000
    expect(fetchSpy).toHaveBeenNthCalledWith(2, 1879, expect.anything(), undefined, 1000, 1000, expect.anything());
  });

  it('resets bars and prevents stale data lingering when switching instruments', async () => {
    vi.spyOn(api, 'getInstrumentPrices').mockResolvedValue(mockBars);

    const { rerender } = render(
      <ThemeProvider>
        <PriceChart instrumentId={2304} symbol="TCS" />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/2 sessions/i)).toBeInTheDocument();
    });

    // Switch instrument
    rerender(
      <ThemeProvider>
        <PriceChart instrumentId={1879} symbol="RELIANCE" />
      </ThemeProvider>
    );

    // Initial render of switched instrument shows loading state
    expect(screen.getByText(/loading historical price bars/i)).toBeInTheDocument();
  });

  it('handles bar with missing volume without converting to zero or crashing', async () => {
    const barMissingVolume: PriceBar[] = [
      {
        trading_date: '2026-10-25',
        open: '1500.00',
        high: '1520.00',
        low: '1490.00',
        close: '1510.00',
        ltp: '1510.00',
        prev_close: '1500.00',
        volume: null,
        volume_lakhs: null,
        turnover: null,
        traded_value_crores: null,
        percentage_change_pct: '0.67',
      },
    ];

    vi.spyOn(api, 'getInstrumentPrices').mockResolvedValue(barMissingVolume);

    render(
      <ThemeProvider>
        <PriceChart instrumentId={2304} symbol="TCS" />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('25 Oct 2026')).toBeInTheDocument();
      expect(screen.getByText('1,510.00')).toBeInTheDocument();
      // Volume item should NOT be in document
      expect(screen.queryByText(/VOL:/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/VAL:/i)).not.toBeInTheDocument();
    });
  });
});
