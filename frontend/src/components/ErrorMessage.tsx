import React from 'react';

interface ErrorMessageProps {
  title?: string;
  message: string;
  status?: number;
  onRetry?: () => void;
}

export const ErrorMessage: React.FC<ErrorMessageProps> = ({
  title = 'Service Unavailable',
  message,
  status,
  onRetry,
}) => {
  return (
    <div className="error-banner" role="alert">
      <div className="error-icon" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <div className="error-content">
        <div className="error-title-row">
          <h3 className="error-title">{title}</h3>
          {status && <span className="error-status-badge">HTTP {status}</span>}
        </div>
        <p className="error-description">{message}</p>
        {onRetry && (
          <button
            type="button"
            className="error-retry-btn"
            onClick={onRetry}
            id="error-retry-btn"
          >
            Retry Request
          </button>
        )}
      </div>
    </div>
  );
};
