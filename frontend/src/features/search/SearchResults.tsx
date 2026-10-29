import React from 'react';
import type { InstrumentSearchResult } from '../../types/instrument';

export interface SearchResultsProps {
  results: InstrumentSearchResult[];
  query: string;
  limit: number;
  offset: number;
  onSelectInstrument: (instrumentId: number) => void;
  onPageChange: (newOffset: number) => void;
  isLoading?: boolean;
}

export const SearchResults: React.FC<SearchResultsProps> = ({
  results,
  query,
  limit,
  offset,
  onSelectInstrument,
  onPageChange,
  isLoading = false,
}) => {
  if (results.length === 0) {
    return (
      <div className="search-empty-state" role="region" aria-label="Search results">
        <div className="state-header-tag">NO MATCHES</div>
        <h2 className="empty-title">Nothing found for "{query}"</h2>
        <p className="empty-message">No instruments found</p>
        <p className="empty-suggestion">
          Try a company name, or part of an NSE symbol.
        </p>
      </div>
    );
  }

  const hasNextPage = results.length === limit;
  const hasPrevPage = offset > 0;
  const startIdx = offset + 1;
  const endIdx = offset + results.length;

  return (
    <div className="search-results-container" role="region" aria-label="Search results">
      <div className="results-header">
        <div className="results-title-group">
          <h1 className="results-heading" id="results-for-query-heading">
            RESULTS FOR "{query}"
          </h1>
          <span className="results-range-text">
            Displaying instruments {startIdx}–{endIdx}
          </span>
        </div>
        <span className="results-badge">NSE Equities</span>
      </div>

      <div className="table-responsive">
        <table className="results-table" aria-label="Search results table">
          <thead>
            <tr>
              <th scope="col" className="col-symbol">Symbol</th>
              <th scope="col" className="col-company">Company Name</th>
              <th scope="col" className="col-series">Series</th>
              <th scope="col" className="col-exchange">Exchange</th>
              <th scope="col" className="col-isin">ISIN</th>
              <th scope="col" className="col-status">Status</th>
              <th scope="col" className="col-action">Action</th>
            </tr>
          </thead>
          <tbody>
            {results.map((item) => (
              <tr
                key={item.instrument_id}
                className="result-row"
                tabIndex={0}
                role="button"
                id={`instrument-row-${item.instrument_id}`}
                aria-label={`Select ${item.company_name} (${item.symbol}, Series ${item.series})`}
                onClick={() => onSelectInstrument(item.instrument_id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelectInstrument(item.instrument_id);
                  }
                }}
              >
                <td className="col-symbol">
                  <div className="symbol-cell">
                    <span className="symbol-code">{item.symbol}</span>
                    <span className="series-tag">{item.series}</span>
                  </div>
                </td>
                <td className="col-company">
                  <div className="company-name">{item.company_name}</div>
                </td>
                <td className="col-series">
                  <span className="badge badge-subtle">{item.series}</span>
                </td>
                <td className="col-exchange">
                  <span className="badge badge-exchange">{item.exchange}</span>
                </td>
                <td className="col-isin">
                  <span className="isin-code">{item.isin || '—'}</span>
                </td>
                <td className="col-status">
                  <span className={`status-pill ${item.is_active ? 'active' : 'inactive'}`}>
                    <span className="status-pill-dot" />
                    {item.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="col-action">
                  <button
                    type="button"
                    className="select-instrument-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectInstrument(item.instrument_id);
                    }}
                    id={`view-btn-${item.instrument_id}`}
                    aria-label={`View details for ${item.symbol}`}
                  >
                    View Details →
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="pagination-bar">
        <div className="pagination-info">
          PAGE {Math.floor(offset / limit) + 1} · MULTIPLE SERIES FOR A SYMBOL LIST AS SEPARATE ROWS
        </div>
        <div className="pagination-controls">
          <button
            type="button"
            id="prev-page-btn"
            className="pagination-btn"
            disabled={!hasPrevPage || isLoading}
            onClick={() => onPageChange(Math.max(0, offset - limit))}
            aria-label="Previous page of results"
          >
            ← Prev
          </button>
          <button
            type="button"
            id="next-page-btn"
            className="pagination-btn"
            disabled={!hasNextPage || isLoading}
            onClick={() => onPageChange(offset + limit)}
            aria-label="Next page of results"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
};
