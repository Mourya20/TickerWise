import React from 'react';

interface ErrorMessageProps {
  title?: string;
  message: string;
  status?: number;
  onRetry?: () => void;
}

export const ErrorMessage: React.FC<ErrorMessageProps> = ({
  title = "Can't reach the backend",
  message,
  status,
  onRetry,
}) => {
  return (
    <div className="error-banner state-card" role="alert">
      <div className="state-header-tag">API ERROR</div>
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
          aria-label="Retry Request"
        >
          Try again
        </button>
      )}
    </div>
  );
};
