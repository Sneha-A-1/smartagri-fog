import {
  Activity,
  BookMarked,
  BrainCircuit,
  CalendarClock,
  ChartColumn,
  CloudSun,
  Crosshair,
  Database,
  Droplets,
  FileText,
  FlaskConical,
  FolderKanban,
  Funnel,
  Gauge,
  Layers,
  LayoutDashboard,
  Leaf,
  Library,
  type LucideIcon,
  Map as MapIcon,
  Network,
  Play,
  RadioTower,
  Settings,
  ShieldCheck,
  TestTubes,
  Tractor,
  Users,
} from "lucide-react";
import { type ComponentType, lazy } from "react";
import type en from "@/i18n/en";

export type GroupId = keyof typeof en.groups;
export type ModuleId = keyof typeof en.nav;
export type PageStatus = "implemented" | "simulated" | "needs-integration" | "planned";

export type ModuleManifest = {
  id: ModuleId;
  path: string;
  group: GroupId;
  icon: LucideIcon;
  status: PageStatus;
  /** Roadmap phase in which the page becomes functional. */
  phase: number;
  /** Permission needed to see the page in navigation. */
  permission?: string;
  /** What the page lets you do, in plain words. Shown on planned pages and in search. */
  description: string;
  component?: ComponentType;
};

export const GROUPS: GroupId[] = ["monitor", "data", "agri", "infrastructure", "research", "platform"];

/**
 * Every page in the application. To add a page: create its component and add one entry here.
 * Navigation, routing, search and status badges all come from this list.
 */
export const MODULES: ModuleManifest[] = [
  {
    id: "overview", path: "/", group: "monitor", icon: LayoutDashboard, status: "implemented", phase: 0,
    description: "Platform status, build progress, recent jobs and system health.",
    component: lazy(() => import("@/pages/Overview")),
  },
  {
    id: "digitalTwin", path: "/digital-twin", group: "monitor", icon: MapIcon, status: "planned", phase: 2,
    description: "Map of farms, fields, sensors, irrigation zones and network nodes, with switchable layers.",
  },
  {
    id: "farms", path: "/farms", group: "monitor", icon: Tractor, status: "planned", phase: 2,
    description: "Create and configure farms, fields, crops, soil types and agricultural scenarios.",
  },
  {
    id: "devices", path: "/devices", group: "monitor", icon: RadioTower, status: "planned", phase: 2,
    description: "Configure sensors and actuators and run the MQTT device simulator.",
  },
  {
    id: "acquisition", path: "/data/acquisition", group: "data", icon: Database, status: "planned", phase: 3,
    description: "Register data sources, upload CSV, Excel or JSON datasets, preview and validate them.",
  },
  {
    id: "retrieval", path: "/data/retrieval", group: "data", icon: Funnel, status: "planned", phase: 3,
    description: "Configure the retrieval pipeline and urgency rules; see which records become urgent tasks.",
  },
  {
    id: "processing", path: "/data/processing", group: "data", icon: FlaskConical, status: "planned", phase: 6,
    description: "Preprocessing, dimensionality reduction, clustering and anomaly detection with comparisons.",
  },
  {
    id: "irrigation", path: "/irrigation", group: "agri", icon: Droplets, status: "planned", phase: 6,
    description: "Crop- and soil-specific thresholds, pump and valve status, and irrigation recommendations.",
  },
  {
    id: "cropHealth", path: "/crop-health", group: "agri", icon: Leaf, status: "planned", phase: 6,
    description: "Upload leaf images and get disease predictions with confidence and recommendations.",
  },
  {
    id: "weather", path: "/weather", group: "agri", icon: CloudSun, status: "planned", phase: 6,
    description: "Weather trends, evapotranspiration, drought and heat-stress alerts.",
  },
  {
    id: "mlLab", path: "/ml-lab", group: "agri", icon: BrainCircuit, status: "planned", phase: 6,
    description: "Train, evaluate, version and compare machine-learning models on registered datasets.",
  },
  {
    id: "topology", path: "/topology", group: "infrastructure", icon: Network, status: "planned", phase: 1,
    description: "Drag-and-drop edge, fog and cloud nodes and links, or generate large topologies from parameters.",
  },
  {
    id: "resources", path: "/resources", group: "infrastructure", icon: Gauge, status: "planned", phase: 1,
    description: "CPU, memory, bandwidth, energy and queue length per node during simulations.",
  },
  {
    id: "catalogue", path: "/algorithms", group: "research", icon: Library, status: "implemented", phase: 0,
    permission: "plugin:read",
    description: "Browse every algorithm with its status, parameters and the phase it arrives in; run runnable ones.",
    component: lazy(() => import("@/pages/Catalogue")),
  },
  {
    id: "scheduling", path: "/scheduling", group: "research", icon: CalendarClock, status: "planned", phase: 1,
    description: "Task queues, allocations and the decision trace explaining why each task went to its node.",
  },
  {
    id: "optimization", path: "/optimization", group: "research", icon: Crosshair, status: "planned", phase: 4,
    description: "Multi-objective optimisation with convergence curves and Pareto fronts.",
  },
  {
    id: "simulation", path: "/simulation", group: "research", icon: Play, status: "planned", phase: 1,
    description: "Configure workloads and failure scenarios and run the discrete-event simulator.",
  },
  {
    id: "experiments", path: "/experiments", group: "research", icon: TestTubes, status: "planned", phase: 1,
    description: "Reproducible experiments: topology, workload, algorithms, seeds and repeated runs.",
  },
  {
    id: "evaluation", path: "/evaluation", group: "research", icon: ChartColumn, status: "planned", phase: 1,
    description: "Compare algorithms with confidence intervals, significance tests, energy and network metrics.",
  },
  {
    id: "literature", path: "/literature", group: "research", icon: BookMarked, status: "planned", phase: 1,
    description: "Import BibTeX, tag papers by layer, technique and metric, and build the research-gap matrix.",
  },
  {
    id: "advanced", path: "/advanced", group: "research", icon: Layers, status: "planned", phase: 7,
    description: "Federated learning, explainable AI, edge-AI profiling and remote sensing (NDVI).",
  },
  {
    id: "jobs", path: "/jobs", group: "platform", icon: Activity, status: "implemented", phase: 0,
    permission: "job:read",
    description: "Background jobs with live progress, cancellation and results.",
    component: lazy(() => import("@/pages/Jobs")),
  },
  {
    id: "projects", path: "/projects", group: "platform", icon: FolderKanban, status: "implemented", phase: 0,
    permission: "project:read",
    description: "Create projects that group your experiments, datasets and results.",
    component: lazy(() => import("@/pages/Projects")),
  },
  {
    id: "reports", path: "/reports", group: "platform", icon: FileText, status: "planned", phase: 5,
    description: "PDF, Excel and LaTeX reports, publication figures and reproducibility bundles.",
  },
  {
    id: "security", path: "/security", group: "platform", icon: ShieldCheck, status: "planned", phase: 7,
    description: "Device identity, encryption settings, data access rules and security-aware scheduling.",
  },
  {
    id: "settings", path: "/settings", group: "platform", icon: Settings, status: "implemented", phase: 0,
    description: "Theme, language, beginner or researcher mode, and system information.",
    component: lazy(() => import("@/pages/SettingsPage")),
  },
  {
    id: "users", path: "/users", group: "platform", icon: Users, status: "implemented", phase: 0,
    permission: "user:manage",
    description: "Users, roles and permissions for multi-user deployments.",
    component: lazy(() => import("@/pages/UsersPage")),
  },
];

export function visibleModules(permissions: string[] | undefined): ModuleManifest[] {
  return MODULES.filter((m) => !m.permission || !permissions || permissions.includes(m.permission));
}
