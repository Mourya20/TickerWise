/**
 * Utilities for formatting financial numbers, dates, and currency values.
 * Follows Indian financial reporting conventions (₹, Lakhs, Crores) without
 * fabricating missing data.
 */

export function parseDecimalNumber(val: string | number | null | undefined): number | null {
  if (val === null || val === undefined || val === '') {
    return null;
  }
  const num = typeof val === 'number' ? val : parseFloat(val);
  return Number.isFinite(num) ? num : null;
}

export function formatCurrencyINR(val: string | number | null | undefined): string {
  const num = parseDecimalNumber(val);
  if (num === null) return '—';
  return `₹${num.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPlainDecimal(
  val: string | number | null | undefined,
  decimals: number = 2
): string {
  const num = parseDecimalNumber(val);
  if (num === null) return '—';
  return num.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export interface PercentageChangeInfo {
  formatted: string;
  direction: 'positive' | 'negative' | 'neutral';
  symbol: string;
  accessibleText: string;
}

export function formatPercentageChange(
  val: string | number | null | undefined
): PercentageChangeInfo | null {
  const num = parseDecimalNumber(val);
  if (num === null) return null;

  const absFormatted = Math.abs(num).toFixed(2);

  if (num > 0) {
    return {
      formatted: `+${absFormatted}%`,
      direction: 'positive',
      symbol: '▲',
      accessibleText: `Up by ${absFormatted} percent`,
    };
  } else if (num < 0) {
    return {
      formatted: `-${absFormatted}%`,
      direction: 'negative',
      symbol: '▼',
      accessibleText: `Down by ${absFormatted} percent`,
    };
  }

  return {
    formatted: `0.00%`,
    direction: 'neutral',
    symbol: '■',
    accessibleText: `Unchanged (0.00 percent)`,
  };
}

export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return '—';
  try {
    const parts = isoDate.split('-');
    if (parts.length === 3) {
      const year = parseInt(parts[0], 10);
      const month = parseInt(parts[1], 10) - 1;
      const day = parseInt(parts[2], 10);
      const d = new Date(year, month, day);
      if (!isNaN(d.getTime())) {
        return d.toLocaleDateString('en-IN', {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });
      }
    }
    return isoDate;
  } catch {
    return isoDate;
  }
}

export function formatVolumeLakhs(val: string | number | null | undefined): string {
  const num = parseDecimalNumber(val);
  if (num === null) return '—';
  return `${num.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} lakh`;
}

export function formatTradedValueCrores(val: string | number | null | undefined): string {
  const num = parseDecimalNumber(val);
  if (num === null) return '—';
  return `₹${num.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} Cr`;
}

export function formatMarketCapCrores(val: string | number | null | undefined): string {
  const num = parseDecimalNumber(val);
  if (num === null) return '—';
  return `₹${num.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} Cr`;
}

export function formatShareCount(val: number | string | null | undefined): string {
  const num = parseDecimalNumber(val);
  if (num === null) return '—';
  return num.toLocaleString('en-IN');
}

