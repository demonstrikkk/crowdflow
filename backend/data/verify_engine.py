import sys, time
sys.path.insert(0, 'C:/Users/asus/Downloads/crowdflow/backend')
from app.storage import storage
from app.engine.venue import VenueGraph
from app.engine.routing import RoutingEngine
from app.engine.simulator import SimulationEngine

venue = storage.get_venue('unity_arena')
graph = VenueGraph(venue)

def build(sid, name, seed=42):
    sc = storage.get_scenario(sid)
    return SimulationEngine(name, sc, graph, RoutingEngine(graph), seed=seed)

# --- 1. performance sweep (gate_overload is the heaviest) ---
e = build('gate_overload', 'perf')
e.play()
t0 = time.time()
while e.t_min < 130:
    e.tick()
wall = time.time() - t0
print(f'PERF gate_overload 130min: {wall:.1f}s ({(130*60)/(wall):.0f}x realtime)')

e = build('normal', 'perf2')
e.play()
t0 = time.time()
while e.t_min < 130:
    e.tick()
wall = time.time() - t0
print(f'PERF normal 130min: {wall:.1f}s ({(130*60)/(wall):.0f}x realtime)')

# --- 2. emergency during the normal surge ---
e = build('normal', 'emerg')
e.play()
while e.t_min < 112:
    e.tick()
e.set_emergency(True)
done_before = e.total_completed
for i in range(150):  # 10 min
    e.tick()
m = e.metrics
print(f'EMERGENCY at t=112: done {done_before} -> {e.total_completed} after 10min; queue {m.queue_total} risk {m.risk_level.value}')
st = e.state()
print('  emergency_active:', st.emergency_active)
print('  sample agent dest:', st.agents[0].destination if st.agents else None)

# --- 3. recommended action at a critical moment ---
e = build('exit_surge', 'rec')
e.play()
while e.t_min < 120:
    e.tick()
st = e.state()
print(f'RECOMMENDED at t=120 (risk {st.metrics.risk_level.value}, queue {st.metrics.queue_total}):')
print('  ', st.recommended_action)
print('  bottlenecks:', len(st.bottlenecks))

# --- 4. optimisation counterfactuals ---
t0 = time.time()
result = e.optimize(horizon_min=10.0)
wall = time.time() - t0
print(f'OPTIMISE took {wall:.1f}s')
if result:
    print('  baseline queue:', result['baseline_metrics'].queue_total)
    for r in result['candidates'][:5]:
        inter = r['intervention']
        print(f"  {inter.description.replace(chr(0x2192), '->')}: score={r['score']}")
else:
    print('  no candidates')

# --- 5. invariants at a CRITICAL moment ---
e = build('normal', 'inv')
e.play()
while e.t_min < 125:
    e.tick()
tot_node = sum(ns.people for ns in e.nodes.values())
tot_edge = sum(es.people for es in e.edges.values())
in_venue = e.total_spawned - e.total_completed
print(f'INVARIANT t=125: in_venue={in_venue} node_people={tot_node} edge_people={tot_edge}')
print(f'  conservation ok: {abs(tot_node + tot_edge - in_venue) < 1e-6}')
scale = e.scale
over = [k for k, es in e.edges.items() if es.people > e._pipe_capacity(*k) * 1.01]
print(f'  edges over pipe: {len(over)} of {len(e.edges)}')
over2 = [n for n, ns in e.nodes.items() if ns.people < -1e-6]
print(f'  nodes with negative people: {len(over2)}')
