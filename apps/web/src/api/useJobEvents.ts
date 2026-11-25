import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { Job } from "./client";

type ProgressEvent = { type: "job.progress"; job_id: string; progress: number; message: string; status: string };
type FinishedEvent = { type: "job.finished"; job: Job };

/** Keeps every job in the query cache live by listening to the API's WebSocket. Reconnects automatically. */
export function useJobEvents(): void {
  const qc = useQueryClient();

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const patch = (id: string, update: (job: Job) => Job) => {
      qc.setQueryData<Job[]>(["jobs"], (old) => old?.map((j) => (j.id === id ? update(j) : j)));
      qc.setQueryData<Job>(["job", id], (old) => (old ? update(old) : old));
    };

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${window.location.host}/api/ws/jobs`);
      socket.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as ProgressEvent | FinishedEvent;
        if (event.type === "job.progress") {
          patch(event.job_id, (j) => ({ ...j, status: "running", progress: event.progress, message: event.message }));
        } else if (event.type === "job.finished") {
          patch(event.job.id, () => event.job);
          qc.invalidateQueries({ queryKey: ["jobs"] });
        }
      };
      socket.onclose = () => {
        if (!closed) retry = setTimeout(connect, 2000);
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, [qc]);
}
