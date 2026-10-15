import React from 'react';

interface LoadingSkeletonProps {
  type?: 'table' | 'detail' | 'general';
}

export const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({ type = 'general' }) => {
  if (type === 'table') {
    return (
      <div className="skeleton-container" role="status" aria-label="Loading instruments">
        <div className="skeleton-status-strip">
          <span className="spinner-inline" aria-hidden="true" />
          <span className="skeleton-status-text">Searching instruments…</span>
        </div>
        <div className="skeleton-table">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="skeleton-row">
              <div className="skeleton-cell cell-short" />
              <div className="skeleton-cell cell-long" />
              <div className="skeleton-cell cell-short" />
              <div className="skeleton-cell cell-medium" />
              <div className="skeleton-cell cell-medium" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (type === 'detail') {
    return (
      <div className="skeleton-container" role="status" aria-label="Loading instrument details">
        <div className="skeleton-status-strip">
          <span className="spinner-inline" aria-hidden="true" />
          <span className="skeleton-status-text">Loading company details…</span>
        </div>
        <div className="skeleton-card card-large">
          <div className="skeleton-badge-row" />
          <div className="skeleton-title" />
          <div className="skeleton-meta" />
        </div>
        <div className="skeleton-grid">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton-card card-metric" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="skeleton-container" role="status" aria-label="Loading">
      <div className="skeleton-status-strip">
        <span className="spinner-inline" aria-hidden="true" />
        <span className="skeleton-status-text">Loading…</span>
      </div>
      <div className="skeleton-card card-large" />
    </div>
  );
};
