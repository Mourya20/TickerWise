import React from 'react';
import type { InstrumentDetailResponse } from '../types/instrument';
import {
  formatCurrencyINR,
  formatDate,
  formatPercentageChange,
  formatPlainDecimal,
} from '../utils/formatters';

interface InstrumentDetailProps {
  instrument: InstrumentDetailResponse;
  onBack: () => void;
}

export const InstrumentDetail: React.FC<InstrumentDetailProps> = ({
  instrument,
  onBack,
}) => {
  const { snapshot } = instrument;
  const pctChange = snapshot ? formatPercentageChange(snapshot.percentage_change_pct) : null;

  return (
    <div className="instrument-detail-container" role="main" aria-label="Instrument details">
      {/* Top Navigation */}
      <div className="detail-top-bar">
        <button
          type="button"
          id="back-to-results-btn"
          className="back-btn"
          onClick={onBack}
          aria-label="Return to search results"
        >
          ← Back to results
        </button>
        <div className="detail-breadcrumbs" aria-hidden="true">
          <span>Instruments</span>
          <span className="breadcrumb-separator">/</span>
          <span>{instrument.symbol}</span>
          <span className="breadcrumb-separator">/</span>
          <span>Series {instrument.series}</span>
        </div>
      </div>

      {/* Main Company Header */}
      <div className="company-header-card">
        <div className="company-primary-info">
          <div className="company-badge-strip">
            <span className="badge badge-exchange">{instrument.exchange}</span>
            <span className="badge badge-symbol">{instrument.symbol}</span>
            <span className="badge badge-series">Series: {instrument.series}</span>
            <span className="badge badge-type">{instrument.instrument_type}</span>
            <span className={`status-pill ${instrument.is_active ? 'active' : 'inactive'}`}>
              <span className="status-pill-dot" />
              {instrument.is_active ? 'Trading Active' : 'Suspended'}
            </span>
          </div>
          <h1 className="company-title" id="instrument-company-name">
            {instrument.company_name}
          </h1>
          <div className="company-meta-row">
            <span className="meta-item">
              <span className="meta-label">ISIN:</span>{' '}
              <strong className="meta-value isin-text">{instrument.isin || '—'}</strong>
            </span>
            <span className="meta-divider">•</span>
            <span className="meta-item">
              <span className="meta-label">Listed on:</span>{' '}
              <strong className="meta-value">{formatDate(instrument.listing_date)}</strong>
            </span>
            <span className="meta-divider">•</span>
            <span className="meta-item">
              <span className="meta-label">Instrument ID:</span>{' '}
              <span className="meta-value">#{instrument.instrument_id}</span>
            </span>
          </div>
        </div>
      </div>

      {/* End-of-Day Market Snapshot Section */}
      <section className="snapshot-section" aria-labelledby="snapshot-heading">
        <div className="section-header">
          <div className="section-title-group">
            <h2 id="snapshot-heading" className="section-title">
              End-of-Day Market Snapshot
            </h2>
            <p className="section-caption">
              End-of-day market statistics from official exchange trades.
            </p>
          </div>
          {snapshot && (
            <div className="snapshot-date-tag">
              <span className="snapshot-date-label">As on</span>
              <strong className="snapshot-date-value">
                {formatDate(snapshot.snapshot_date)}
              </strong>
            </div>
          )}
        </div>

        {snapshot ? (
          <div className="snapshot-metrics-grid">
            {/* LTP Card */}
            <div className="metric-card metric-primary">
              <div className="metric-card-header">
                <span className="metric-label" id="label-ltp">Last-Traded Price (LTP)</span>
                <span className="metric-tag">Live / EOD</span>
              </div>
              <div className="metric-body">
                <div className="metric-main-value" aria-labelledby="label-ltp">
                  {formatCurrencyINR(snapshot.ltp)}
                </div>
                {pctChange && (
                  <div
                    className={`metric-delta delta-${pctChange.direction}`}
                    role="status"
                    aria-label={pctChange.accessibleText}
                  >
                    <span className="delta-symbol" aria-hidden="true">
                      {pctChange.symbol}
                    </span>
                    <span className="delta-value">{pctChange.formatted}</span>
                    <span className="delta-context">vs Prev Close</span>
                  </div>
                )}
              </div>
              <div className="metric-footnote">
                Official last traded execution price on snapshot date.
              </div>
            </div>

            {/* Market Capitalization Card */}
            <div className="metric-card">
              <div className="metric-card-header">
                <span className="metric-label" id="label-mcap">Market Capitalization</span>
                <span className="metric-unit-badge">₹ Crores</span>
              </div>
              <div className="metric-body">
                <div className="metric-numeric-value" aria-labelledby="label-mcap">
                  {formatPlainDecimal(snapshot.market_capitalization_crores, 2)}
                  <span className="unit-suffix"> Cr</span>
                </div>
              </div>
              <div className="metric-footnote">
                Total market value of equity in crores.
              </div>
            </div>

            {/* Traded Volume Card */}
            <div className="metric-card">
              <div className="metric-card-header">
                <span className="metric-label" id="label-volume">Volume</span>
                <span className="metric-unit-badge">Lakhs</span>
              </div>
              <div className="metric-body">
                <div className="metric-numeric-value" aria-labelledby="label-volume">
                  {formatPlainDecimal(snapshot.volume_lakhs, 2)}
                  <span className="unit-suffix"> Lakhs</span>
                </div>
              </div>
              <div className="metric-footnote">
                Total shares traded during session in lakhs.
              </div>
            </div>

            {/* Traded Value Card */}
            <div className="metric-card">
              <div className="metric-card-header">
                <span className="metric-label" id="label-value">Traded Value</span>
                <span className="metric-unit-badge">₹ Crores</span>
              </div>
              <div className="metric-body">
                <div className="metric-numeric-value" aria-labelledby="label-value">
                  {formatPlainDecimal(snapshot.traded_value_crores, 2)}
                  <span className="unit-suffix"> Cr</span>
                </div>
              </div>
              <div className="metric-footnote">
                Aggregate monetary turnover in crores.
              </div>
            </div>
          </div>
        ) : (
          <div className="snapshot-unavailable-card" role="alert">
            <div className="unavailable-icon" aria-hidden="true">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <div className="unavailable-content">
              <h3 className="unavailable-title">Market Snapshot Data Unavailable</h3>
              <p className="unavailable-message">
                An end-of-day trading snapshot has not been recorded for this instrument.
                This typically occurs for newly listed or suspended series without recorded trades on the latest snapshot date.
              </p>
              <p className="unavailable-note">
                Security master details and company registration remain verified below.
              </p>
            </div>
          </div>
        )}
      </section>

      {/* Security Master Details Section */}
      <section className="master-details-section" aria-labelledby="master-details-heading">
        <h2 id="master-details-heading" className="section-title">
          Security Master & Listing Attributes
        </h2>

        <div className="details-table-card">
          <dl className="key-value-grid">
            <div className="key-value-row">
              <dt className="kv-label">Symbol</dt>
              <dd className="kv-value"><code>{instrument.symbol}</code></dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Series Code</dt>
              <dd className="kv-value">{instrument.series}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Exchange</dt>
              <dd className="kv-value">{instrument.exchange}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Instrument Type</dt>
              <dd className="kv-value">{instrument.instrument_type}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">ISIN Code</dt>
              <dd className="kv-value isin-text">{instrument.isin || '—'}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Listing Date</dt>
              <dd className="kv-value">{formatDate(instrument.listing_date)}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Face Value</dt>
              <dd className="kv-value">{formatCurrencyINR(instrument.face_value)}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Paid-Up Value</dt>
              <dd className="kv-value">{formatCurrencyINR(instrument.paid_up_value)}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Market Lot</dt>
              <dd className="kv-value">{instrument.market_lot ?? '—'}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Trading Status</dt>
              <dd className="kv-value">
                {instrument.is_active ? 'Active on Exchange' : 'Inactive / Delisted'}
              </dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Company Record ID</dt>
              <dd className="kv-value">#{instrument.company_id}</dd>
            </div>
            <div className="key-value-row">
              <dt className="kv-label">Instrument Record ID</dt>
              <dd className="kv-value">#{instrument.instrument_id}</dd>
            </div>
          </dl>
        </div>
      </section>
    </div>
  );
};
