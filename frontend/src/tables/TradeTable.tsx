import {
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  filterFn_includesString,
  globalFilteringFeature,
  rowPaginationFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import type { TradeRecord } from "../api/types";
import { day, decimal, percentValue, rupees } from "../lib/format";
import { href } from "../lib/route";

// Client-side sorting, text search and paging over the run's trades (a few hundred rows).
// Features and columns live at module scope so they are stable between renders.
const features = tableFeatures({
  columnFilteringFeature,
  globalFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { includesString: filterFn_includesString },
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric },
  rowPaginationFeature,
  paginatedRowModel: createPaginatedRowModel(),
});

const helper = createColumnHelper<typeof features, TradeRecord>();
const SEARCHABLE = new Set(["trade_id", "events", "expiry_weekday", "lot_size_source"]);

const columns = helper.columns([
  helper.accessor("trade_id", { header: "Trade" }),
  helper.accessor("entry_date", { header: "Entry", cell: (c) => day(c.getValue()) }),
  helper.accessor("expiry", { header: "Expiry", cell: (c) => day(c.getValue()) }),
  helper.accessor("expiry_weekday", { header: "Day" }),
  helper.accessor("strike", { header: "Strike", cell: (c) => c.getValue().toLocaleString("en-IN") }),
  helper.accessor("lot_size", { header: "Lot" }),
  helper.accessor("vix_at_entry", { header: "VIX", cell: (c) => decimal(c.getValue()) }),
  helper.accessor("premium_fill_points", { header: "Premium (pts)", cell: (c) => decimal(c.getValue()) }),
  helper.accessor("nifty_move_pct", { header: "NIFTY move", cell: (c) => percentValue(c.getValue()) }),
  helper.accessor("pnl_points_net", { header: "Net pts", cell: (c) => decimal(c.getValue()) }),
  helper.accessor("pnl_pct_premium_net", { header: "Net % premium", cell: (c) => percentValue(c.getValue()) }),
  helper.accessor("pnl_rs_net", { header: "Net ₹", cell: (c) => rupees(c.getValue()) }),
  helper.accessor("events", { header: "Events", cell: (c) => c.getValue() ?? "" }),
]);

export function TradeTable({
  trades,
  runId,
  studyId,
}: {
  trades: TradeRecord[];
  runId: string;
  studyId?: string;
}) {
  const table = useTable({
    features,
    columns,
    data: trades,
    globalFilterFn: "includesString",
    getColumnCanGlobalFilter: (column) => SEARCHABLE.has(column.id),
    initialState: { pagination: { pageIndex: 0, pageSize: 25 }, sorting: [{ id: "expiry", desc: false }] },
  });
  const filtered = table.getFilteredRowModel().rows.length;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <input
          type="search"
          aria-label="Search trades"
          placeholder="Search trade id, weekday or event (e.g. rbi_policy)"
          className="w-80 rounded border border-slate-300 px-2 py-1"
          value={String(table.state.globalFilter ?? "")}
          onChange={(e) => table.setGlobalFilter(e.target.value)}
        />
        <span className="text-slate-600">
          {filtered} of {trades.length} trades
        </span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm" aria-label="Trades">
          <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <th key={header.id} className="px-2 py-2 text-left">
                      <button
                        type="button"
                        className="flex items-center gap-1 uppercase"
                        onClick={header.column.getToggleSortingHandler()}
                        aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                      >
                        <table.FlexRender header={header} />
                        {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : ""}
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="tabular-nums">
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-t border-slate-100 hover:bg-indigo-50">
                {row.getAllCells().map((cell) => (
                  <td key={cell.id} className="whitespace-nowrap px-2 py-1">
                    {cell.column.id === "trade_id" ? (
                      <a
                        className="font-mono text-xs text-indigo-700 underline"
                        href={href({ page: "trade", runId, tradeId: row.original.trade_id, studyId })}
                      >
                        {row.original.trade_id}
                      </a>
                    ) : (
                      <table.FlexRender cell={cell} />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <button type="button" className="rounded border px-2 py-0.5 disabled:opacity-40" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
          Previous
        </button>
        <span>
          Page {(table.state.pagination?.pageIndex ?? 0) + 1} of {Math.max(table.getPageCount(), 1)}
        </span>
        <button type="button" className="rounded border px-2 py-0.5 disabled:opacity-40" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
          Next
        </button>
      </div>
    </div>
  );
}
