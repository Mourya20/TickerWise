import '@testing-library/jest-dom/vitest'

// Mock window.scrollTo for jsdom
Object.defineProperty(window, 'scrollTo', {
  value: () => {},
  writable: true,
});
