import React, { useState } from 'react';
import type { InstrumentDetailResponse } from '../types/instrument';
import {
  formatCurrencyINR,
  formatDate,
  formatPercentageChange,
  formatPlainDecimal,
  formatShareCount,
} from '../utils/formatters';
import { PlannedFeature } from './PlannedFeature';
import { PriceChart } from './PriceChart';

interface InstrumentDetailProps {
  instrument: InstrumentDetailResponse;
  onBack: () => void;
  initialTab?: string;
}

type TabKey =
  | 'snapshot'
  | 'overview'
  | 'prices'
  | 'technical'
  | 'fundamentals'
  | 'peers'
  | 'news'
  | 'documents'
  | 'research';

const TABS: { key: TabKey; label: string; isPlanned: boolean }[] = [
  { key: 'snapshot', label: 'Snapshot', isPlanned: false },
  { key: 'prices', label: 'Prices', isPlanned: false },
  { key: 'technical', label: 'Technical', isPlanned: true },
  { key: 'fundamentals', label: 'Fundamentals', isPlanned: true },
  { key: 'peers', label: 'Peers', isPlanned: true },
  { key: 'news', label: 'News', isPlanned: true },
  { key: 'documents', label: 'Documents', isPlanned: true },
  { key: 'research', label: 'Research', isPlanned: true },
];

export const InstrumentDetail: React.FC<InstrumentDetailProps> = ({
  instrument,
  onBack,
  initialTab = 'snapshot',
}) => {
  const normalizedInitial = (initialTab === 'overview' ? 'snapshot' : initialTab) as TabKey;
  const [activeTab, setActiveTab] = useState<TabKey>(normalizedInitial || 'snapshot');

  const { snapshot } = instrument;
  const pctChange = snapshot ? formatPercentageChange(snapshot.percentage_change_pct) : null;

  return (
    <div className="instrument-detail-container" role="main" aria-label="Instrument details">
      {/* Top Navigation & Breadcrumbs */}
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
        <div className="detail-breadcrumbs" aria-label="Breadcrumb">
          <span className="crumb-slash">/</span>
          <span className="crumb-symbol-series">{instrument.symbol} · {instrument.series}</span>
        </div>
      </div>

      {/* Company Heading & Metadata line */}
      <div className="company-header-block">
        <div className="company-title-wrapper">
          <span className="company-symbol-hero">{instrument.symbol}</span>
          <h1 className="company-title" id="instrument-company-name">
            {instrument.company_name}
          </h1>
        </div>

        <div className="company-meta-strip">
          <span>{instrument.exchange}</span>
          <span className="meta-dot">·</span>
          <span>{instrument.symbol}</span>
          <span className="meta-dot">·</span>
          <span>SERIES {instrument.series}</span>
          <span className="meta-dot">·</span>
          <span>{instrument.instrument_type}</span>
          <span className="meta-dot">·</span>
          <span>{instrument.is_active ? 'MASTER LISTED' : 'MASTER SUSPENDED'}</span>
          {instrument.isin && (
            <>
              <span className="meta-dot">·</span>
              <span>ISIN {instrument.isin}</span>
            </>
          )}
          {instrument.listing_date && (
            <>
              <span className="meta-dot">·</span>
              <span>LISTED {formatDate(instrument.listing_date)}</span>
            </>
          )}
        </div>
      </div>

      {/* Two-Column Market Data Notice Box */}
      <div className="historical-notice-box" role="status" aria-label="Market data notice">
        <div className="notice-box-left">
          <strong>Market</strong>
          <strong>Data.</strong>
        </div>
        <div className="notice-box-right">
          {snapshot ? (
            <p>
              Daily data dated {formatDate(snapshot.snapshot_date)} sourced from {snapshot.source_name || 'historical market snapshot'}.
              {snapshot.is_stale ? ' (Snapshot is stale, latest trading session may be pending).' : ' EOD updates active on trading days.'}
            </p>
          ) : (
            <p>
              No trading snapshot has been ingested for this instrument series on the latest market date. Security master details remain verified.
            </p>
          )}
        </div>
      </div>

      {/* Horizontal Tabs with 'Planned' badges */}
      <nav className="company-tabs-nav" aria-label="Company detail sections">
        <ul className="company-tabs-list" role="tablist">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.key || (tab.key === 'snapshot' && activeTab === 'overview');
            return (
              <li key={tab.key} role="presentation">
                <button
                  type="button"
                  role="tab"
                  id={`tab-${tab.key}`}
                  aria-selected={isActive}
                  aria-controls={`tabpanel-${tab.key}`}
                  className={`tab-btn ${isActive ? 'tab-btn-active' : ''}`}
                  onClick={() => setActiveTab(tab.key)}
                >
                  <span className="tab-label">{tab.label}</span>
                  {tab.isPlanned && <span className="tab-planned-pill">Planned</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Tab Panels */}
      {activeTab === 'snapshot' || activeTab === 'overview' ? (
        <div id="tabpanel-snapshot" role="tabpanel" aria-labelledby="tab-snapshot">
          {snapshot ? (
            <div className="snapshot-content-block">
              {/* Hero Price Section */}
              <div className="hero-price-section">
                <div className="price-primary-row">
                  <span className="hero-price-value" id="ltp-display-value">
                    {formatCurrencyINR(snapshot.ltp)}
                  </span>
                  {pctChange && (
                    <span
                      className={`hero-price-delta delta-${pctChange.direction}`}
                      role="status"
                      aria-label={pctChange.accessibleText}
                    >
                      <span className="delta-arrow" aria-hidden="true">{pctChange.symbol}</span>
                      <span className="delta-num">{pctChange.formatted}</span>
                      <span className="delta-ref">vs prev close</span>
                    </span>
                  )}
                </div>
                <div className="price-sub-caption">
                  <span className="ltp-text-label">Last-Traded Price (LTP)</span>
                  <span className="caption-dot">·</span>
                  <span className="caption-tag">SNAPSHOT DATED</span>
                  <span className="caption-date">{formatDate(snapshot.snapshot_date)}</span>
                </div>
              </div>

              {/* Three Metrics Strip */}
              <div className="three-metrics-strip">
                <div className="metric-col">
                  <div className="metric-col-label">Market Capitalization</div>
                  <div className="metric-col-value">
                    {snapshot.market_capitalization_crores
                      ? `₹${formatPlainDecimal(snapshot.market_capitalization_crores, 2)} Cr`
                      : '— Cr'}
                  </div>
                  <div className="metric-subtext-provenance">
                    {snapshot.market_capitalization_crores ? (
                      <>
                        <span title={snapshot.market_cap_explanation || undefined}>
                          {snapshot.market_cap_price_basis || 'LTP'} ({formatDate(snapshot.market_cap_price_date || snapshot.snapshot_date)}) × {formatShareCount(snapshot.share_count)} shares
                          {snapshot.share_count_date ? ` (${formatDate(snapshot.share_count_date)})` : ''}
                        </span>
                        {snapshot.share_count_status === 'stale' && (
                          <span className="stale-badge" title="Share count filing is older than 120 days">Stale &gt;120d</span>
                        )}
                      </>
                    ) : (
                      <span>No dated share count</span>
                    )}
                  </div>
                </div>

                <div className="metric-col">
                  <div className="metric-col-label">Volume</div>
                  <div className="metric-col-value">
                    {snapshot.volume_lakhs
                      ? `${formatPlainDecimal(snapshot.volume_lakhs, 2)} lakh`
                      : snapshot.volume != null
                      ? `${formatPlainDecimal(snapshot.volume / 100000, 2)} lakh`
                      : '— lakh'}
                  </div>
                  <div className="metric-subtext-provenance">
                    {snapshot.volume != null ? (
                      <span>{snapshot.volume.toLocaleString('en-IN')} shares</span>
                    ) : (
                      <span>—</span>
                    )}
                  </div>
                </div>

                <div className="metric-col">
                  <div className="metric-col-label">Traded Value</div>
                  <div className="metric-col-value">
                    {snapshot.traded_value_crores
                      ? `₹${formatPlainDecimal(snapshot.traded_value_crores, 2)} Cr`
                      : snapshot.turnover != null
                      ? `₹${formatPlainDecimal(parseFloat(String(snapshot.turnover)) / 10000000, 2)} Cr`
                      : '— Cr'}
                  </div>
                  <div className="metric-subtext-provenance">
                    {snapshot.turnover != null ? (
                      <span>Turnover ₹{parseFloat(String(snapshot.turnover)).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
                    ) : (
                      <span>—</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Interactive Price & Volume Chart */}
              <div className="snapshot-chart-container" style={{ marginTop: '24px' }}>
                <PriceChart instrumentId={instrument.instrument_id} symbol={instrument.symbol} />
              </div>
            </div>
          ) : (
            <div className="snapshot-unavailable-card" role="alert">
              <div className="state-header-tag">NO SNAPSHOT</div>
              <h3 className="unavailable-title">No end-of-day snapshot for this instrument</h3>
              <div className="unavailable-badge">Market Snapshot Data Unavailable</div>
              <p className="unavailable-message">
                Company details are available; price and volume fields show Not available rather than a guess.
              </p>
            </div>
          )}

          {/* Security Master Section */}
          <section className="security-master-section" aria-labelledby="security-master-heading">
            <h2 id="security-master-heading" className="security-master-title">
              SECURITY MASTER
            </h2>

            <div className="master-grid-box">
              <div className="master-col">
                <div className="master-row">
                  <span className="master-key">Symbol</span>
                  <span className="master-val">{instrument.symbol}</span>
                </div>
                <div className="master-row">
                  <span className="master-key">Exchange</span>
                  <span className="master-val">{instrument.exchange}</span>
                </div>
                <div className="master-row">
                  <span className="master-key">ISIN</span>
                  <span className="master-val isin-font">{instrument.isin || '—'}</span>
                </div>
                <div className="master-row">
                  <span className="master-key">Face / paid-up</span>
                  <span className="master-val">
                    {formatCurrencyINR(instrument.face_value)} / {formatCurrencyINR(instrument.paid_up_value)}
                  </span>
                </div>
                <div className="master-row">
                  <span className="master-key">Status</span>
                  <span className="master-val">
                    {instrument.is_active ? 'Active on exchange' : 'Suspended'}
                  </span>
                </div>
              </div>

              <div className="master-col">
                <div className="master-row">
                  <span className="master-key">Series</span>
                  <span className="master-val">{instrument.series}</span>
                </div>
                <div className="master-row">
                  <span className="master-key">Instrument type</span>
                  <span className="master-val">{instrument.instrument_type}</span>
                </div>
                <div className="master-row">
                  <span className="master-key">Listed</span>
                  <span className="master-val">{formatDate(instrument.listing_date)}</span>
                </div>
                <div className="master-row">
                  <span className="master-key">Market lot</span>
                  <span className="master-val">{instrument.market_lot ?? 1}</span>
                </div>
                <div className="master-row">
                  <span className="master-key">Record IDs</span>
                  <span className="master-val">#{instrument.company_id ?? instrument.instrument_id} · #{instrument.instrument_id}</span>
                </div>
              </div>
            </div>
          </section>
        </div>
      ) : (
        /* Planned Tab View */
        <div id={`tabpanel-${activeTab}`} role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
          {activeTab === 'prices' && (
            <div className="prices-tab-view" style={{ marginTop: '16px' }}>
              <div style={{ marginBottom: '16px' }}>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 4px 0' }}>
                  {instrument.symbol} · Historical Daily Prices &amp; Volume
                </h2>
                <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', margin: 0 }}>
                  Interactive candlestick OHLCV and trading volume history.
                </p>
              </div>
              <PriceChart instrumentId={instrument.instrument_id} symbol={instrument.symbol} />
            </div>
          )}

          {activeTab === 'technical' && (
            <PlannedFeature
              title={`${instrument.symbol} · Technical Analysis & Indicators`}
              description="Interactive charting with technical overlays (SMA, EMA, RSI, MACD, Bollinger Bands) and pattern detection."
              stageBadge="Stage 2: Technicals"
              roadmapDetails={[
                'Standard moving averages (20, 50, 100, 200 SMA/EMA)',
                'Momentum indicators including Relative Strength Index (RSI)',
                'Volume-weighted average price (VWAP) and delivery volume trends',
              ]}
              backLink="#"
              backText="← Back to Overview"
            />
          )}

          {activeTab === 'fundamentals' && (
            <PlannedFeature
              title={`${instrument.company_name} · Company Fundamentals`}
              description="Balance sheets, profit & loss statements, cash flow statements, and valuation ratios (P/E, P/B, EV/EBITDA, ROE, ROCE)."
              stageBadge="Stage 3: Fundamentals"
              roadmapDetails={[
                'Normalized financial statements from official XBRL filings',
                'Valuation and profitability ratios with historical peer percentiles',
                'Shareholding patterns and institutional ownership changes',
              ]}
              backLink="#"
              backText="← Back to Overview"
            />
          )}

          {activeTab === 'peers' && (
            <PlannedFeature
              title={`${instrument.symbol} · Industry & Sector Peers`}
              description="Comparative valuation and performance benchmarks against sector competitors listed on the National Stock Exchange."
              stageBadge="Stage 3: Sector Benchmarks"
              roadmapDetails={[
                'Sector classification and market capitalization rankings',
                'Peer valuation matrix (P/E, P/B, Dividend Yield, Sales Growth)',
                'Relative price momentum and performance heatmaps',
              ]}
              backLink="#"
              backText="← Back to Overview"
            />
          )}

          {activeTab === 'news' && (
            <PlannedFeature
              title={`${instrument.company_name} · News & Disclosures`}
              description="Curated regulatory corporate filings, exchange announcements, board meetings, and verified financial news feeds."
              stageBadge="Stage 4: Document Intelligence"
              roadmapDetails={[
                'Real-time NSE corporate announcement ingestion',
                'Earnings call transcript indexing and investor presentation summaries',
                'Sentiment classification and event impact tagging',
              ]}
              backLink="#"
              backText="← Back to Overview"
            />
          )}

          {activeTab === 'documents' && (
            <PlannedFeature
              title={`${instrument.company_name} · Regulatory Documents & Reports`}
              description="Annual reports, quarterly financial filings, and investor disclosures organized for semantic search and retrieval."
              stageBadge="Stage 4: Document Intelligence"
              roadmapDetails={[
                'Automated PDF annual report ingestion from exchange filings',
                'Table and footnote extraction using OCR and document parsing',
                'Vector embeddings for contextual semantic retrieval',
              ]}
              backLink="#"
              backText="← Back to Overview"
            />
          )}

          {activeTab === 'research' && (
            <PlannedFeature
              title={`${instrument.company_name} · Evidence-Grounded AI Research`}
              description="Deep-dive equity research reports synthesized by autonomous LLM agents with verifiable citations to source documents and official filings."
              stageBadge="Stage 5: Autonomous AI Research Layer"
              roadmapDetails={[
                'Multi-source Retrieval-Augmented Generation (RAG) over verified filings',
                'Strict hallucination prevention with clickable source citations',
                'Thesis generation, risk factor evaluation, and competitive moats analysis',
              ]}
              backLink="#"
              backText="← Back to Overview"
            />
          )}
        </div>
      )}
    </div>
  );
};
