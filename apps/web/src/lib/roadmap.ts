/** Development roadmap, mirrored from the project document. Update CURRENT_PHASE as phases complete. */
export const CURRENT_PHASE = 1;

export const PHASES = [
  { n: 0, name: "Foundations", goal: "Platform skeleton, plugin registry, jobs, access control" },
  { n: 1, name: "Research spine", goal: "Topology, workloads, baseline schedulers, simulator, experiments" },
  { n: 2, name: "Farm and device world", goal: "Farms, digital-twin map, MQTT device simulator" },
  { n: 3, name: "Data retrieval", goal: "Pipeline, urgency classification, event injection" },
  { n: 4, name: "Scheduling and optimisation", goal: "Metaheuristics, NSGA-II, learned policies, AURA" },
  { n: 5, name: "Evaluation and reporting", goal: "Sweeps, statistics, LaTeX and PDF reports" },
  { n: 6, name: "Agri-intelligence", goal: "ML lab, irrigation, crop health, weather" },
  { n: 7, name: "Advanced modules", goal: "Federated learning, explainable AI, remote sensing" },
] as const;
