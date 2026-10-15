import React from 'react';
import { NavLink } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { ConnectionStatus } from './ConnectionStatus';

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen = false, onClose }) => {
  const { theme, toggleTheme } = useTheme();

  return (
    <>
      {isOpen && (
        <div
          className="sidebar-backdrop"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside className={`app-sidebar ${isOpen ? 'sidebar-open' : ''}`} aria-label="Main Navigation">
        {/* Logo / Title */}
        <div className="sidebar-brand-header">
          <NavLink to="/search" className="brand-logo-link" onClick={onClose}>
            <span className="brand-title">TickerWise</span>
          </NavLink>

          <button
            type="button"
            className="mobile-close-btn"
            onClick={onClose}
            aria-label="Close navigation"
          >
            ✕
          </button>
        </div>

        {/* Navigation list */}
        <nav className="sidebar-nav-scroll">
          {/* RESEARCH Section */}
          <div className="nav-group">
            <div className="nav-group-header">RESEARCH</div>
            <NavLink
              to="/search"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              onClick={onClose}
            >
              <span className="nav-label">Search & instruments</span>
            </NavLink>
          </div>

          {/* PLANNED · NOT IMPLEMENTED Section */}
          <div className="nav-group">
            <div className="nav-group-header">PLANNED · NOT<br />IMPLEMENTED</div>

            <NavLink
              to="/screener"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              onClick={onClose}
            >
              <span className="nav-label">Screener</span>
            </NavLink>

            <NavLink
              to="/market"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              onClick={onClose}
            >
              <span className="nav-label">Market overview</span>
            </NavLink>

            <NavLink
              to="/sectors"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              onClick={onClose}
            >
              <span className="nav-label">Sectors</span>
            </NavLink>

            <NavLink
              to="/analysis"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              onClick={onClose}
            >
              <span className="nav-label">Analysis</span>
            </NavLink>

            <NavLink
              to="/news"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              onClick={onClose}
            >
              <span className="nav-label">News & documents</span>
            </NavLink>

            <NavLink
              to="/research"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              onClick={onClose}
            >
              <span className="nav-label">AI research</span>
            </NavLink>

            <NavLink
              to="/system-health"
              className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              onClick={onClose}
            >
              <span className="nav-label">System health</span>
            </NavLink>
          </div>
        </nav>

        {/* Footer controls: Real connection status & Dark theme switch */}
        <div className="sidebar-footer">
          <ConnectionStatus />

          <button
            type="button"
            className="theme-switch-row"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            role="switch"
            aria-checked={theme === 'dark'}
          >
            <div className="theme-switch-label-group">
              <span className="theme-switch-icon" aria-hidden="true">
                {theme === 'dark' ? '🌙' : '☀️'}
              </span>
              <span className="theme-toggle-label">
                {theme === 'dark' ? 'Dark theme' : 'Light theme'}
              </span>
            </div>
            <span className={`theme-toggle-track ${theme === 'dark' ? 'track-dark' : ''}`}>
              <span className={`theme-toggle-thumb ${theme === 'dark' ? 'thumb-dark' : ''}`} />
            </span>
          </button>
        </div>
      </aside>
    </>
  );
};
