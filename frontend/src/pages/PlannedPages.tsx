import React from 'react';
import { PlannedFeature } from '../components/PlannedFeature';

export const ScreenerPage: React.FC = () => (
  <PlannedFeature
    title="Stock screener"
    description="Filtering and ranking stocks is part of the roadmap, but nothing here works yet. No sample data is shown."
    roadmapItem="ROADMAP ITEM 4 · GENERAL ANALYSIS, SCREENING AND HISTORICAL RESEARCH"
    backLink="/search"
    backText="Go to search"
  />
);

export const MarketOverviewPage: React.FC = () => (
  <PlannedFeature
    title="Market Overview & Macro Intelligence"
    description="Broad market breadth, benchmark index performance (NIFTY 50, NIFTY NEXT 50, NIFTY 500), advancing vs declining stocks, and sector turnover heatmaps."
    stageBadge="Stage 2 Planned"
    roadmapDetails={[
      'Real-time and EOD benchmark index tracking',
      'Advance-decline ratio and market breadth indicators',
      'Top gainers, losers, and most active securities by value and volume',
      'Exchange-wide turnover and FII/DII institutional activity summaries',
    ]}
  />
);

export const SectorsPage: React.FC = () => (
  <PlannedFeature
    title="Sector & Industry Classification Analysis"
    description="Sectoral indices performance, industry group aggregation, and relative sector strength across Indian financial markets."
    stageBadge="Stage 3 Planned"
    roadmapDetails={[
      'NIFTY Sectoral performance comparison (Bank, Auto, IT, Pharma, FMCG, Metal, Energy)',
      'Sector valuation percentiles and historical price-to-earnings heatmaps',
      'Constituent weighted contribution and dispersion metrics',
    ]}
  />
);

export const AnalysisPage: React.FC = () => (
  <PlannedFeature
    title="Technical & Quantitative Analysis Suite"
    description="Comprehensive quantitative analysis, risk metrics, rolling volatility, Sharpe ratios, and algorithmic strategy backtesting."
    stageBadge="Stage 2–3 Planned"
    roadmapDetails={[
      'Historical volatility and beta calculations against NIFTY 50',
      'Drawdown analysis and value-at-risk (VaR) estimations',
      'Automated technical pattern recognition (support/resistance, channels, wedges)',
    ]}
  />
);

export const NewsDocumentsPage: React.FC = () => (
  <PlannedFeature
    title="Corporate News & Regulatory Disclosures"
    description="Curated regulatory announcements from the National Stock Exchange, board meeting notifications, dividend declarations, and corporate actions."
    stageBadge="Stage 4 Planned"
    roadmapDetails={[
      'Automated NSE corporate filing feeds and insider trading disclosures',
      'Earnings call transcripts and investor presentations',
      'Event-driven news clustering and impact scoring',
    ]}
  />
);

export const DocumentsPage: React.FC = () => (
  <PlannedFeature
    title="Financial Document Repository & Annual Reports"
    description="Centralized repository of corporate annual reports, quarterly financial filings, and credit rating agency releases."
    stageBadge="Stage 4 Planned"
    roadmapDetails={[
      'Automated PDF annual report ingestion and text extraction',
      'Financial statement footnote indexing and auditor commentary extraction',
      'Multi-year document comparison and change tracking',
    ]}
  />
);

export const AiResearchPage: React.FC = () => (
  <PlannedFeature
    title="Evidence-Grounded AI Research Layer"
    description="Autonomous AI equity research assistant synthesizing verifiable investment insights grounded strictly in official exchange filings and audited financial statements."
    stageBadge="Stage 5 Planned"
    roadmapDetails={[
      'Retrieval-Augmented Generation (RAG) over verified corporate annual reports',
      'Zero-hallucination policy with exact document paragraph citations',
      'Automated earnings release summarization and guidance tracking',
      'Competitive moats analysis and forensic accounting anomaly detection',
    ]}
  />
);

export const SystemHealthPage: React.FC = () => (
  <PlannedFeature
    title="System Health, Telemetry & Ingestion Diagnostics"
    description="Operational status of backend services, MySQL database connections, automated EOD ingestion cron runs, and external provider feeds."
    stageBadge="System Telemetry"
    roadmapDetails={[
      'Database connection pool metrics and row counts (Companies, Instruments, Snapshots)',
      'TejHQ EOD pipeline status and published trading date verification',
      'Windows Task Scheduler execution history and review directory exports',
      '0xramm supplementary provider gate verification and security logs',
    ]}
  />
);

export const NotFoundPage: React.FC = () => (
  <div className="not-found-container" role="region" aria-label="Page not found">
    <div className="not-found-card">
      <div className="not-found-icon" aria-hidden="true">404</div>
      <h1 className="not-found-title">Page Not Found</h1>
      <p className="not-found-message">
        The requested path does not exist on the TickerWise workbench.
      </p>
      <div className="not-found-actions">
        <a href="/search" className="btn-primary">
          ← Return to Search & Instruments
        </a>
      </div>
    </div>
  </div>
);
