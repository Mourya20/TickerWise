import React, { useEffect, useState } from 'react';
import type {
  CorporateAction,
  InstrumentDetailResponse,
  ShareCountHistory,
} from '../types/instrument';
import {
  getInstrumentCorporateActions,
  getInstrumentShareCounts,
} from '../services/api';
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
  | 'actions'
  | 'technical'
  | 'fundamentals'
  | 'peers'
  | 'news'
  | 'documents'
  | 'research';

const TABS: { key: TabKey; label: string; isPlanned: boolean }[] = [
  { key: 'snapshot', label: 'Snapshot', isPlanned: false },
  { key: 'prices', label: 'Prices', isPlanned: false },
  { key: 'actions', label: 'Corporate Actions', isPlanned: false },
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

  const [corporateActions, setCorporateActions] = useState<CorporateAction[] | null>(null);
  const [actionsLoading, setActionsLoading] = useState<boolean>(false);
  const [actionsError, setActionsError] = useState<string | null>(null);

  const [shareCounts, setShareCounts] = useState<ShareCountHistory[] | null>(null);
  const [shareCountsLoading, setShareCountsLoading] = useState<boolean>(false);
  const [shareCountsError, setShareCountsError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab !== 'actions') return;

    let isMounted = true;
    const controller = new AbortController();

    async function loadData() {
      setActionsLoading(true);
      setActionsError(null);
      setShareCountsLoading(true);
      setShareCountsError(null);

      try {
        const [actionsData, sharesData] = await Promise.allSettled([
          getInstrumentCorporateActions(instrument.instrument_id, controller.signal),
          getInstrumentShareCounts(instrument.instrument_id, controller.signal),
        ]);

        if (!isMounted) return;

        if (actionsData.status === 'fulfilled') {
          setCorporateActions(actionsData.value);
        } else {
          setActionsError('Failed to load corporate actions.');
        }

        if (sharesData.status === 'fulfilled') {
          setShareCounts(sharesData.value);
        } else {
          setShareCountsError('Failed to load share count history.');
        }
      } finally {
        if (isMounted) {
          setActionsLoading(false);
          setShareCountsLoading(false);
        }
      }
    }

    loadData();

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, [activeTab, instrument.instrument_id]);

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
          {instrument.listing_date ? (
            <>
              <span className="meta-dot">·</span>
              <span>LISTED {formatDate(instrument.listing_date)}</span>
            </>
          ) : instrument.first_seen_date ? (
            <>
              <span className="meta-dot">·</span>
              <span>FIRST SEEN {formatDate(instrument.first_seen_date)}</span>
            </>
          ) : null}
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
                <PriceChart
                  instrumentId={instrument.instrument_id}
                  symbol={instrument.symbol}
                  latestDate={instrument.snapshot?.snapshot_date}
                />
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
                  {instrument.symbol} · Historical Daily Prices & Volume
                </h2>
                <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', margin: 0 }}>
                  Interactive candlestick OHLCV and trading volume history.
                </p>
              </div>
              <PriceChart
                instrumentId={instrument.instrument_id}
                symbol={instrument.symbol}
                latestDate={instrument.snapshot?.snapshot_date}
              />
            </div>
          )}

          {activeTab === 'actions' && (
            <div className="corporate-actions-tab-view" style={{ marginTop: '16px' }}>
              <div style={{ marginBottom: '20px' }}>
                <h2 data-testid="corporate-actions-heading" style={{ fontSize: '1.15rem', fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 6px 0' }}>
                  {instrument.symbol} · Corporate Actions & Share Capital History
                </h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
                  Verified exchange corporate actions and dated share capital filings used for defensible market capitalization calculation.
                </p>
              </div>

              {/* Corporate Actions Table */}
              <div style={{ marginBottom: '32px' }}>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>Exchange Corporate Actions</span>
                  {corporateActions && (
                    <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '12px', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                      {corporateActions.length} recorded
                    </span>
                  )}
                </h3>

                {actionsLoading ? (
                  <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading corporate actions...</div>
                ) : actionsError ? (
                  <div style={{ padding: '16px', color: 'var(--color-loss)', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '6px' }}>{actionsError}</div>
                ) : !corporateActions || corporateActions.length === 0 ? (
                  <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-surface)', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                    No corporate actions recorded for this instrument.
                  </div>
                ) : (
                  <div className="table-responsive">
                    <table className="results-table" aria-label="Corporate Actions Table">
                      <thead>
                        <tr>
                          <th>Event Date</th>
                          <th>Event Type</th>
                          <th>Details & Terms</th>
                          <th>Status</th>
                          <th>Source Reference</th>
                        </tr>
                      </thead>
                      <tbody>
                        {corporateActions.map((act) => {
                          const eventDate = act.effective_date || act.ex_date || act.allotment_date || act.record_date || act.announcement_date;
                          let detailsStr = act.raw_subject || '—';
                          if (act.event_type === 'bonus' && act.ratio_num && act.ratio_den) {
                            detailsStr = `Bonus Issue ${act.ratio_num}:${act.ratio_den}`;
                          } else if (act.event_type === 'split' && act.face_value_from && act.face_value_to) {
                            detailsStr = `Stock Split FV ₹${act.face_value_from} to ₹${act.face_value_to}`;
                          } else if (act.event_type === 'split' && act.ratio_num && act.ratio_den) {
                            detailsStr = `Stock Split ${act.ratio_num}:${act.ratio_den}`;
                          } else if (act.cash_amount) {
                            detailsStr = `Dividend ₹${act.cash_amount} per share`;
                          } else if (act.actual_shares) {
                            detailsStr = `${act.event_type.toUpperCase()} Allotment: ${act.actual_shares.toLocaleString('en-IN')} shares`;
                          }
                          return (
                            <tr key={act.id}>
                              <td style={{ whiteSpace: 'nowrap' }}>{eventDate ? formatDate(eventDate) : '—'}</td>
                              <td>
                                <span style={{
                                  display: 'inline-block',
                                  padding: '2px 8px',
                                  borderRadius: '4px',
                                  fontSize: '0.75rem',
                                  fontWeight: 600,
                                  textTransform: 'uppercase',
                                  background: act.event_type === 'bonus' || act.event_type === 'split' ? 'rgba(59, 130, 246, 0.15)' : 'rgba(255, 255, 255, 0.08)',
                                  color: act.event_type === 'bonus' || act.event_type === 'split' ? '#60a5fa' : 'var(--text-primary)',
                                }}>
                                  {act.event_type}
                                </span>
                              </td>
                              <td>{detailsStr}</td>
                              <td>
                                <span style={{
                                  display: 'inline-block',
                                  padding: '2px 8px',
                                  borderRadius: '4px',
                                  fontSize: '0.72rem',
                                  textTransform: 'capitalize',
                                  background: act.status === 'completed' || act.status === 'allotted' ? 'rgba(34, 197, 94, 0.15)' : 'rgba(234, 179, 8, 0.15)',
                                  color: act.status === 'completed' || act.status === 'allotted' ? '#4ade80' : '#facc15',
                                }}>
                                  {act.status}
                                </span>
                              </td>
                              <td style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                                {act.source_name || act.source_reference || 'TejHQ'}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Share Capital History Table */}
              <div>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>Official Shareholding Pattern Filings</span>
                  {shareCounts && (
                    <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '12px', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                      {shareCounts.length} filings
                    </span>
                  )}
                </h3>

                {shareCountsLoading ? (
                  <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading share capital history...</div>
                ) : shareCountsError ? (
                  <div style={{ padding: '16px', color: 'var(--color-loss)', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '6px' }}>{shareCountsError}</div>
                ) : !shareCounts || shareCounts.length === 0 ? (
                  <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-surface)', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                    No shareholding pattern filings found.
                  </div>
                ) : (
                  <div className="table-responsive">
                    <table className="results-table" aria-label="Shareholding Pattern Table">
                      <thead>
                        <tr>
                          <th>Quarter Ended</th>
                          <th>Reported Shares</th>
                          <th>Filing Method</th>
                          <th>Validation</th>
                          <th>Notes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shareCounts.map((sc) => (
                          <tr key={sc.id}>
                            <td style={{ whiteSpace: 'nowrap' }}>{formatDate(sc.reporting_date)}</td>
                            <td style={{ fontWeight: 600 }}>{sc.reported_share_count.toLocaleString('en-IN')}</td>
                            <td>
                              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                {sc.extraction_method === 'directly_reported' ? 'Direct XBRL' : 'Derived'}
                              </span>
                            </td>
                            <td>
                              <span style={{
                                display: 'inline-block',
                                padding: '2px 8px',
                                borderRadius: '4px',
                                fontSize: '0.72rem',
                                background: sc.validation_status === 'valid' ? 'rgba(34, 197, 94, 0.15)' : 'rgba(234, 179, 8, 0.15)',
                                color: sc.validation_status === 'valid' ? '#4ade80' : '#facc15',
                              }}>
                                {sc.validation_status}
                              </span>
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                              {sc.corporate_action_details || '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
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
