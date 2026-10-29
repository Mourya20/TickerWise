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
  market_cap_price_basis?: string | null;
  market_cap_price_date?: string | null;
  share_count?: number | null;
  share_count_date?: string | null;
  share_count_source?: string | null;
  share_count_method?: string | null;
  share_count_status?: string | null;
  market_cap_explanation?: string | null;
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

export interface PriceBar {
  trading_date: string;
  open: string | number | null;
  high: string | number | null;
  low: string | number | null;
  close: string | number | null;
  ltp: string | number | null;
  prev_close: string | number | null;
  volume: number | null;
  volume_lakhs: string | number | null;
  turnover: string | number | null;
  traded_value_crores: string | number | null;
  percentage_change_pct: string | number | null;
  trade_count?: number | null;
  source_name?: string | null;
}

export interface ShareCountHistory {
  id: number;
  instrument_id: number;
  symbol: string;
  series: string;
  share_class: string;
  reported_share_count: number;
  fully_paid_shares?: number | null;
  partly_paid_shares?: number | null;
  source_capital_amount?: string | number | null;
  face_value?: string | number | null;
  reporting_date: string;
  filing_date?: string | null;
  retrieved_at: string;
  source_name?: string | null;
  extraction_method: string;
  validation_status: string;
  corporate_action_adjusted: boolean;
  corporate_action_details?: string | null;
}

export interface CorporateAction {
  id: number;
  instrument_id: number;
  exchange: string;
  symbol: string;
  event_type: string;
  dedup_key: string;
  announcement_date?: string | null;
  record_date?: string | null;
  ex_date?: string | null;
  issue_open_date?: string | null;
  issue_close_date?: string | null;
  allotment_date?: string | null;
  completion_date?: string | null;
  effective_date?: string | null;
  ratio_num?: number | null;
  ratio_den?: number | null;
  face_value_from?: string | number | null;
  face_value_to?: string | number | null;
  cash_amount?: string | number | null;
  proposed_shares?: number | null;
  proposed_amount?: string | number | null;
  actual_shares?: number | null;
  actual_amount?: string | number | null;
  status: string;
  source_id: number;
  source_name?: string | null;
  source_reference?: string | null;
  retrieved_at: string;
  raw_subject?: string | null;
  validation_status: string;
  notes?: string | null;
}

export interface CorporateActionSyncStatusResponse {
  instrument_id: number;
  symbol: string;
  status: 'synced' | 'empty' | 'not_synced' | 'failed' | 'partial';
  last_checked_at?: string | null;
  last_success_at?: string | null;
  events_count: number;
  provider_name: string;
  error_message?: string | null;
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
  first_seen_date?: string | null;
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
