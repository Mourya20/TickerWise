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
  percentage_change_pct: string | null;
  market_capitalization_crores: string | null;
  volume_lakhs: string | null;
  traded_value_crores: string | null;
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

export interface ApiError {
  message: string;
  status?: number;
}
