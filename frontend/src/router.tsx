import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { SearchPage } from './pages/SearchPage';
import { StockDetailPage } from './pages/StockDetailPage';
import {
  ScreenerPage,
  MarketOverviewPage,
  SectorsPage,
  AnalysisPage,
  NewsDocumentsPage,
  DocumentsPage,
  AiResearchPage,
  SystemHealthPage,
  NotFoundPage,
} from './pages/PlannedPages';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <Navigate to="/search" replace />,
      },
      {
        path: 'search',
        element: <SearchPage />,
      },
      {
        path: 'stocks/:instrumentId',
        element: <Navigate to="overview" replace />,
      },
      {
        path: 'stocks/:instrumentId/overview',
        element: <StockDetailPage />,
      },
      {
        path: 'stocks/:instrumentId/:tab',
        element: <StockDetailPage />,
      },
      {
        path: 'screener',
        element: <ScreenerPage />,
      },
      {
        path: 'market',
        element: <MarketOverviewPage />,
      },
      {
        path: 'sectors',
        element: <SectorsPage />,
      },
      {
        path: 'analysis',
        element: <AnalysisPage />,
      },
      {
        path: 'news',
        element: <NewsDocumentsPage />,
      },
      {
        path: 'documents',
        element: <DocumentsPage />,
      },
      {
        path: 'research',
        element: <AiResearchPage />,
      },
      {
        path: 'system-health',
        element: <SystemHealthPage />,
      },
      {
        path: '*',
        element: <NotFoundPage />,
      },
    ],
  },
]);
