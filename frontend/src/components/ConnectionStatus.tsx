import React, { useEffect, useState } from 'react';
import { checkHealth, getProviderStatus } from '../services/api';
import type { ProviderStatusResponse } from '../types/instrument';

export const ConnectionStatus: React.FC = () => {
  const [status, setStatus] = useState<'checking' | 'connected' | 'unavailable'>('checking');
  const [providerInfo, setProviderInfo] = useState<ProviderStatusResponse | null>(null);

  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();

    async function evaluateConnection() {
      setStatus('checking');
      try {
        await checkHealth(controller.signal);
        if (!isMounted) return;
        setStatus('connected');

        try {
          const prov = await getProviderStatus(controller.signal);
          if (isMounted) setProviderInfo(prov);
        } catch {
          // Provider status error does not mean backend is down
        }
      } catch {
        if (isMounted) {
          setStatus('unavailable');
          setProviderInfo(null);
        }
      }
    }

    evaluateConnection();

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, []);

  return (
    <div className="connection-status-panel" role="status" aria-label="Backend status">
      <div className="status-indicator-row">
        <span
          className={`status-dot status-dot-${status}`}
          aria-hidden="true"
        />
        <span className="status-label-text">
          {status === 'checking' && 'Checking backend…'}
          {status === 'connected' && 'Backend Connected'}
          {status === 'unavailable' && 'Backend Unavailable'}
        </span>
      </div>

      {status === 'connected' && providerInfo && (
        <div className="provider-substatus-text">
          <span>{providerInfo.primary_provider}: </span>
          <span className="provider-date-tag">
            {providerInfo.latest_published_trading_date || 'No EOD date'}
          </span>
          {providerInfo.incomplete_coverage && (
            <span className="coverage-badge" title="Partial market coverage">Partial</span>
          )}
        </div>
      )}
    </div>
  );
};
