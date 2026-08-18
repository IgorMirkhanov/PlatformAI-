"use client";

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface AdminColumn<T> {
  id: string;
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
}

interface AdminDataTableProps<T> {
  columns: AdminColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  search?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  loading?: boolean;
  emptyMessage?: string;
  toolbar?: ReactNode;
  className?: string;
  /** Server-side pagination */
  page?: number;
  pageSize?: number;
  total?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
}

export function AdminDataTable<T>({
  columns,
  rows,
  rowKey,
  search,
  onSearchChange,
  searchPlaceholder = "Search…",
  loading = false,
  emptyMessage = "No rows found.",
  toolbar,
  className,
  page = 1,
  pageSize = 20,
  total,
  totalPages,
  onPageChange,
}: AdminDataTableProps<T>) {
  const columnDefs: ColumnDef<T, unknown>[] = columns.map((column) => ({
    id: column.id,
    header: column.header,
    cell: ({ row }) => column.cell(row.original),
    meta: { className: column.className },
  }));

  const table = useReactTable({
    data: rows,
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => rowKey(row),
    manualPagination: true,
    pageCount: totalPages ?? -1,
  });

  const computedTotalPages =
    totalPages ??
    (typeof total === "number" && pageSize > 0
      ? Math.max(1, Math.ceil(total / pageSize))
      : 1);
  const showPager = Boolean(onPageChange) && computedTotalPages > 0;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {onSearchChange ? (
          <label className="relative block min-w-[240px] max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <input
              value={search ?? ""}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder={searchPlaceholder}
              className="w-full rounded-xl border border-zinc-800 bg-zinc-950/80 py-2 pl-9 pr-3 text-sm text-zinc-100 outline-none ring-amber-500/30 placeholder:text-zinc-600 focus:ring-2"
            />
          </label>
        ) : (
          <div />
        )}
        {toolbar}
      </div>

      <div className="overflow-hidden rounded-2xl border border-zinc-800/80">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-zinc-950/90 text-xs uppercase tracking-wider text-zinc-500">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const meta = header.column.columnDef.meta as
                      | { className?: string }
                      | undefined;
                    return (
                      <th
                        key={header.id}
                        className={cn("px-4 py-3 font-medium", meta?.className)}
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(header.column.columnDef.header, header.getContext())}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody className="divide-y divide-zinc-800/80 bg-zinc-950/40">
              {loading ? (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-10 text-center text-zinc-500">
                    Loading…
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-10 text-center text-zinc-500">
                    {emptyMessage}
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="hover:bg-zinc-900/40">
                    {row.getVisibleCells().map((cell) => {
                      const meta = cell.column.columnDef.meta as
                        | { className?: string }
                        | undefined;
                      return (
                        <td
                          key={cell.id}
                          className={cn("px-4 py-3 text-zinc-200", meta?.className)}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      );
                    })}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showPager ? (
        <div className="flex items-center justify-between gap-3 text-xs text-zinc-500">
          <p>
            Page {page} of {Math.max(1, computedTotalPages)}
            {typeof total === "number" ? ` · ${total} total` : null}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => onPageChange?.(Math.max(1, page - 1))}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1.5 text-zinc-300 transition hover:border-zinc-600 disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Prev
            </button>
            <button
              type="button"
              disabled={page >= computedTotalPages || loading}
              onClick={() => onPageChange?.(Math.min(computedTotalPages, page + 1))}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1.5 text-zinc-300 transition hover:border-zinc-600 disabled:opacity-40"
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
