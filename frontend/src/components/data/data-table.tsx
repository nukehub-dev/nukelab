import { useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type RowSelectionState,
  type ColumnFiltersState,
  type VisibilityState,
} from '@tanstack/react-table';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronUp, GripVertical } from 'lucide-react';
import { cn } from '../../lib/utils';
import { DataTablePagination } from './data-table-pagination';
import { DataTableToolbar } from './data-table-toolbar';
import { DataTableMobile } from './data-table-mobile';
import { SkeletonTable } from '../feedback/skeleton';

interface DataTableProps<TData> {
  columns: ColumnDef<TData, unknown>[];
  data: TData[];
  totalCount: number;
  pageCount: number;
  page: number;
  limit: number;
  sorting: SortingState;
  rowSelection: RowSelectionState;
  columnFilters: ColumnFiltersState;
  columnVisibility: VisibilityState;
  globalFilter: string;
  isLoading?: boolean;
  isError?: boolean;
  errorMessage?: string;
  onPageChange: (page: number) => void;
  onLimitChange: (limit: number) => void;
  onSortingChange: (sorting: SortingState) => void;
  onRowSelectionChange: (selection: RowSelectionState) => void;
  onColumnFiltersChange: (filters: ColumnFiltersState) => void;
  onColumnVisibilityChange: (updater: VisibilityState | ((old: VisibilityState) => VisibilityState)) => void;
  onGlobalFilterChange: (filter: string) => void;
  getRowId?: (row: TData) => string;
  bulkActions?: Array<{
    label: string;
    icon: React.ReactNode;
    onClick: (selectedIds: string[]) => void;
    variant?: 'default' | 'destructive';
  }>;
  filters?: Array<{
    key: string;
    label: string;
    options: Array<{ label: string; value: string }>;
  }>;
  searchable?: boolean;
  searchPlaceholder?: string;
  emptyState?: React.ReactNode;
  mobileCardRenderer?: (row: TData) => React.ReactNode;
  enableRowSelection?: boolean;
}

export function DataTable<TData>({
  columns,
  data,
  totalCount,
  pageCount,
  page,
  limit,
  sorting,
  rowSelection,
  columnFilters,
  columnVisibility,
  globalFilter,
  isLoading,
  isError,
  errorMessage,
  onPageChange,
  onLimitChange,
  onSortingChange,
  onRowSelectionChange,
  onColumnFiltersChange,
  onColumnVisibilityChange,
  onGlobalFilterChange,
  getRowId,
  bulkActions,
  filters,
  searchable = true,
  searchPlaceholder = 'Search...',
  emptyState,
  mobileCardRenderer,
  enableRowSelection = true,
}: DataTableProps<TData>) {
  const [showMobile, setShowMobile] = useState(false);

  const table = useReactTable({
    data,
    columns,
    pageCount,
    state: {
      sorting,
      rowSelection,
      columnFilters,
      columnVisibility,
      globalFilter,
      pagination: { pageIndex: page - 1, pageSize: limit },
    },
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    enableRowSelection,
    getRowId,
    onSortingChange: (updater) => {
      const newSorting = typeof updater === 'function' ? updater(sorting) : updater;
      onSortingChange(newSorting);
    },
    onRowSelectionChange: (updater) => {
      const newSelection = typeof updater === 'function' ? updater(rowSelection) : updater;
      onRowSelectionChange(newSelection);
    },
    onColumnFiltersChange: (updater) => {
      const newFilters = typeof updater === 'function' ? updater(columnFilters) : updater;
      onColumnFiltersChange(newFilters);
    },
    onColumnVisibilityChange: onColumnVisibilityChange,
    onGlobalFilterChange: onGlobalFilterChange,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const selectedRows = table.getSelectedRowModel().rows;
  const selectedIds = selectedRows.map((row) => getRowId?.(row.original) || String(row.id));

  return (
    <div className="space-y-4">
      <DataTableToolbar
        table={table}
        globalFilter={globalFilter}
        onGlobalFilterChange={onGlobalFilterChange}
        selectedCount={selectedRows.length}
        selectedIds={selectedIds}
        bulkActions={bulkActions}
        filters={filters}
        searchable={searchable}
        searchPlaceholder={searchPlaceholder}
        onViewToggle={() => setShowMobile(!showMobile)}
        isMobileView={showMobile}
      />

      {isLoading ? (
        <SkeletonTable rows={limit} columns={columns.length} />
      ) : isError ? (
        <div className="bubble p-8 text-center space-y-4">
          <p className="text-destructive font-medium">{errorMessage || 'Failed to load data'}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            Retry
          </button>
        </div>
      ) : data.length === 0 ? (
        emptyState || (
          <div className="bubble p-8 text-center">
            <p className="text-muted-foreground">No results found</p>
          </div>
        )
      ) : (
        <>
          {/* Desktop Table */}
          <div className={cn('hidden md:block overflow-hidden rounded-xl border border-border/50')} >
            <div className="overflow-x-auto">
              <table className="w-full caption-bottom text-sm">
                <thead className="bg-muted/50 sticky top-0 z-10">
                  {table.getHeaderGroups().map((headerGroup) => (
                    <tr key={headerGroup.id} className="border-b border-border/50 transition-colors">
                      {headerGroup.headers.map((header) => (
                        <th
                          key={header.id}
                          className={cn(
                            'h-10 px-4 text-left align-middle font-medium text-muted-foreground',
                            header.column.getCanSort() && 'cursor-pointer select-none hover:text-foreground'
                          )}
                          style={{ width: header.getSize() }}
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          <div className="flex items-center gap-1">
                            {header.isPlaceholder
                              ? null
                              : flexRender(header.column.columnDef.header, header.getContext())}
                            {header.column.getCanSort() && (
                              <span className="ml-1">
                                {header.column.getIsSorted() === 'asc' ? (
                                  <ChevronUp className="w-3.5 h-3.5" />
                                ) : header.column.getIsSorted() === 'desc' ? (
                                  <ChevronDown className="w-3.5 h-3.5" />
                                ) : (
                                  <GripVertical className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50" />
                                )}
                              </span>
                            )}
                          </div>
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody className="divide-y divide-border/50">
                  <AnimatePresence mode="popLayout">
                    {table.getRowModel().rows.map((row, i) => (
                      <motion.tr
                        key={row.id}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 20 }}
                        transition={{ delay: i * 0.03, duration: 0.3 }}
                        className={cn(
                          'border-b border-border/50 transition-colors hover:bg-muted/30 data-[state=selected]:bg-primary/5',
                          row.getIsSelected() && 'bg-primary/5'
                        )}
                        data-state={row.getIsSelected() ? 'selected' : undefined}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td
                            key={cell.id}
                            className="p-4 align-middle"
                          >
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </motion.tr>
                    ))}
                  </AnimatePresence>
                </tbody>
              </table>
            </div>
          </div>

          {/* Mobile Cards */}
          <div className={cn('md:hidden', !showMobile && 'hidden md:block')} >
            <DataTableMobile
              rows={table.getRowModel().rows}
              cardRenderer={mobileCardRenderer}
              getRowId={(row) => getRowId?.(row.original) || String(row.id)}
              selectedRows={rowSelection}
              onRowSelectionChange={onRowSelectionChange}
              enableRowSelection={enableRowSelection}
            />
          </div>

          <DataTablePagination
            page={page}
            limit={limit}
            totalCount={totalCount}
            pageCount={pageCount}
            onPageChange={onPageChange}
            onLimitChange={onLimitChange}
          />
        </>
      )}
    </div>
  );
}
