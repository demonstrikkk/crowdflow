import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, FileUp, Loader2, MapPin, Search, Sparkles, Waypoints } from 'lucide-react';
import { useSimulation } from '../store/SimulationContext';

interface CreateTwinProps {
  onReady: (venueId: string) => void;
  onReviewBlueprint: (file: File) => void;
}

export default function CreateTwinView({ onReady, onReviewBlueprint }: CreateTwinProps) {
  const s = useSimulation();
  const [query, setQuery] = useState('');
  const [building, setBuilding] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const venues = s.venues.filter((v) => v.name.toLowerCase().includes(query.trim().toLowerCase()));

  useEffect(() => {
    void s.refreshCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const build = useCallback(
    async (venueId: string) => {
      setBuilding(true);
      s.selectVenue(venueId);
      setBuilding(false);
      onReady(venueId);
    },
    [s, onReady],
  );

  return (
    <div className="flex h-full w-full flex-col items-center justify-center bg-od-canvas px-4 overflow-y-auto scrollbar-thin">
      <div className="w-full max-w-2xl py-10">
        <div className="border border-od-line bg-od-panel shadow-[0_32px_80px_-40px_rgba(0,0,0,0.8)]">
          <div className="flex items-center justify-between gap-3 border-b border-od-line px-6 py-5">
            <div className="min-w-0">
              <div className="sec-label">CrowdFlow · Operational Workspace</div>
              <h1 className="mt-1 font-display text-xl font-extrabold uppercase tracking-[0.04em] text-od-ink">
                Create Operational Twin
              </h1>
              <p className="mt-1.5 text-[11px] leading-relaxed text-od-muted">
                Drop a venue blueprint and CrowdFlow reconstructs its spatial model, or select a venue
                already in the catalogue. The venue is the workspace — everything you do happens on it.
              </p>
            </div>
            <span className="chip is-active shrink-0">
              <span className="status-dot is-ok" />
              Twin
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-od-line">
            {/* left: upload */}
            <div className="p-5 space-y-3">
              <div className="text-[9px] uppercase tracking-[0.22em] text-od-muted flex items-center gap-1.5">
                <FileUp className="w-3 h-3" /> Drop a blueprint
              </div>
              <div
                className="flex h-32 cursor-pointer flex-col items-center justify-center gap-2 border border-dashed border-od-line-strong bg-od-canvas hover:border-od-ink transition-none"
                onClick={() => fileRef.current?.click()}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') fileRef.current?.click();
                }}
                aria-label="Upload venue blueprint image"
              >
                <FileUp className="h-5 w-5 text-od-ink" />
                <span className="text-[10px] uppercase tracking-[0.16em] text-od-muted">PNG / JPG / WEBP / PDF</span>
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/bmp"
                className="hidden"
                aria-label="Upload venue blueprint image"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onReviewBlueprint(file);
                  e.target.value = '';
                }}
              />

              <div className="border border-od-line bg-od-canvas px-3 py-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[9px] uppercase tracking-[0.18em] text-od-muted">Review before building</span>
                  <span className="chip">
                    <span className="status-dot is-ok" />
                    correct
                  </span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-od-muted">
                  Detections open in a review canvas so you can correct gates, regions, walls and labels before the
                  twin is reconstructed.
                </p>
              </div>
            </div>

            {/* right: select */}
            <div className="p-5 space-y-3">
              <div className="text-[9px] uppercase tracking-[0.22em] text-od-muted flex items-center gap-1.5">
                <Waypoints className="w-3 h-3" /> Select a blueprint
              </div>
              <div className="flex items-center gap-1.5">
                <Search className="w-3.5 h-3.5 text-od-muted shrink-0" />
                <input
                  className="field w-full"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search venue / address"
                  aria-label="Search venues"
                />
              </div>

              <div className="max-h-64 space-y-1.5 overflow-y-auto scrollbar-thin">
                {venues.length === 0 && (
                  <p className="text-[10px] uppercase tracking-[0.14em] text-od-muted py-4 text-center">
                    No venues found — upload a blueprint
                  </p>
                )}
                {venues.map((v) => (
                  <button
                    key={v.id}
                    onClick={() => void build(v.id)}
                    className="w-full border border-od-line hover:border-od-ink text-left px-3 py-2.5 cursor-pointer transition-none bg-od-surface"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-display text-[11px] font-bold uppercase tracking-[0.1em] text-od-ink">{v.name}</span>
                      <ArrowRight className="w-3 h-3 text-od-muted" />
                    </div>
                    <div className="mt-0.5 flex items-center gap-3 text-[10px] text-od-muted">
                      <span className="flex items-center gap-1"><MapPin className="w-3 h-3" /> {v.nodes.filter((n) => n.type === 'ENTRY').length} gates</span>
                      <span>{v.nodes.length} nodes</span>
                      <span>{v.edges.length} walkways</span>
                    </div>
                  </button>
                ))}
              </div>

              {s.venues.length === 0 && (
                <div className="border border-od-line bg-od-canvas px-3 py-2.5">
                  <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-[0.18em] text-od-muted">
                    <Sparkles className="w-3 h-3" /> No catalogue yet
                  </div>
                  <p className="mt-1 text-[10px] text-od-muted leading-relaxed">
                    Start by importing a blueprint, or start the backend seed data (uvicorn app.main:app).
                  </p>
                </div>
              )}
            </div>
          </div>

          {building && (
            <div className="flex items-center justify-center gap-2 border-t border-od-line px-6 py-3 text-[10px] uppercase tracking-[0.18em] text-od-muted">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading surrounding environment…
            </div>
          )}
        </div>

        <p className="mt-3 text-center text-[10px] uppercase tracking-[0.18em] text-od-muted">
          Venue → Situation → Simulation → Intervention → Outcome
        </p>
      </div>
    </div>
  );
}
