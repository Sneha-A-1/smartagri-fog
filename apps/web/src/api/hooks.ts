import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, type Experiment, type Job, type LitEntry } from "./client";

async function unwrap<T>(p: Promise<{ data?: T; error?: unknown }>): Promise<T> {
  const { data, error } = await p;
  if (error !== undefined) throw new Error(errorMessage(error));
  return data as T;
}

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: () => unwrap(api.GET("/api/health")), refetchInterval: 15000 });

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => unwrap(api.GET("/api/auth/me")) });

export const useSystemInfo = () =>
  useQuery({ queryKey: ["system-info"], queryFn: () => unwrap(api.GET("/api/system/info")) });

export const usePlugins = () => useQuery({ queryKey: ["plugins"], queryFn: () => unwrap(api.GET("/api/plugins")) });

export const usePlugin = (id: string) =>
  useQuery({
    queryKey: ["plugin", id],
    queryFn: () => unwrap(api.GET("/api/plugins/{plugin_id}", { params: { path: { plugin_id: id } } })),
  });

export const useJobs = () =>
  useQuery({ queryKey: ["jobs"], queryFn: () => unwrap(api.GET("/api/jobs", { params: { query: { limit: 100 } } })) });

export const useJob = (id: string) =>
  useQuery({
    queryKey: ["job", id],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })),
  });

export const useJobResult = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: ["job-result", id],
    enabled,
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/result", { params: { path: { job_id: id } } })),
  });

export function useStartJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { plugin_id: string; params: Record<string, unknown>; project_id?: string | null }) =>
      unwrap(api.POST("/api/jobs", { body })),
    onSuccess: (job: Job) => {
      qc.setQueryData<Job[]>(["jobs"], (old) => [job, ...(old ?? [])]);
    },
  });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/jobs/{job_id}/cancel", { params: { path: { job_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

export const useProjects = () =>
  useQuery({ queryKey: ["projects"], queryFn: () => unwrap(api.GET("/api/projects")) });

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description: string; default_seed: number }) =>
      unwrap(api.POST("/api/projects", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/projects/{project_id}", { params: { path: { project_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export const useUsers = (enabled: boolean) =>
  useQuery({ queryKey: ["users"], enabled, queryFn: () => unwrap(api.GET("/api/users")) });

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; display_name: string; password: string; roles: string[] }) =>
      unwrap(api.POST("/api/users", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export const useServerSettings = () =>
  useQuery({ queryKey: ["settings"], queryFn: () => unwrap(api.GET("/api/settings/me")) });

export function useSaveServerSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) => unwrap(api.PUT("/api/settings/me", { body: { values } })),
    onSuccess: (data) => qc.setQueryData(["settings"], data),
  });
}

// --- experiments -------------------------------------------------------------------------------

const ACTIVE = new Set(["queued", "running"]);

export const useExperimentSchema = () =>
  useQuery({ queryKey: ["experiment-schema"], queryFn: () => unwrap(api.GET("/api/experiments/schema")), staleTime: Infinity });

export const useExperiments = () =>
  useQuery({
    queryKey: ["experiments"],
    queryFn: () => unwrap(api.GET("/api/experiments")),
    refetchInterval: (q) => (q.state.data?.some((e) => ACTIVE.has(e.status)) ? 2000 : false),
  });

export const useExperiment = (id: string) =>
  useQuery({
    queryKey: ["experiment", id],
    enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/experiments/{exp_id}", { params: { path: { exp_id: id } } })),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 1500 : false),
  });

export const useExperimentResult = (id: string, enabled: boolean, jobId: string | null | undefined) =>
  useQuery({
    queryKey: ["experiment-result", id, jobId],
    enabled,
    staleTime: Infinity,
    queryFn: () => unwrap(api.GET("/api/experiments/{exp_id}/result", { params: { path: { exp_id: id } } })),
  });

function useExperimentMutation<T>(fn: (arg: T) => Promise<Experiment>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (exp) => {
      qc.setQueryData(["experiment", exp.id], exp);
      qc.invalidateQueries({ queryKey: ["experiments"] });
    },
  });
}

export const useCreateExperiment = () =>
  useExperimentMutation((body: { spec: Record<string, unknown>; project_id?: string | null }) =>
    unwrap(api.POST("/api/experiments", { body })),
  );

export const useUpdateExperiment = () =>
  useExperimentMutation(({ id, spec }: { id: string; spec: Record<string, unknown> }) =>
    unwrap(api.PUT("/api/experiments/{exp_id}", { params: { path: { exp_id: id } }, body: { spec } })),
  );

export const useRunExperiment = () =>
  useExperimentMutation((id: string) =>
    unwrap(api.POST("/api/experiments/{exp_id}/run", { params: { path: { exp_id: id } } })),
  );

export const useCancelExperiment = () =>
  useExperimentMutation((id: string) =>
    unwrap(api.POST("/api/experiments/{exp_id}/cancel", { params: { path: { exp_id: id } } })),
  );

export const useDuplicateExperiment = () =>
  useExperimentMutation((id: string) =>
    unwrap(api.POST("/api/experiments/{exp_id}/duplicate", { params: { path: { exp_id: id } } })),
  );

export function useDeleteExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/experiments/{exp_id}", { params: { path: { exp_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiments"] }),
  });
}

// --- designed topologies and workloads ---------------------------------------------------------

export const useDesignPresets = () =>
  useQuery({ queryKey: ["design-presets"], queryFn: () => unwrap(api.GET("/api/topologies/presets")), staleTime: Infinity });

export const useTopologies = () => useQuery({ queryKey: ["topologies"], queryFn: () => unwrap(api.GET("/api/topologies")) });

export const useTopology = (id: string) =>
  useQuery({
    queryKey: ["topology", id],
    enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/topologies/{topo_id}", { params: { path: { topo_id: id } } })),
  });

type TopologyBody = { name: string; description: string; topology: Record<string, unknown>; layout: Record<string, unknown>; project_id?: string | null };

export function useSaveTopology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: TopologyBody }) =>
      id
        ? unwrap(api.PUT("/api/topologies/{topo_id}", { params: { path: { topo_id: id } }, body }))
        : unwrap(api.POST("/api/topologies", { body })),
    onSuccess: (row) => {
      qc.setQueryData(["topology", row.id], row);
      qc.invalidateQueries({ queryKey: ["topologies"] });
    },
  });
}

export function useDuplicateTopology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/topologies/{topo_id}/duplicate", { params: { path: { topo_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["topologies"] }),
  });
}

export function useDeleteTopology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/topologies/{topo_id}", { params: { path: { topo_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["topologies"] }),
  });
}

export const generateTopology = (params: Record<string, unknown>) =>
  unwrap(api.POST("/api/topologies/generate", { body: params as never }));

export const validateTopology = (topology: Record<string, unknown>) =>
  unwrap(api.POST("/api/topologies/validate", { body: { topology } }));

export const useWorkloadTemplate = () =>
  useQuery({ queryKey: ["workload-template"], queryFn: () => unwrap(api.GET("/api/workloads/template")), staleTime: Infinity });

export const useWorkloads = () => useQuery({ queryKey: ["workloads"], queryFn: () => unwrap(api.GET("/api/workloads")) });

export const useWorkload = (id: string) =>
  useQuery({
    queryKey: ["workload", id],
    enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/workloads/{wl_id}", { params: { path: { wl_id: id } } })),
  });

type WorkloadBody = { name: string; description: string; spec: Record<string, unknown>; project_id?: string | null };

export function useSaveWorkload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: WorkloadBody }) =>
      id
        ? unwrap(api.PUT("/api/workloads/{wl_id}", { params: { path: { wl_id: id } }, body }))
        : unwrap(api.POST("/api/workloads", { body })),
    onSuccess: (row) => {
      qc.setQueryData(["workload", row.id], row);
      qc.invalidateQueries({ queryKey: ["workloads"] });
    },
  });
}

export function useDeleteWorkload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/workloads/{wl_id}", { params: { path: { wl_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workloads"] }),
  });
}

export const previewWorkload = (spec: Record<string, unknown>, topology?: Record<string, unknown> | null) =>
  unwrap(api.POST("/api/workloads/preview", { body: { spec, topology: topology ?? null } }));

export function useStartSimulation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { topology_id: string; workload_id: string; placement: string; discipline: string; seed: number; settings: Record<string, unknown>; project_id?: string | null }) =>
      unwrap(api.POST("/api/simulations", { body: body as never })),
    onSuccess: (job: Job) => qc.setQueryData<Job[]>(["jobs"], (old) => [job, ...(old ?? [])]),
  });
}

export const fetchTopology = (id: string) =>
  unwrap(api.GET("/api/topologies/{topo_id}", { params: { path: { topo_id: id } } }));
export const fetchWorkload = (id: string) => unwrap(api.GET("/api/workloads/{wl_id}", { params: { path: { wl_id: id } } }));

// --- literature ----------------------------------------------------------------------------------

export const useLiterature = () => useQuery({ queryKey: ["literature"], queryFn: () => unwrap(api.GET("/api/literature")) });

export const useLitVocabulary = () =>
  useQuery({ queryKey: ["literature-vocabulary"], queryFn: () => unwrap(api.GET("/api/literature/vocabulary")) });

export const useLitPrisma = () =>
  useQuery({ queryKey: ["literature-prisma"], queryFn: () => unwrap(api.GET("/api/literature/prisma")) });

export const useLitMatrix = (rows: string, cols: string, stage: string) =>
  useQuery({
    queryKey: ["literature-matrix", rows, cols, stage],
    queryFn: () => unwrap(api.GET("/api/literature/matrix", { params: { query: { rows: rows as never, cols: cols as never, stage } } })),
  });

function invalidateLiterature(qc: ReturnType<typeof useQueryClient>) {
  for (const key of ["literature", "literature-prisma", "literature-matrix", "literature-vocabulary"])
    qc.invalidateQueries({ queryKey: [key] });
}

export function useUpdateLit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      unwrap(api.PATCH("/api/literature/{entry_id}", { params: { path: { entry_id: id } }, body: patch as never })),
    onSuccess: (row) => {
      qc.setQueryData<LitEntry[]>(["literature"], (old) => old?.map((e) => (e.id === row.id ? row : e)));
      invalidateLiterature(qc);
    },
  });
}

export function useCreateLit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; authors: string; year: number | null; venue: string; doi: string }) =>
      unwrap(api.POST("/api/literature", { body: { url: "", abstract: "", bibtex_key: "", ...body } })),
    onSuccess: () => invalidateLiterature(qc),
  });
}

export function useDeleteLit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/literature/{entry_id}", { params: { path: { entry_id: id } } })),
    onSuccess: () => invalidateLiterature(qc),
  });
}

export function useImportLit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, source }: { file: File; source: string }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("source", source);
      return unwrap(api.POST("/api/literature/import", { body: form as never, bodySerializer: (b) => b as unknown as FormData }));
    },
    onSuccess: () => invalidateLiterature(qc),
  });
}

// --- farms, weather and irrigation ---------------------------------------------------------------

export type WeatherSource = "open_meteo" | "csv" | "synthetic";

export const useAgroPresets = () =>
  useQuery({ queryKey: ["agro-presets"], staleTime: Infinity, queryFn: () => unwrap(api.GET("/api/agro/presets")) });

export const useFarms = () => useQuery({ queryKey: ["farms"], queryFn: () => unwrap(api.GET("/api/farms")) });

export const useFarm = (id: string) =>
  useQuery({
    queryKey: ["farm", id],
    enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/farms/{farm_id}", { params: { path: { farm_id: id } } })),
  });

function invalidateFarms(qc: ReturnType<typeof useQueryClient>) {
  for (const key of ["farms", "farm", "water-balance"]) qc.invalidateQueries({ queryKey: [key] });
}

export function useCreateFarm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: FarmBody) => unwrap(api.POST("/api/farms", { body: { description: "", region: "", ...body } })),
    onSuccess: () => invalidateFarms(qc),
  });
}

export type FarmBody = { name: string; latitude: number; longitude: number; elevation_m: number; region?: string; description?: string; project_id?: string | null };

export function useUpdateFarm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<FarmBody> }) =>
      unwrap(api.PATCH("/api/farms/{farm_id}", { params: { path: { farm_id: id } }, body: patch })),
    onSuccess: () => invalidateFarms(qc),
  });
}

export function useDeleteFarm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/farms/{farm_id}", { params: { path: { farm_id: id } } })),
    onSuccess: () => invalidateFarms(qc),
  });
}

export function useCreateField() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, body }: { farmId: string; body: Record<string, unknown> }) =>
      unwrap(api.POST("/api/farms/{farm_id}/fields", { params: { path: { farm_id: farmId } }, body: body as never })),
    onSuccess: () => invalidateFarms(qc),
  });
}

export function useUpdateField() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      unwrap(api.PATCH("/api/fields/{field_id}", { params: { path: { field_id: id } }, body: patch as never })),
    onSuccess: () => invalidateFarms(qc),
  });
}

export function useDeleteField() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/fields/{field_id}", { params: { path: { field_id: id } } })),
    onSuccess: () => invalidateFarms(qc),
  });
}

export const useFarmWeather = (farmId: string, source: WeatherSource, start?: string, end?: string) =>
  useQuery({
    queryKey: ["weather", farmId, source, start, end],
    enabled: Boolean(farmId),
    retry: false,
    queryFn: () =>
      unwrap(api.GET("/api/farms/{farm_id}/weather", { params: { path: { farm_id: farmId }, query: { source, start, end } } })),
  });

export function useImportWeatherCsv() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, file }: { farmId: string; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return unwrap(
        api.POST("/api/farms/{farm_id}/weather/csv", {
          params: { path: { farm_id: farmId } },
          body: form as never,
          bodySerializer: (b) => b as unknown as FormData,
        }),
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["weather"] });
      qc.invalidateQueries({ queryKey: ["water-balance"] });
    },
  });
}

export const useWaterBalance = (fieldId: string, source: WeatherSource, useSensors = false, trigger?: number) =>
  useQuery({
    queryKey: ["water-balance", fieldId, source, useSensors, trigger],
    enabled: Boolean(fieldId),
    retry: false,
    queryFn: () =>
      unwrap(
        api.GET("/api/fields/{field_id}/water-balance", {
          params: { path: { field_id: fieldId }, query: { source, trigger, use_sensors: useSensors } },
        }),
      ),
  });

export const placeSearch = (q: string) => unwrap(api.GET("/api/geo/search", { params: { query: { q } } }));
export const elevationAt = (latitude: number, longitude: number) =>
  unwrap(api.GET("/api/geo/elevation", { params: { query: { latitude, longitude } } }));

// --- devices and digital twin --------------------------------------------------------------------

export const useDeviceKinds = () =>
  useQuery({ queryKey: ["device-kinds"], staleTime: Infinity, queryFn: () => unwrap(api.GET("/api/devices/kinds")) });

export const useDevices = (farmId?: string) =>
  useQuery({
    queryKey: ["devices", farmId],
    refetchInterval: 60_000,
    retry: false,
    queryFn: () => unwrap(api.GET("/api/devices", { params: { query: { farm_id: farmId } } })),
  });

function invalidateDevices(qc: ReturnType<typeof useQueryClient>) {
  for (const key of ["devices", "readings", "twin", "water-balance"]) qc.invalidateQueries({ queryKey: [key] });
}

export function useCreateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, body }: { farmId: string; body: Record<string, unknown> }) =>
      unwrap(api.POST("/api/farms/{farm_id}/devices", { params: { path: { farm_id: farmId } }, body: body as never })),
    onSuccess: () => invalidateDevices(qc),
  });
}

export function useUpdateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      unwrap(api.PATCH("/api/devices/{device_id}", { params: { path: { device_id: id } }, body: patch as never })),
    onSuccess: () => invalidateDevices(qc),
  });
}

export function useDeleteDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/devices/{device_id}", { params: { path: { device_id: id } } })),
    onSuccess: () => invalidateDevices(qc),
  });
}

export function useResetDeviceToken() {
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/devices/{device_id}/token", { params: { path: { device_id: id } } })),
  });
}

export const useReadings = (deviceId: string, metric: string, days = 14) =>
  useQuery({
    queryKey: ["readings", deviceId, metric, days],
    enabled: Boolean(deviceId && metric),
    refetchInterval: 60_000,
    queryFn: () =>
      unwrap(
        api.GET("/api/devices/{device_id}/readings", {
          params: {
            path: { device_id: deviceId },
            query: { metric, start: new Date(Date.now() - days * 864e5).toISOString(), max_points: 600 },
          },
        }),
      ),
  });

export const useTwin = (source: WeatherSource, useSensors: boolean) =>
  useQuery({
    queryKey: ["twin", source, useSensors],
    refetchInterval: 60_000,
    retry: false,
    queryFn: () => unwrap(api.GET("/api/twin", { params: { query: { source, use_sensors: useSensors } } })),
  });

// --- data retrieval framework --------------------------------------------------------------------

export function useRunRetrieval() {
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => unwrap(api.POST("/api/retrieval/run", { body: body as never })),
  });
}
