import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@testing-library/react';
import * as React from 'react';
import { InstrumentCanvasAgents } from '../InstrumentCanvasAgents';
import type { VenueModel } from '../../../lib/types';

const mockVenue: VenueModel = {
  id: 'v1',
  name: 'Test Venue',
  width: 1000,
  height: 620,
  nodes: [],
  edges: [],
};

describe('InstrumentCanvasAgents — Canvas fallback (Req 19)', () => {
  let getContextSpy: ReturnType<typeof vi.spyOn>;
  let consoleWarnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // Mock getContext to simulate Canvas 2D unavailability
    getContextSpy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null as never);
    consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    getContextSpy.mockRestore();
    consoleWarnSpy.mockRestore();
  });

  it('calls onCanvasUnsupported when getContext returns null', () => {
    const onCanvasUnsupported = vi.fn();
    const simRef = React.createRef<null>();

    render(
      <InstrumentCanvasAgents
        simRef={simRef as React.RefObject<never>}
        venue={mockVenue}
        showAgents={true}
        viewBoxX={0}
        viewBoxY={0}
        viewBoxW={1000}
        viewBoxH={620}
        onCanvasUnsupported={onCanvasUnsupported}
      />,
    );

    expect(onCanvasUnsupported).toHaveBeenCalledTimes(1);
  });

  it('does not throw an uncaught exception when 2D context is unavailable', () => {
    const simRef = React.createRef<null>();

    expect(() => {
      render(
        <InstrumentCanvasAgents
          simRef={simRef as React.RefObject<never>}
          venue={mockVenue}
          showAgents={true}
          viewBoxX={0}
          viewBoxY={0}
          viewBoxW={1000}
          viewBoxH={620}
        />,
      );
    }).not.toThrow();
  });
});
