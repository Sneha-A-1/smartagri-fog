import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, type Job } from "./client";

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
