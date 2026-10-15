import React, { useState } from 'react';
import { useTheme } from '../context/ThemeContext';

interface SearchBarProps {
  initialQuery?: string;
  onSearch: (query: string) => void;
  isLoading?: boolean;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  initialQuery = '',
  onSearch,
  isLoading = false,
}) => {
  const { theme } = useTheme();
  const [query, setQuery] = useState(initialQuery);
  const [prevInitialQuery, setPrevInitialQuery] = useState(initialQuery);
  const [validationError, setValidationError] = useState<string | null>(null);

  if (initialQuery !== prevInitialQuery) {
    setPrevInitialQuery(initialQuery);
    setQuery(initialQuery);
  }

  const placeholderText = theme === 'dark'
    ? '> find company or symbol'
    : 'Search by company name or NSE symbol';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      setValidationError('Please enter a company name or stock symbol to search.');
      return;
    }
    setValidationError(null);
    onSearch(trimmed);
  };

  const handleClear = () => {
    setQuery('');
    setValidationError(null);
  };

  return (
    <div className="search-bar-wrapper">
      <form
        role="search"
        className="search-form"
        onSubmit={handleSubmit}
        aria-label="Stock instrument search form"
      >
        <div className="search-input-container">
          <span className="search-icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
          </span>

          <input
            id="stock-search-input"
            type="text"
            className="search-input"
            placeholder={placeholderText}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (validationError) setValidationError(null);
            }}
            disabled={isLoading}
            autoComplete="off"
            spellCheck={false}
            aria-label="Search instruments by company name or symbol"
            aria-invalid={validationError ? 'true' : 'false'}
            aria-describedby={validationError ? 'search-validation-error' : undefined}
          />

          {query && !isLoading && (
            <button
              type="button"
              id="clear-search-btn"
              className="search-clear-btn"
              onClick={handleClear}
              aria-label="Clear search input"
              title="Clear input"
            >
              ×
            </button>
          )}

          <button
            type="submit"
            id="submit-search-btn"
            className="search-submit-btn"
            disabled={isLoading}
            aria-label="Execute search"
          >
            {isLoading ? (
              <span className="btn-spinner" aria-hidden="true" />
            ) : (
              'Search'
            )}
          </button>
        </div>

        {validationError && (
          <div
            id="search-validation-error"
            className="search-validation-hint"
            role="alert"
          >
            {validationError}
          </div>
        )}
      </form>
    </div>
  );
};
