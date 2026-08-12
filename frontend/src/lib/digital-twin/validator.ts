import type { VenueDigitalTwin, TwinValidationIssue } from '../types';

export function validateTwin(twin: VenueDigitalTwin): TwinValidationIssue[] {
  const issues: TwinValidationIssue[] = [];

  if (!twin.levels || twin.levels.length === 0) {
    issues.push({
      id: 'missing-levels',
      severity: 'ERROR',
      scope: 'LEVEL',
      message: 'Venue twin has no levels defined.',
      element_ids: [],
    });
  }

  if (!twin.navigation || !twin.navigation.nodes || twin.navigation.nodes.length === 0) {
    issues.push({
      id: 'empty-navigation-graph',
      severity: 'WARNING',
      scope: 'GRAPH',
      message: 'No navigation nodes found in the digital twin.',
      element_ids: [],
    });
  }

  return issues;
}
