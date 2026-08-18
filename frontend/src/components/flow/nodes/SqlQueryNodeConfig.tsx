"use client";

import { useCallback, useEffect, useState } from "react";

import {
  createDbConnection,
  listDbConnections,
  type DbConnectionRecord,
  type DbConnectionType,
} from "@/lib/integrations/dbConnectionsApi";
import type { FlowNodeData, SqlQueryNodeData } from "@/types/flow";

type PatchFn = (partial: Partial<FlowNodeData>) => void;

const inputClass =
  "w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-zinc-600";
const textareaClass = `${inputClass} min-h-[120px] resize-y font-mono text-xs`;

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function CreateConnectionModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (row: DbConnectionRecord) => void;
}) {
  const [name, setName] = useState("");
  const [dbType, setDbType] = useState<DbConnectionType>("postgresql");
  const [connectionString, setConnectionString] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return null;
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const created = await createDbConnection({
        name: name.trim(),
        db_type: dbType,
        connection_string: connectionString.trim(),
      });
      onCreated(created);
      setName("");
      setDbType("postgresql");
      setConnectionString("");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create connection");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#121214] p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-zinc-100">New SQL connection</h3>
            <p className="mt-1 text-xs text-zinc-500">
              Connection string is encrypted at rest and never returned by the API.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="flex flex-col gap-3">
          <Field label="Name">
            <input
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Production Read Replica"
              required
            />
          </Field>
          <Field label="Database type">
            <select
              className={inputClass}
              value={dbType}
              onChange={(e) => setDbType(e.target.value as DbConnectionType)}
            >
              <option value="postgresql">PostgreSQL</option>
              <option value="mysql">MySQL</option>
            </select>
          </Field>
          <Field label="Connection string">
            <textarea
              className={textareaClass}
              value={connectionString}
              onChange={(e) => setConnectionString(e.target.value)}
              placeholder="postgresql://user:pass@host:5432/dbname"
              required
            />
          </Field>
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-zinc-700 px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-sky-600 px-3 py-2 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save connection"}
          </button>
        </div>
      </form>
    </div>
  );
}

export function SqlQueryNodeConfig({
  data,
  patch,
}: {
  data: SqlQueryNodeData;
  patch: PatchFn;
}) {
  const [connections, setConnections] = useState<DbConnectionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await listDbConnections();
      setConnections(response.items);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load connections");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectedId = data.connection_id ?? "";

  return (
    <>
      <Field label="Saved connection">
        <select
          className={inputClass}
          value={selectedId}
          disabled={loading}
          onChange={(e) => {
            const nextId = e.target.value;
            const match = connections.find((item) => item.id === nextId);
            patch({
              connection_id: nextId || null,
              connection_label: match?.name ?? "",
              connection_string: "",
            });
          }}
        >
          <option value="">Select a connection…</option>
          {connections.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} ({item.db_type})
            </option>
          ))}
        </select>
      </Field>

      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="rounded-md border border-dashed border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
        >
          + Add connection
        </button>
        <button
          type="button"
          onClick={() => void refresh()}
          className="text-[11px] text-zinc-500 hover:text-zinc-300"
        >
          Refresh
        </button>
      </div>

      {loadError && <p className="text-xs text-amber-400">{loadError}</p>}

      <Field label="SQL Query">
        <textarea
          className={textareaClass}
          value={data.query}
          onChange={(e) => patch({ query: e.target.value })}
          placeholder={
            "SELECT * FROM products\nWHERE sku = {{ session.variables.user_sku }}\nLIMIT 1"
          }
        />
      </Field>

      <p className="text-[11px] text-zinc-600">
        Only read-only <code className="text-zinc-400">SELECT</code> queries are allowed. Use
        placeholders like <code className="text-zinc-400">{`{{ session.variables.user_sku }}`}</code>.
      </p>

      <Field label="Result Variable">
        <input
          className={inputClass}
          value={data.result_variable}
          onChange={(e) => patch({ result_variable: e.target.value })}
          placeholder="sql_result"
        />
      </Field>

      <Field label="Max Rows">
        <input
          type="number"
          min={1}
          max={500}
          className={inputClass}
          value={data.max_rows}
          onChange={(e) =>
            patch({ max_rows: Math.max(1, Math.min(500, Number(e.target.value) || 1)) })
          }
        />
      </Field>

      <CreateConnectionModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(row) => {
          setConnections((prev) => [row, ...prev]);
          patch({
            connection_id: row.id,
            connection_label: row.name,
            connection_string: "",
          });
        }}
      />
    </>
  );
}
