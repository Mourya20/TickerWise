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
});
