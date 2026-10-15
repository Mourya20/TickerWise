import React, { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { SearchBar } from './SearchBar';
import { useTheme } from '../context/ThemeContext';

export const AppShell: React.FC = () => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();

  // If currently on /search?q=..., extract query for the top search bar
  const queryParams = new URLSearchParams(location.search);
  const currentQuery = queryParams.get('q') || '';

  const handleGlobalSearch = (query: string) => {
    const trimmed = query.trim();
    if (trimmed) {
      navigate(`/search?q=${encodeURIComponent(trimmed)}`);
    } else {
      navigate('/search');
    }
  };

  return (
    <div className="workbench-app-shell">
      {/* Left Persistent Navigation */}
      <Sidebar
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Content Workspace */}
      <div className="workbench-content-area">
        {/* Top bar with mobile menu button, Global Search Input & Theme Toggle Switch */}
        <header className="workbench-top-bar" role="banner">
          <div className="top-bar-left">
            <button
              type="button"
              className="mobile-menu-trigger"
              onClick={() => setIsMobileMenuOpen(true)}
              aria-label="Open navigation menu"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <div className="top-search-wrapper">
              <SearchBar
                initialQuery={currentQuery}
                onSearch={handleGlobalSearch}
              />
            </div>
          </div>

          <div className="top-bar-right">
            <button
              type="button"
              className="top-theme-toggle-btn"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              role="switch"
              aria-checked={theme === 'dark'}
            >
              <span className="top-theme-icon" aria-hidden="true">
                {theme === 'dark' ? '🌙' : '☀️'}
              </span>
              <span className={`theme-toggle-track ${theme === 'dark' ? 'track-dark' : ''}`}>
                <span className={`theme-toggle-thumb ${theme === 'dark' ? 'thumb-dark' : ''}`} />
              </span>
              <span className="top-theme-label">
                {theme === 'dark' ? 'Dark' : 'Light'}
              </span>
            </button>
          </div>
        </header>

        {/* Dynamic page content routed by React Router */}
        <main className="workbench-main-viewport" role="main" id="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
