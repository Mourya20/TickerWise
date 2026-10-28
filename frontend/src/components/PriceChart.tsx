import React, { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts';
import { useTheme } from '../context/ThemeContext';
import { getInstrumentPrices } from '../services/api';
import type { PriceBar } from '../types/instrument';
import {
  formatDate,
  formatPlainDecimal,
  formatTradedValueCrores,
  formatVolumeLakhs,
} from '../utils/formatters';

interface PriceChartProps {
  instrumentId: number;
  symbol: string;
  latestDate?: string;
}

type RangeOption = '1M' | '3M' | '6M' | '1Y' | 'ALL';

function calculateFromDate(range: RangeOption, anchorDateStr?: string): string | undefined {
  if (range === 'ALL') return undefined;

  let baseDate = new Date();
  if (anchorDateStr) {
    const parsed = new Date(anchorDateStr);
    if (!isNaN(parsed.getTime())) {
      baseDate = parsed;
    }
  }

  const d = new Date(baseDate.getTime());

  if (range === '1M') d.setDate(d.getDate() - 30);
  else if (range === '3M') d.setDate(d.getDate() - 90);
  else if (range === '6M') d.setDate(d.getDate() - 180);
  else if (range === '1Y') d.setDate(d.getDate() - 365);

  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export const PriceChart: React.FC<PriceChartProps> = ({ instrumentId, symbol, latestDate }) => {
  const { theme } = useTheme();
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  const [range, setRange] = useState<RangeOption>('6M');
  const [bars, setBars] = useState<PriceBar[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [hoveredBar, setHoveredBar] = useState<PriceBar | null>(null);

  // Fetch complete price history for the selected range with automatic multi-page pagination and cancellation
  const fetchPrices = async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const fromDate = calculateFromDate(range, latestDate);
      const barsMap = new Map<string, PriceBar>();
      let offset = 0;
      const pageSize = 1000;
      const maxPages = 50;

      for (let page = 0; page < maxPages; page++) {
        if (signal?.aborted) return;
        const pageBars = await getInstrumentPrices(
          instrumentId,
          fromDate,
          undefined,
          pageSize,
          offset,
          page === 0, // trigger auto_backfill on first page if missing
          signal
        );
        if (signal?.aborted) return;
        if (!pageBars || pageBars.length === 0) break;

        for (const b of pageBars) {
          barsMap.set(b.trading_date, b);
        }

        if (pageBars.length < pageSize) break;
        offset += pageSize;
      }

      const sortedData = Array.from(barsMap.values()).sort((a, b) =>
        a.trading_date.localeCompare(b.trading_date)
      );

      setBars(sortedData);
      if (sortedData.length > 0) {
        setHoveredBar(sortedData[sortedData.length - 1]);
      } else {
        setHoveredBar(null);
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return; // Normal cancellation
      }
      const message = err instanceof Error ? err.message : 'Failed to load historical prices';
      setError(message);
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    fetchPrices(controller.signal);
    return () => {
      controller.abort();
    };
  }, [instrumentId, range]);

  // Initialize and update Lightweight Charts instance
  useEffect(() => {
    if (!chartContainerRef.current || loading || error || bars.length === 0) {
      return;
    }

    const isDark = theme === 'dark';
    const container = chartContainerRef.current;

    // Clean up previous chart instance
    if (chartInstanceRef.current) {
      chartInstanceRef.current.remove();
      chartInstanceRef.current = null;
    }

    const chart = createChart(container, {
      width: container.clientWidth || 800,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: isDark ? '#0b1120' : '#ffffff' },
        textColor: isDark ? '#94a3b8' : '#475569',
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(226, 232, 240, 0.8)' },
        horzLines: { color: isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(226, 232, 240, 0.8)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: isDark ? '#334155' : '#cbd5e1',
        scaleMargins: {
          top: 0.1,
          bottom: 0.25,
        },
      },
      timeScale: {
        borderColor: isDark ? '#334155' : '#cbd5e1',
        timeVisible: false,
      },
    });

    chartInstanceRef.current = chart;

    // Candlestick Series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });
    candleSeriesRef.current = candleSeries;

    // Volume Histogram Series
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: 'volume_scale',
    });
    volumeSeriesRef.current = volumeSeries;

    chart.priceScale('volume_scale').applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    // Populate data
    const candleData = bars
      .filter((b) => b.open !== null && b.high !== null && b.low !== null && b.close !== null)
      .map((b) => ({
        time: b.trading_date,
        open: Number(b.open),
        high: Number(b.high),
        low: Number(b.low),
        close: Number(b.close),
      }));

    const volumeData = bars
      .filter((b) => b.volume !== null && b.volume !== undefined)
      .map((b) => {
        const open = Number(b.open ?? 0);
        const close = Number(b.close ?? 0);
        const isUp = close >= open;
        return {
          time: b.trading_date,
          value: Number(b.volume),
          color: isUp ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
        };
      });

    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);
    chart.timeScale().fitContent();

    // Map by date string for crosshair inspection
    const barMap = new Map<string, PriceBar>();
    bars.forEach((b) => barMap.set(b.trading_date, b));

    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time) {
        if (bars.length > 0) {
          setHoveredBar(bars[bars.length - 1]);
        }
        return;
      }
      const timeStr = typeof param.time === 'string' ? param.time : '';
      if (timeStr && barMap.has(timeStr)) {
        setHoveredBar(barMap.get(timeStr) || null);
      }
    });

    // Resize observer
    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver((entries) => {
        if (!entries || entries.length === 0 || !chartInstanceRef.current) return;
        const { width } = entries[0].contentRect;
        if (width > 0) {
          chartInstanceRef.current.applyOptions({ width });
        }
      });
      resizeObserver.observe(container);
    }

    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      if (chartInstanceRef.current) {
        chartInstanceRef.current.remove();
        chartInstanceRef.current = null;
      }
    };
  }, [bars, theme, loading, error]);

  const latestBar = bars.length > 0 ? bars[bars.length - 1] : null;
  const activeInspectionBar = hoveredBar || latestBar;

  return (
    <div className="price-chart-card" role="region" aria-label={`Historical price chart for ${symbol}`}>
      {/* Top Header / Range Selector & Latest Date */}
      <div className="chart-header-row">
        <div className="chart-title-group">
          <h3 className="chart-title">Daily OHLCV Chart</h3>
          {bars.length > 0 && (
            <span className="chart-latest-date-pill" title={`Available history: ${bars[0].trading_date} to ${bars[bars.length - 1].trading_date}`}>
              {bars.length} sessions ({formatDate(bars[0].trading_date)} – {formatDate(bars[bars.length - 1].trading_date)})
            </span>
          )}
        </div>

        <div className="chart-range-selector" role="group" aria-label="Select date range">
          {(['1M', '3M', '6M', '1Y', 'ALL'] as RangeOption[]).map((r) => (
            <button
              key={r}
              type="button"
              className={`range-pill-btn ${range === r ? 'range-pill-active' : ''}`}
              onClick={() => setRange(r)}
              aria-pressed={range === r}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Selected Bar Inspect Strip */}
      {activeInspectionBar && !loading && !error && (
        <div className="chart-inspect-strip" aria-live="polite">
          <div className="inspect-item">
            <span className="inspect-label">DATE:</span>
            <span className="inspect-value">{formatDate(activeInspectionBar.trading_date)}</span>
          </div>
          <div className="inspect-item">
            <span className="inspect-label">O:</span>
            <span className="inspect-value">{formatPlainDecimal(activeInspectionBar.open)}</span>
          </div>
          <div className="inspect-item">
            <span className="inspect-label">H:</span>
            <span className="inspect-value">{formatPlainDecimal(activeInspectionBar.high)}</span>
          </div>
          <div className="inspect-item">
            <span className="inspect-label">L:</span>
            <span className="inspect-value">{formatPlainDecimal(activeInspectionBar.low)}</span>
          </div>
          <div className="inspect-item">
            <span className="inspect-label">C:</span>
            <span className="inspect-value font-semibold">
              {formatPlainDecimal(activeInspectionBar.close)}
            </span>
          </div>
          {activeInspectionBar.volume_lakhs && (
            <div className="inspect-item">
              <span className="inspect-label">VOL:</span>
              <span className="inspect-value">{formatVolumeLakhs(activeInspectionBar.volume_lakhs)}</span>
            </div>
          )}
          {activeInspectionBar.traded_value_crores && (
            <div className="inspect-item">
              <span className="inspect-label">VAL:</span>
              <span className="inspect-value">
                {formatTradedValueCrores(activeInspectionBar.traded_value_crores)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Main Chart Body / States */}
      <div className="chart-canvas-container">
        {loading && (
          <div className="chart-loading-overlay" role="status">
            <div className="chart-spinner" aria-hidden="true" />
            <p className="loading-text">Loading historical price bars...</p>
          </div>
        )}

        {error && !loading && (
          <div className="chart-error-box" role="alert">
            <span className="error-icon" aria-hidden="true">⚠️</span>
            <p className="error-title">Failed to load price history</p>
            <p className="error-message">{error}</p>
            <button
              type="button"
              className="chart-retry-btn"
              onClick={fetchPrices}
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !error && bars.length === 0 && (
          <div className="chart-empty-box" role="status">
            <p className="empty-title">No Historical Price Data</p>
            <p className="empty-sub">
              No daily price bars found for {symbol} within the selected range ({range}).
            </p>
          </div>
        )}

        <div
          ref={chartContainerRef}
          className={`chart-render-target ${loading || error || bars.length === 0 ? 'hidden' : ''}`}
          style={{ width: '100%', height: '420px' }}
        />
      </div>
    </div>
  );
};
