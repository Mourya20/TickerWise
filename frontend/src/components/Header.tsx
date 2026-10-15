import React from 'react';

interface HeaderProps {
  apiStatus: 'checking' | 'connected' | 'error';
  onReset?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ apiStatus, onReset }) => {
  return (
    <header className="app-header" role="banner">
      <div className="header-container">
        <div className="brand-group" onClick={onReset} style={{ cursor: onReset ? 'pointer' : 'default' }}>
          <div className="brand-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 3v18h18" />
              <path d="m19 9-5 5-4-4-3 3" />
            </svg>
          </div>
          <div className="brand-text">
            <h1 className="brand-title">TickerWise</h1>
            <span className="brand-subtitle">NSE Equities & Market Snapshot Browser</span>
          </div>
        </div>

        <div className="header-actions">
          <div
            className={`api-status-badge status-${apiStatus}`}
            title={`Backend status: ${apiStatus}`}
            role="status"
            aria-live="polite"
          >
            <span className="status-dot" aria-hidden="true" />
            <span className="status-label">
              {apiStatus === 'connected' && 'Backend Connected'}
              {apiStatus === 'checking' && 'Connecting...'}
              {apiStatus === 'error' && 'Backend Offline'}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
};
