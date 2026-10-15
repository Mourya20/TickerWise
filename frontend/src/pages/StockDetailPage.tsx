import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { InstrumentDetail } from '../components/InstrumentDetail';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorMessage } from '../components/ErrorMessage';
import { getInstrumentDetail, ApiRequestError } from '../services/api';
import type { InstrumentDetailResponse, ApiError } from '../types/instrument';

export const StockDetailPage: React.FC = () => {
  const { instrumentId, tab } = useParams<{ instrumentId: string; tab?: string }>();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<InstrumentDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const parsedId = instrumentId ? parseInt(instrumentId, 10) : NaN;

  const fetchDetail = useCallback(async (id: number) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setError(null);

    try {
      const data = await getInstrumentDetail(id, controller.signal);
      setDetail(data);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      if (err instanceof ApiRequestError) {
        setError({ message: err.message, status: err.status });
      } else {
        setError({ message: 'Failed to retrieve instrument details from server.' });
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isNaN(parsedId) || parsedId <= 0) {
      setIsLoading(false);
      setError({ message: `Invalid instrument identifier: "${instrumentId}". Expected positive integer ID.`, status: 400 });
      return;
    }

    fetchDetail(parsedId);

    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [parsedId, instrumentId, fetchDetail]);

  const location = useLocation();

  const handleBack = () => {
    const fromSearch = (location.state as { fromSearch?: string } | null)?.fromSearch;
    if (fromSearch) {
      navigate(`/search${fromSearch}`);
    } else if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/search');
    }
  };

  if (isLoading) {
    return (
      <div className="stock-detail-page-container">
        <LoadingSkeleton type="detail" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="stock-detail-page-container">
        <div className="detail-top-bar">
          <button
            type="button"
            className="back-btn"
            onClick={handleBack}
            aria-label="Return to search"
          >
            ← Back to results
          </button>
        </div>

        <ErrorMessage
          title="Instrument Details Unavailable"
          message={error ? error.message : 'No instrument data found.'}
          status={error?.status}
          onRetry={!isNaN(parsedId) && parsedId > 0 ? () => fetchDetail(parsedId) : undefined}
        />
      </div>
    );
  }

  return (
    <div className="stock-detail-page-container">
      <InstrumentDetail
        instrument={detail}
        onBack={handleBack}
        initialTab={tab || 'overview'}
      />
    </div>
  );
};
