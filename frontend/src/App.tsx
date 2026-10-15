import { useState, useEffect, useRef, useCallback } from 'react';
import { Header } from './components/Header';
import { SearchBar } from './components/SearchBar';
import { SearchResults } from './components/SearchResults';
import { InstrumentDetail } from './components/InstrumentDetail';
import { LoadingSkeleton } from './components/LoadingSkeleton';
import { ErrorMessage } from './components/ErrorMessage';
import {
  checkHealth,
  searchInstruments,
  getInstrumentDetail,
  ApiRequestError,
} from './services/api';
import type {
  InstrumentSearchResult,
  InstrumentDetailResponse,
  ApiError,
} from './types/instrument';

const PAGE_SIZE = 20;

export function App() {
  const [apiStatus, setApiStatus] = useState<'checking' | 'connected' | 'error'>('checking');
  const [query, setQuery] = useState('');
  const [hasSearched, setHasSearched] = useState(false);
  const [searchResults, setSearchResults] = useState<InstrumentSearchResult[]>([]);
  const [offset, setOffset] = useState(0);
  const [selectedInstrumentId, setSelectedInstrumentId] = useState<number | null>(null);
  const [instrumentDetail, setInstrumentDetail] = useState<InstrumentDetailResponse | null>(null);
  const [isLoadingSearch, setIsLoadingSearch] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const searchAbortControllerRef = useRef<AbortController | null>(null);
  const detailAbortControllerRef = useRef<AbortController | null>(null);

  // Check backend health on initial load
  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();

    checkHealth(controller.signal)
      .then(() => {
        if (isMounted) setApiStatus('connected');
      })
      .catch((err) => {
        if (isMounted && !(err instanceof DOMException && err.name === 'AbortError')) {
          setApiStatus('error');
        }
      });

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, []);

  // Execute Search
  const executeSearch = useCallback(async (newQuery: string, newOffset: number = 0) => {
    const trimmed = newQuery.trim();
    if (!trimmed) return;

    if (searchAbortControllerRef.current) {
      searchAbortControllerRef.current.abort();
    }
    const controller = new AbortController();
    searchAbortControllerRef.current = controller;

    setIsLoadingSearch(true);
    setError(null);
    setSelectedInstrumentId(null);
    setInstrumentDetail(null);
    setQuery(trimmed);
    setOffset(newOffset);
    setHasSearched(true);

    try {
      const results = await searchInstruments(trimmed, PAGE_SIZE, newOffset, controller.signal);
      setSearchResults(results);
      setApiStatus('connected');
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      if (err instanceof ApiRequestError) {
        setError({ message: err.message, status: err.status });
      } else {
        setError({ message: 'An unexpected error occurred while searching.' });
      }
      setSearchResults([]);
    } finally {
      setIsLoadingSearch(false);
    }
  }, []);

  // Handle Search Submission from SearchBar
  const handleSearchSubmit = (newQuery: string) => {
    executeSearch(newQuery, 0);
  };

  // Handle Pagination
  const handlePageChange = (newOffset: number) => {
    executeSearch(query, newOffset);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // Select Instrument for Detail View
  const handleSelectInstrument = useCallback(async (instrumentId: number) => {
    if (detailAbortControllerRef.current) {
      detailAbortControllerRef.current.abort();
    }
    const controller = new AbortController();
    detailAbortControllerRef.current = controller;

    setSelectedInstrumentId(instrumentId);
    setIsLoadingDetail(true);
    setError(null);

    try {
      const detail = await getInstrumentDetail(instrumentId, controller.signal);
      setInstrumentDetail(detail);
      setApiStatus('connected');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      if (err instanceof ApiRequestError) {
        setError({ message: err.message, status: err.status });
      } else {
        setError({ message: 'Failed to load instrument details.' });
      }
    } finally {
      setIsLoadingDetail(false);
    }
  }, []);

  // Return to Search Results
  const handleBackToResults = () => {
    if (detailAbortControllerRef.current) {
      detailAbortControllerRef.current.abort();
    }
    setSelectedInstrumentId(null);
    setInstrumentDetail(null);
    setError(null);
  };

  // Reset to initial clean state
  const handleReset = () => {
    if (searchAbortControllerRef.current) searchAbortControllerRef.current.abort();
    if (detailAbortControllerRef.current) detailAbortControllerRef.current.abort();
    setQuery('');
    setHasSearched(false);
    setSearchResults([]);
    setOffset(0);
    setSelectedInstrumentId(null);
    setInstrumentDetail(null);
    setError(null);
  };

  return (
    <div className="workbench-layout">
      <Header apiStatus={apiStatus} onReset={handleReset} />

      <main className="workbench-main">
        {/* Search Bar is always accessible at top */}
        <SearchBar
          initialQuery={query}
          onSearch={handleSearchSubmit}
          isLoading={isLoadingSearch}
        />

        {/* Global Error Banner */}
        {error && (
          <ErrorMessage
            title="Request Error"
            message={error.message}
            status={error.status}
            onRetry={() => {
              if (selectedInstrumentId) {
                handleSelectInstrument(selectedInstrumentId);
              } else if (query) {
                executeSearch(query, offset);
              }
            }}
          />
        )}

        {/* Detail View */}
        {selectedInstrumentId !== null ? (
          isLoadingDetail ? (
            <LoadingSkeleton type="detail" />
          ) : instrumentDetail ? (
            <InstrumentDetail
              instrument={instrumentDetail}
              onBack={handleBackToResults}
            />
          ) : null
        ) : (
          /* Search Results View */
          isLoadingSearch ? (
            <LoadingSkeleton type="table" />
          ) : hasSearched ? (
            <SearchResults
              results={searchResults}
              query={query}
              limit={PAGE_SIZE}
              offset={offset}
              onSelectInstrument={handleSelectInstrument}
              onPageChange={handlePageChange}
              isLoading={isLoadingSearch}
            />
          ) : (
            /* Welcome / Initial Guidance Card */
            <div className="search-empty-state" role="region" aria-label="Welcome">
              <div className="empty-icon" aria-hidden="true">
                <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M3 3v18h18" />
                  <path d="m19 9-5 5-4-4-3 3" />
                </svg>
              </div>
              <h2 className="empty-title">Stock Intelligence Workbench</h2>
              <p className="empty-message">
                Search across 2,600+ NSE-listed companies and active trading instruments.
              </p>
              <p className="empty-suggestion">
                Try searching for <code>TCS</code>, <code>RELIANCE</code>, <code>INFY</code>, or <code>HDFC</code> to view equity metadata and end-of-day market snapshots.
              </p>
            </div>
          )
        )}
      </main>
    </div>
  );
}

export default App;
