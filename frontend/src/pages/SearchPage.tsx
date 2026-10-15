import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate, useLocation } from 'react-router-dom';
import { SearchResults } from '../components/SearchResults';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorMessage } from '../components/ErrorMessage';
import { searchInstruments, ApiRequestError } from '../services/api';
import type { InstrumentSearchResult, ApiError } from '../types/instrument';

const PAGE_SIZE = 20;

export const SearchPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const queryParam = searchParams.get('q') || '';
  const offsetParam = parseInt(searchParams.get('offset') || '0', 10);

  const [results, setResults] = useState<InstrumentSearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);

  const fetchResults = useCallback(async (query: string, offset: number) => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setHasSearched(false);
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setError(null);
    setHasSearched(true);

    try {
      const data = await searchInstruments(trimmed, PAGE_SIZE, offset, controller.signal);
      setResults(data);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      if (err instanceof ApiRequestError) {
        setError({ message: err.message, status: err.status });
      } else {
        setError({ message: 'An unexpected error occurred while searching instruments.' });
      }
      setResults([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (queryParam) {
      fetchResults(queryParam, offsetParam);
    } else {
      setResults([]);
      setHasSearched(false);
      setError(null);
    }
  }, [queryParam, offsetParam, fetchResults]);

  const location = useLocation();

  const handleSelectInstrument = (instrumentId: number) => {
    const fromSearch = location.search || (queryParam ? `?q=${encodeURIComponent(queryParam)}` : '');
    navigate(`/stocks/${instrumentId}/overview`, {
      state: { fromSearch },
    });
  };

  const handlePageChange = (newOffset: number) => {
    setSearchParams({ q: queryParam, offset: String(newOffset) });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="search-page-container">
      {error && (
        <ErrorMessage
          title="Search Request Error"
          message={error.message}
          status={error.status}
          onRetry={() => fetchResults(queryParam, offsetParam)}
        />
      )}

      {isLoading ? (
        <LoadingSkeleton type="table" />
      ) : hasSearched ? (
        <SearchResults
          results={results}
          query={queryParam}
          limit={PAGE_SIZE}
          offset={offsetParam}
          onSelectInstrument={handleSelectInstrument}
          onPageChange={handlePageChange}
          isLoading={isLoading}
        />
      ) : (
        <div className="search-empty-state" role="region" aria-label="Welcome">
          <div className="empty-icon" aria-hidden="true">
            <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M3 3v18h18" />
              <path d="m19 9-5 5-4-4-3 3" />
            </svg>
          </div>
          <h2 className="empty-title">TickerWise</h2>
          <p className="empty-message">
            Search across 2,600+ NSE-listed companies and active trading instruments.
          </p>
          <p className="empty-suggestion">
            Try searching by symbol like <code>RELIANCE</code>, <code>TCS</code>, <code>INFY</code>, <code>HDFCBANK</code>, or by company name.
          </p>
        </div>
      )}
    </div>
  );
};
