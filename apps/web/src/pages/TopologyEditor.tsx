import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { Cable, Download, LayoutGrid, Maximize, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { generateTopology, useDesignPresets, useSaveTopology, useTopology, validateTopology } from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { type JsonSchema, SchemaForm } from "@/components/SchemaForm";
import { cn } from "@/lib/cn";
import { useUi } from "@/stores/ui";

type Layer = "iot" | "edge" | "fog" | "cloud";
export type NodeSpec = {
  id: string; name: string; layer: Layer; cores: number; mips: number; ram_mb: number; p_idle_w: number; p_max_w: number;
  cost_per_core_s: number; mtbf_s: number; mttr_s: number;
};
export type LinkSpec = { a: string; b: string; kind: string; bandwidth_mbps: number; latency_ms: number };
type Layout = Record<string, { x: number; y: number }>;
type Check = { valid: boolean; problems: string[]; summary: Record<string, unknown> | null | undefined };

const LAYER_LABEL: Record<Layer, string> = { iot: "IoT gateway", edge: "Edge device", fog: "Fog server", cloud: "Cloud server" };
const LAYER_ROW: Record<Layer, number> = { cloud: 60, fog: 220, edge: 380, iot: 540 };
const LAYER_SHAPE: Record<Layer, string> = { iot: "diamond", edge: "round-rectangle", fog: "hexagon", cloud: "ellipse" };
const LINK_KINDS = ["ethernet", "wifi", "4g", "5g", "lorawan", "zigbee", "ble", "nbiot", "wan"];

function defaultKind(a: Layer, b: Layer): string {
  const pair = [a, b].sort().join("-");
  if (pair.includes("iot")) return "wifi";
  if (pair === "cloud-fog" || pair.includes("cloud")) return "wan";
  return "ethernet";
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

export default function TopologyEditor() {
  const { topoId } = useParams();
  const { data: presets } = useDesignPresets();
  const { data: saved, isLoading } = useTopology(topoId ?? "");
  if (!presets || (topoId && isLoading)) return <p className="text-sm text-ink-3">Loading…</p>;
  if (topoId && !saved) return <p className="text-sm text-danger">Topology not found.</p>;
  return (
    <Designer
      key={topoId ?? "new"}
      topoId={topoId}
      presets={presets as unknown as Presets}
      initial={saved ? {
        name: saved.name, description: saved.description,
        nodes: (saved.topology.nodes ?? []) as NodeSpec[], links: (saved.topology.links ?? []) as LinkSpec[],
        layout: saved.layout as Layout,
      } : { name: "Untitled network", description: "", nodes: [], links: [], layout: {} }}
    />
  );
}

type Presets = { devices: Record<string, Record<string, number>>; link_kinds: Record<string, { bandwidth_mbps: number; latency_ms: number }>; generator_schema: JsonSchema };
type Initial = { name: string; description: string; nodes: NodeSpec[]; links: LinkSpec[]; layout: Layout };

function Designer({ topoId, presets, initial }: { topoId?: string; presets: Presets; initial: Initial }) {
  const navigate = useNavigate();
  const theme = useUi((s) => s.theme);
  const mode = useUi((s) => s.mode);
  const save = useSaveTopology();
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [nodes, setNodes] = useState<NodeSpec[]>(initial.nodes);
  const [links, setLinks] = useState<LinkSpec[]>(initial.links);
  const [selected, setSelected] = useState<{ type: "node" | "link"; id: string } | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [check, setCheck] = useState<Check | null>(null);
  const [dirty, setDirty] = useState(false);
  const [genOpen, setGenOpen] = useState(false);
  const [genParams, setGenParams] = useState<Record<string, unknown>>({ farms: 4, gateways_per_farm: 2, edge_per_farm: 1, fog_nodes: 2, cloud_nodes: 1 });
  const [confirmReplace, setConfirmReplace] = useState<null | (() => void)>(null);
  const [message, setMessage] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const linkId = (l: LinkSpec) => `${l.a}--${l.b}`;
  const topology = useMemo(() => ({ name, nodes, links }), [name, nodes, links]);

  // --- Cytoscape set-up ---------------------------------------------------------------------------
  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({
      container: container.current,
      wheelSensitivity: 0.25,
      boxSelectionEnabled: false,
      elements: [],
      layout: { name: "preset" },
    });
    cyRef.current = cy;
    (window as unknown as { __cy?: Core }).__cy = cy; // debugging hook
    // Keep the canvas sized to its container (window resizes, sidebar collapse, panels).
    const observer = new ResizeObserver(() => cy.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // Style follows the theme (Cytoscape needs concrete colours).
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const ink = cssVar("--ink"), ink3 = cssVar("--ink-3"), line = cssVar("--ink-3"), accent = cssVar("--accent");
    const colour: Record<Layer, string> = {
      iot: cssVar("--st-planned"), edge: cssVar("--st-implemented"), fog: cssVar("--accent"), cloud: cssVar("--st-integration"),
    };
    cy.style([
      { selector: "node", style: {
        label: "data(label)", "font-size": 11, color: ink, "text-valign": "bottom", "text-margin-y": 6,
        "font-family": "Instrument Sans Variable, Segoe UI, sans-serif", width: 34, height: 34,
        "border-width": 2, "background-opacity": 0.18,
      } },
      ...(Object.keys(colour) as Layer[]).map((l) => ({
        selector: `node[layer = "${l}"]`,
        style: { shape: LAYER_SHAPE[l], "background-color": colour[l], "border-color": colour[l], ...(l === "iot" ? { width: 24, height: 24 } : {}) },
      })) as never[],
      { selector: "node:selected", style: { "border-width": 4, "border-color": accent, "background-opacity": 0.35 } },
      { selector: "node.connect-source", style: { "border-style": "dashed", "border-width": 4, "border-color": accent } },
      { selector: "edge", style: {
        width: "mapData(bw, -3, 3, 1, 4)", "line-color": line, "curve-style": "bezier", label: "data(kind)", "font-size": 9,
        color: ink3, "text-background-color": cssVar("--bg"), "text-background-opacity": 1, "text-background-padding": "2px",
        "text-rotation": "autorotate", opacity: 0.8,
      } },
      { selector: "edge:selected", style: { "line-color": accent, width: 4, opacity: 1 } },
    ] as never);
  }, [theme]);

  // Sync React state -> Cytoscape elements (positions stay in Cytoscape).
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      const nodeIds = new Set(nodes.map((n) => n.id));
      const linkIds = new Set(links.map(linkId));
      cy.nodes().forEach((el) => {
        if (!nodeIds.has(el.id())) el.remove();
      });
      cy.edges().forEach((el) => {
        if (!linkIds.has(el.id())) el.remove();
      });
      const toAdd: ElementDefinition[] = [];
      for (const n of nodes) {
        const el = cy.getElementById(n.id);
        const data = { id: n.id, label: n.name || n.id, layer: n.layer };
        if (el.empty()) {
          const pos = initial.layout[n.id] ?? { x: 80 + (cy.nodes(`[layer = "${n.layer}"]`).length) * 140, y: LAYER_ROW[n.layer] };
          toAdd.push({ group: "nodes", data, position: { ...pos } });
        } else el.data(data);
      }
      for (const l of links) {
        const el = cy.getElementById(linkId(l));
        const data = { id: linkId(l), source: l.a, target: l.b, kind: l.kind, bw: Math.log10(Math.max(l.bandwidth_mbps, 0.001)) };
        if (el.empty()) toAdd.push({ group: "edges", data });
        else el.data(data);
      }
      if (toAdd.length) cy.add(toAdd);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, links]);

  useEffect(() => {
    if (initial.nodes.length) cyRef.current?.fit(undefined, 40);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tap handling: select, or connect two nodes.
  const onTap = useCallback(
    (evt: cytoscape.EventObject) => {
      const target = evt.target;
      if (target === cyRef.current) {
        setSelected(null);
        return;
      }
      if (target.isNode() && connecting) {
        const id = target.id();
        if (!connectFrom) {
          setConnectFrom(id);
          return;
        }
        if (connectFrom !== id) {
          const a = nodes.find((n) => n.id === connectFrom)!;
          const b = nodes.find((n) => n.id === id)!;
          const exists = links.some((l) => (l.a === a.id && l.b === b.id) || (l.a === b.id && l.b === a.id));
          if (exists) setMessage(`${a.id} and ${b.id} are already connected.`);
          else {
            const kind = defaultKind(a.layer, b.layer);
            const preset = presets.link_kinds[kind];
            setLinks((ls) => [...ls, { a: a.id, b: b.id, kind, ...preset }]);
            setDirty(true);
          }
        }
        setConnectFrom(null);
        return;
      }
      setSelected({ type: target.isNode() ? "node" : "link", id: target.id() });
    },
    [connecting, connectFrom, nodes, links, presets],
  );

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.on("tap", onTap);
    const onDrag = () => setDirty(true);
    cy.on("dragfree", "node", onDrag);
    return () => {
      cy.off("tap", onTap);
      cy.off("dragfree", "node", onDrag);
    };
  }, [onTap]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().removeClass("connect-source");
    if (connectFrom) cy.getElementById(connectFrom).addClass("connect-source");
  }, [connectFrom]);

  // Live validation (debounced).
  useEffect(() => {
    const t = setTimeout(() => {
      validateTopology(topology as never).then(setCheck).catch(() => setCheck(null));
    }, 400);
    return () => clearTimeout(t);
  }, [topology]);

  // --- actions ------------------------------------------------------------------------------------
  const addNode = (layer: Layer) => {
    const base = layer === "iot" ? "gw" : layer;
    let i = nodes.filter((n) => n.layer === layer).length + 1;
    while (nodes.some((n) => n.id === `${base}-${i}`)) i++;
    const id = `${base}-${i}`;
    const preset = presets.devices[layer];
    const node: NodeSpec = {
      id, name: id, layer, cores: preset.cores, mips: preset.mips, ram_mb: preset.ram_mb, p_idle_w: preset.p_idle_w,
      p_max_w: preset.p_max_w, cost_per_core_s: preset.cost_per_core_s, mtbf_s: 0, mttr_s: 0,
    };
    setNodes((ns) => [...ns, node]);
    setSelected({ type: "node", id });
    setDirty(true);
  };

  const deleteSelected = useCallback(() => {
    if (!selected) return;
    if (selected.type === "node") {
      setNodes((ns) => ns.filter((n) => n.id !== selected.id));
      setLinks((ls) => ls.filter((l) => l.a !== selected.id && l.b !== selected.id));
    } else setLinks((ls) => ls.filter((l) => linkId(l) !== selected.id));
    setSelected(null);
    setDirty(true);
  }, [selected]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      if (e.key === "Delete" || e.key === "Backspace") deleteSelected();
      if (e.key === "Escape") {
        setConnecting(false);
        setConnectFrom(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteSelected]);

  const arrange = () => {
    const cy = cyRef.current;
    if (!cy) return;
    const layers = ["cloud", "fog", "edge", "iot"] as Layer[];
    const widest = Math.max(1, ...layers.map((l) => cy.nodes(`[layer = "${l}"]`).length));
    layers.forEach((layer) => {
      const row = cy.nodes(`[layer = "${layer}"]`).sort((a, b) => a.id().localeCompare(b.id(), undefined, { numeric: true }));
      const offset = ((widest - row.length) * 140) / 2; // centre each row under the widest one
      row.forEach((n, i) => {
        n.position({ x: 80 + offset + i * 140, y: LAYER_ROW[layer] });
      });
    });
    cy.fit(undefined, 40);
    setDirty(true);
  };

  const replaceWith = (topo: { nodes: NodeSpec[]; links: LinkSpec[] }, layout: Layout) => {
    const cy = cyRef.current;
    cy?.elements().remove();
    initial.layout = layout;
    setSelected(null);
    setNodes(topo.nodes);
    setLinks(topo.links);
    setDirty(true);
    setTimeout(() => cy?.fit(undefined, 40), 50);
  };

  const runGenerate = async () => {
    const gen = await generateTopology(genParams);
    const apply = () => replaceWith(gen.topology as never, gen.layout as Layout);
    setGenOpen(false);
    if (nodes.length) setConfirmReplace(() => apply);
    else apply();
  };

  const currentLayout = (): Layout => {
    const out: Layout = {};
    cyRef.current?.nodes().forEach((n) => {
      out[n.id()] = { x: Math.round(n.position().x), y: Math.round(n.position().y) };
    });
    return out;
  };

  const doSave = () =>
    save.mutate(
      { id: topoId, body: { name, description, topology: topology as never, layout: currentLayout() } },
      {
        onSuccess: (row) => {
          setDirty(false);
          setMessage("Saved.");
          if (!topoId) navigate(`/topology/${row.id}`, { replace: true });
        },
      },
    );

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ name, description, topology, layout: currentLayout() }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${name.replace(/[^a-z0-9]+/gi, "-").toLowerCase() || "topology"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const importJson = async (file: File) => {
    try {
      const data = JSON.parse(await file.text());
      const topo = data.topology ?? data;
      if (!Array.isArray(topo.nodes) || !Array.isArray(topo.links)) throw new Error("No nodes and links found");
      const apply = () => {
        if (data.name) setName(data.name);
        replaceWith(topo, data.layout ?? {});
      };
      if (nodes.length) setConfirmReplace(() => apply);
      else apply();
    } catch (e) {
      setMessage(`Couldn't import that file: ${(e as Error).message}`);
    }
  };

  const selNode = selected?.type === "node" ? nodes.find((n) => n.id === selected.id) : undefined;
  const selLink = selected?.type === "link" ? links.find((l) => linkId(l) === selected.id) : undefined;
  const updateNode = (patch: Partial<NodeSpec>) => {
    setNodes((ns) => ns.map((n) => (n.id === selNode?.id ? { ...n, ...patch } : n)));
    setDirty(true);
  };
  const updateLink = (patch: Partial<LinkSpec>) => {
    setLinks((ls) => ls.map((l) => (linkId(l) === selected?.id ? { ...l, ...patch } : l)));
    setDirty(true);
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-2.5">
        <Link to="/topology" className="text-sm text-ink-3 hover:text-accent">Topologies</Link>
        <span className="text-ink-3">/</span>
        <input aria-label="Topology name" value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }}
          className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 text-base font-semibold hover:border-line focus:border-line sm:max-w-sm" />
        <span className="text-xs text-ink-3">{dirty ? "Unsaved changes" : topoId ? "Saved" : ""}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button onClick={() => fileInput.current?.click()} title="Import a topology JSON file"><Upload className="size-4" />Import</Button>
          <Button onClick={exportJson} title="Download this topology as JSON"><Download className="size-4" />Export</Button>
          <Button variant="primary" onClick={doSave} disabled={save.isPending || !name.trim() || (check !== null && check.summary === null)}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
        <input ref={fileInput} type="file" accept="application/json,.json" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void importJson(f); e.target.value = ""; }} />
      </div>

      <div className="flex min-h-0 flex-1">
        <aside className="w-52 shrink-0 space-y-5 overflow-y-auto border-r border-line bg-surface-2 p-3 text-sm">
          <div>
            <h2 className="mb-2 text-xs font-medium text-ink-3">Add a node</h2>
            <div className="grid gap-1.5">
              {(["iot", "edge", "fog", "cloud"] as Layer[]).map((l) => (
                <Button key={l} className="justify-start" onClick={() => addNode(l)}><Plus className="size-4" />{LAYER_LABEL[l]}</Button>
              ))}
            </div>
          </div>
          <div>
            <h2 className="mb-2 text-xs font-medium text-ink-3">Edit</h2>
            <div className="grid gap-1.5">
              <Button className={cn("justify-start", connecting && "border-accent bg-accent-soft text-accent")} aria-pressed={connecting}
                onClick={() => { setConnecting(!connecting); setConnectFrom(null); }}>
                <Cable className="size-4" />{connecting ? "Connecting…" : "Connect nodes"}
              </Button>
              <Button className="justify-start" onClick={deleteSelected} disabled={!selected}><Trash2 className="size-4" />Delete selected</Button>
              <Button className="justify-start" onClick={arrange} disabled={!nodes.length}><LayoutGrid className="size-4" />Arrange by layer</Button>
              <Button className="justify-start" onClick={() => cyRef.current?.fit(undefined, 40)} disabled={!nodes.length}><Maximize className="size-4" />Fit to screen</Button>
              <Button className="justify-start" onClick={() => setGenOpen(true)}><Sparkles className="size-4" />Generate farm network</Button>
            </div>
            {connecting && (
              <p className="mt-2 text-xs text-ink-2">
                {connectFrom ? `Now click the node to connect to ${connectFrom}.` : "Click the first node, then the second. Esc to stop."}
              </p>
            )}
          </div>
          <div className="text-xs text-ink-3">
            <h2 className="mb-1 font-medium">Shapes</h2>
            <p>◇ gateway, ▢ edge, ⬡ fog, ◯ cloud. Thicker links have more bandwidth.</p>
          </div>
        </aside>

        <div className="relative min-w-0 flex-1 bg-bg">
          {/* Cytoscape forces position: relative on its container, so it gets its own sized wrapper. */}
          <div className="absolute inset-0">
            <div ref={container} className="h-full w-full" aria-label="Topology canvas" role="application" />
          </div>
          {!nodes.length && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-ink-3">
              Add nodes from the left, or generate a farm network to start from.
            </div>
          )}
        </div>

        <aside className="w-80 shrink-0 overflow-y-auto border-l border-line bg-surface p-4 text-sm">
          {selNode ? (
            <NodePanel node={selNode} update={updateNode} showAdvanced={mode === "researcher"} />
          ) : selLink ? (
            <LinkPanel link={selLink} update={updateLink} presets={presets} />
          ) : (
            <SummaryPanel check={check} description={description} setDescription={(d) => { setDescription(d); setDirty(true); }} />
          )}
          {message && <p className="mt-4 text-xs text-ink-2" role="status">{message}</p>}
          {save.error && <p className="mt-4 text-xs text-danger">{save.error.message}</p>}
        </aside>
      </div>

      {genOpen && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal aria-label="Generate farm network">
          <div className="w-full max-w-xl rounded-xl border border-line bg-surface p-5">
            <h2 className="text-base font-semibold">Generate a farm network</h2>
            <p className="mt-1 text-sm text-ink-2">Gateways connect to their farm's edge devices, farms share regional fog servers, and every fog server connects to the cloud.</p>
            <div className="mt-4">
              <SchemaForm schema={presets.generator_schema} values={genParams} onChange={setGenParams} showAdvanced={mode === "researcher"} />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button onClick={() => setGenOpen(false)}>Close</Button>
              <Button variant="primary" onClick={() => void runGenerate()}>Generate</Button>
            </div>
          </div>
        </div>
      )}
      <ConfirmDialog open={confirmReplace !== null} title="Replace the current network?"
        body="Everything on the canvas is replaced. Unsaved changes are lost." confirmLabel="Replace"
        onCancel={() => setConfirmReplace(null)} onConfirm={() => { confirmReplace?.(); setConfirmReplace(null); }} />
    </div>
  );
}

function Num({ label, value, onChange, unit, step = "any", min = 0, help }: {
  label: string; value: number; onChange: (v: number) => void; unit?: string; step?: string | number; min?: number; help?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex justify-between text-xs font-medium">{label}{unit && <span className="font-normal text-ink-3">{unit}</span>}</span>
      <input type="number" value={Number.isFinite(value) ? value : ""} step={step} min={min}
        onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
        className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5 tabular-nums" />
      {help && <span className="mt-0.5 block text-xs text-ink-3">{help}</span>}
    </label>
  );
}

function NodePanel({ node, update, showAdvanced }: { node: NodeSpec; update: (p: Partial<NodeSpec>) => void; showAdvanced: boolean }) {
  return (
    <div className="space-y-3">
      <div>
        <h2 className="font-semibold">{LAYER_LABEL[node.layer]}</h2>
        <p className="text-xs text-ink-3">ID {node.id}</p>
      </div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium">Display name</span>
        <input value={node.name} onChange={(e) => update({ name: e.target.value })} className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5" />
      </label>
      {node.layer === "iot" ? (
        <p className="text-xs text-ink-2">Gateways collect sensor data and drive actuators. Tasks start here; gateways don't run tasks.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <Num label="Cores" value={node.cores} step={1} min={1} onChange={(v) => update({ cores: Math.max(1, Math.round(v)) })} />
            <Num label="Speed per core" unit="MIPS" value={node.mips} onChange={(mips) => update({ mips })} />
          </div>
          <Num label="Memory" unit="MB" value={node.ram_mb} onChange={(ram_mb) => update({ ram_mb })} />
          <div className="grid grid-cols-2 gap-3">
            <Num label="Idle power" unit="W" value={node.p_idle_w} onChange={(p_idle_w) => update({ p_idle_w })} />
            <Num label="Peak power" unit="W" value={node.p_max_w} onChange={(p_max_w) => update({ p_max_w })} />
          </div>
          {showAdvanced ? (
            <>
              <Num label="Cost per busy core-second" unit="$" value={node.cost_per_core_s} onChange={(cost_per_core_s) => update({ cost_per_core_s })} />
              <div className="grid grid-cols-2 gap-3">
                <Num label="Mean time between failures" unit="s" value={node.mtbf_s} onChange={(mtbf_s) => update({ mtbf_s })} help="0 = never fails" />
                <Num label="Mean repair time" unit="s" value={node.mttr_s} onChange={(mttr_s) => update({ mttr_s })} />
              </div>
            </>
          ) : (
            <p className="text-xs text-ink-3">Switch to researcher mode for cost and failure settings.</p>
          )}
          <p className="text-xs text-ink-3">Capacity: {(node.cores * node.mips).toLocaleString()} MIPS.</p>
        </>
      )}
    </div>
  );
}

function LinkPanel({ link, update, presets }: { link: LinkSpec; update: (p: Partial<LinkSpec>) => void; presets: Presets }) {
  return (
    <div className="space-y-3">
      <div>
        <h2 className="font-semibold">Link</h2>
        <p className="text-xs text-ink-3">{link.a} ↔ {link.b}</p>
      </div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium">Technology</span>
        <select value={link.kind} onChange={(e) => update({ kind: e.target.value, ...presets.link_kinds[e.target.value] })}
          className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5">
          {LINK_KINDS.map((k) => <option key={k} value={k}>{k === "wan" ? "WAN / internet" : k === "nbiot" ? "NB-IoT" : k === "lorawan" ? "LoRaWAN" : k === "ble" ? "Bluetooth LE" : k.toUpperCase().replace("WIFI", "Wi-Fi").replace("ETHERNET", "Ethernet").replace("ZIGBEE", "Zigbee")}</option>)}
        </select>
        <span className="mt-0.5 block text-xs text-ink-3">Changing technology fills in typical values; adjust them to your measurements.</span>
      </label>
      <div className="grid grid-cols-2 gap-3">
        <Num label="Bandwidth" unit="Mbit/s" value={link.bandwidth_mbps} min={0.0001} onChange={(bandwidth_mbps) => update({ bandwidth_mbps })} />
        <Num label="Latency (one way)" unit="ms" value={link.latency_ms} onChange={(latency_ms) => update({ latency_ms })} />
      </div>
      <p className="text-xs text-ink-3">Sending 1 MB takes about {(8 / Math.max(link.bandwidth_mbps, 1e-6) + link.latency_ms / 1000).toFixed(2)} s over this link.</p>
    </div>
  );
}

function SummaryPanel({ check, description, setDescription }: { check: Check | null; description: string; setDescription: (d: string) => void }) {
  const layers = (check?.summary?.layers ?? {}) as Record<string, { nodes: number; capacity_mips: number }>;
  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-semibold">Network</h2>
        <p className="text-xs text-ink-3">Click a node or link to edit it.</p>
      </div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium">Description</span>
        <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5" />
      </label>
      {check?.summary && (
        <table className="w-full text-xs">
          <thead className="text-left text-ink-3"><tr><th className="pb-1 font-normal">Layer</th><th className="pb-1 text-right font-normal">Nodes</th><th className="pb-1 text-right font-normal">MIPS</th></tr></thead>
          <tbody className="divide-y divide-line">
            {(["cloud", "fog", "edge", "iot"] as Layer[]).map((l) => (
              <tr key={l}><td className="py-1">{LAYER_LABEL[l]}</td><td className="py-1 text-right tabular-nums">{layers[l]?.nodes ?? 0}</td><td className="py-1 text-right tabular-nums">{(layers[l]?.capacity_mips ?? 0).toLocaleString()}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      <div>
        <h3 className="text-xs font-medium">Check</h3>
        {!check ? <p className="text-xs text-ink-3">Checking…</p> : check.valid ? (
          <p className="mt-1 text-xs text-[var(--st-implemented)]">Ready to simulate.</p>
        ) : (
          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-danger">{check.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        )}
      </div>
    </div>
  );
}
