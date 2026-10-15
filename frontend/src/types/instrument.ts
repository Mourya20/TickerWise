export interface InstrumentSearchResult {
  instrument_id: number;
  company_name: string;
  exchange: string;
  symbol: string;
  series: string;
  isin: string | null;
  is_active: boolean;
}

export interface MarketSnapshotResponse {
  snapshot_date: string;
  ltp: string | null;
  close?: string | null;
  open?: string | null;
  high?: string | null;
  low?: string | null;
  prev_close?: string | null;
  percentage_change_pct: string | null;
  is_calculated_change?: boolean;
  market_capitalization_crores: string | null;
  volume_lakhs: string | null;
  traded_value_crores: string | null;
  volume?: number | null;
  turnover?: string | null;
  trade_count?: number | null;
  source_name?: string | null;
  last_ingested_at?: string | null;
  is_stale?: boolean;
  freshness_status?: 'fresh' | 'stale' | 'incomplete' | 'unknown' | string;
}

export interface InstrumentDetailResponse {
  instrument_id: number;
  company_id: number;
  company_name: string;
  exchange: string;
  symbol: string;
  series: string;
  instrument_type: string;
  isin: string | null;
  listing_date: string | null;
  paid_up_value: string | null;
  market_lot: number | null;
  face_value: string | null;
  is_active: boolean;
  snapshot: MarketSnapshotResponse | null;
}

export interface ProviderInfo {
  name: string;
  source_type: string;
  is_active: boolean;
  source_url: string | null;
  terms_url: string | null;
  permission_verified: boolean;
}

export interface ProviderStatusResponse {
  primary_provider: string;
  provider_availability: 'available' | 'unavailable' | 'unknown' | string;
  latest_published_trading_date: string | null;
  pipeline_stage: string | null;
  prices_published_at: string | null;
  derived_published_at: string | null;
  is_fresh: boolean;
  last_successful_ingestion_date: string | null;
  last_successful_ingestion_completed_at: string | null;
  last_run_status: string | null;
  last_run_completed_at: string | null;
  incomplete_coverage: boolean;
  is_local_stale: boolean;
  providers: ProviderInfo[];
  last_local_ingestion_date?: string | null;
  last_local_ingestion_status?: string | null;
}

export interface ApiError {
  message: string;
  status?: number;
}
