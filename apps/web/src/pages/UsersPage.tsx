import { type FormEvent, useState } from "react";
import { useCreateUser, useHealth, useMe, useUsers } from "@/api/hooks";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/PageHeader";

const ROLES = [
  ["researcher", "Researcher: experiments, algorithms, simulation"],
  ["farmer", "Farmer: farm monitoring and irrigation advice"],
  ["expert", "Agricultural expert: crop health and analysis"],
  ["admin", "Administrator: everything, including users"],
] as const;

export default function UsersPage() {
  const { data: me } = useMe();
  const { data: health } = useHealth();
  const canManage = me?.permissions.includes("user:manage") ?? false;
  const { data: users } = useUsers(canManage);
  const create = useCreateUser();
  const [form, setForm] = useState({ email: "", display_name: "", password: "", role: "researcher" });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { email: form.email, display_name: form.display_name, password: form.password, roles: [form.role] },
      { onSuccess: () => setForm({ email: "", display_name: "", password: "", role: "researcher" }) },
    );
  };

  return (
    <>
      <PageHeader
        title="Users and access"
        lead={
          health?.local_mode
            ? "You're in local mode: the platform runs for you alone and doesn't ask anyone to sign in. Accounts created here are used when the platform is deployed for several people."
            : "Each person signs in with their own account. Their role decides which pages and actions they can use."
        }
      />
      <div className="grid gap-12 lg:grid-cols-[1fr_20rem]">
        <ul className="divide-y divide-line border-y border-line text-sm">
          {users?.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{u.display_name}</div>
                <div className="text-ink-3">{u.email}</div>
              </div>
              <span className="text-ink-2 capitalize">{u.roles.join(", ")}</span>
            </li>
          ))}
        </ul>

        <form onSubmit={submit} className="space-y-4 text-sm">
          <h2 className="text-lg font-semibold">Add a user</h2>
          {(
            [
              ["display_name", "Name", "text"],
              ["email", "Email", "email"],
              ["password", "Password (8 characters or more)", "password"],
            ] as const
          ).map(([key, label, type]) => (
            <label key={key} className="block">
              <span className="mb-1.5 block font-medium">{label}</span>
              <input
                required
                type={type}
                minLength={key === "password" ? 8 : undefined}
                value={form[key]}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                className="w-full rounded-lg border border-line bg-surface px-3 py-2"
              />
            </label>
          ))}
          <label className="block">
            <span className="mb-1.5 block font-medium">Role</span>
            <select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2"
            >
              {ROLES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {create.error && <p className="text-danger">{create.error.message}</p>}
          {create.isSuccess && <p className="text-[var(--st-implemented)]">User added.</p>}
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Add user
          </Button>
        </form>
      </div>
    </>
  );
}
