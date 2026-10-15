import React from 'react';
import { useNavigate } from 'react-router-dom';

export interface PlannedFeatureProps {
  title: string;
  description?: string;
  roadmapItem?: string;
  stageBadge?: string;
  roadmapDetails?: string[];
  backLink?: string;
  backText?: string;
}

export const PlannedFeature: React.FC<PlannedFeatureProps> = ({
  title,
  description = 'Filtering and ranking stocks is part of the roadmap, but nothing here works yet. No sample data is shown.',
  roadmapItem = 'ROADMAP ITEM 4 · GENERAL ANALYSIS, SCREENING AND HISTORICAL RESEARCH',
  stageBadge,
  roadmapDetails,
  backLink = '/search',
  backText = 'Go to search',
}) => {
  const navigate = useNavigate();

  return (
    <div className="planned-feature-container" role="region" aria-label={`Planned feature: ${title}`}>
      <div className="planned-pill-badge" id="badge-planned-status">
        {stageBadge || 'Planned — Not Implemented'}
      </div>

      <h1 className="planned-title" id="planned-feature-heading">
        {title}
      </h1>

      <p className="planned-description">
        {description}
      </p>

      {roadmapItem && (
        <div className="planned-roadmap-meta">
          {roadmapItem}
        </div>
      )}

      {roadmapDetails && roadmapDetails.length > 0 && (
        <div className="planned-roadmap-section">
          <ul className="roadmap-list">
            {roadmapDetails.map((item, idx) => (
              <li key={idx} className="roadmap-item">
                <span className="roadmap-bullet" aria-hidden="true">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="planned-actions">
        <button
          type="button"
          className="btn-planned-action"
          onClick={() => navigate(backLink)}
          aria-label={backText}
        >
          {backText}
        </button>
      </div>
    </div>
  );
};
