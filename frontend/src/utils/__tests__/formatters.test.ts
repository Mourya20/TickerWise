import { describe, it, expect } from 'vitest';
import {
  formatCurrencyINR,
  formatPlainDecimal,
  formatPercentageChange,
  formatDate,
  parseDecimalNumber,
} from '../formatters';

describe('Formatters Utility', () => {
  describe('parseDecimalNumber', () => {
    it('correctly parses numbers and strings', () => {
      expect(parseDecimalNumber(123.45)).toBe(123.45);
      expect(parseDecimalNumber('2304.90')).toBe(2304.9);
      expect(parseDecimalNumber('-5.85')).toBe(-5.85);
    });

    it('returns null for empty, null, or invalid input', () => {
      expect(parseDecimalNumber(null)).toBeNull();
      expect(parseDecimalNumber(undefined)).toBeNull();
      expect(parseDecimalNumber('')).toBeNull();
      expect(parseDecimalNumber('invalid')).toBeNull();
    });
  });

  describe('formatCurrencyINR', () => {
    it('formats positive currency with ₹ and Indian grouping', () => {
      expect(formatCurrencyINR('2304.900000')).toBe('₹2,304.90');
      expect(formatCurrencyINR('1000000')).toBe('₹10,00,000.00');
    });

    it('returns dash for null or missing values without fabricating data', () => {
      expect(formatCurrencyINR(null)).toBe('—');
      expect(formatCurrencyINR(undefined)).toBe('—');
      expect(formatCurrencyINR('')).toBe('—');
    });
  });

  describe('formatPlainDecimal', () => {
    it('formats decimal numbers with specified fraction digits', () => {
      expect(formatPlainDecimal('833932.990000', 2)).toBe('8,33,932.99');
      expect(formatPlainDecimal('121.460000', 2)).toBe('121.46');
    });

    it('returns dash for missing values', () => {
      expect(formatPlainDecimal(null)).toBe('—');
    });
  });

  describe('formatPercentageChange', () => {
    it('formats positive change with + and ▲ symbol', () => {
      const res = formatPercentageChange('2.110000');
      expect(res).not.toBeNull();
      expect(res?.formatted).toBe('+2.11%');
      expect(res?.direction).toBe('positive');
      expect(res?.symbol).toBe('▲');
      expect(res?.accessibleText).toContain('Up by 2.11 percent');
    });

    it('formats negative change with - and ▼ symbol', () => {
      const res = formatPercentageChange('-1.450000');
      expect(res).not.toBeNull();
      expect(res?.formatted).toBe('-1.45%');
      expect(res?.direction).toBe('negative');
      expect(res?.symbol).toBe('▼');
      expect(res?.accessibleText).toContain('Down by 1.45 percent');
    });

    it('formats zero change as neutral', () => {
      const res = formatPercentageChange('0.000000');
      expect(res).not.toBeNull();
      expect(res?.formatted).toBe('0.00%');
      expect(res?.direction).toBe('neutral');
    });

    it('returns null for missing change', () => {
      expect(formatPercentageChange(null)).toBeNull();
    });
  });

  describe('formatDate', () => {
    it('formats ISO dates accurately', () => {
      expect(formatDate('2026-10-14')).toBe('14 Oct 2026');
      expect(formatDate('2004-08-25')).toBe('25 Aug 2004');
    });

    it('returns dash for null/empty date', () => {
      expect(formatDate(null)).toBe('—');
      expect(formatDate(undefined)).toBe('—');
    });
  });
});
