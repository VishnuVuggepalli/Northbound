interface DataTableProps {
  columns: string[];
  rows: string[][];
  /** Optional per-column className for the cell (by column index). */
  cellClass?: (colIndex: number) => string;
}

/** Shared compact data table (monospace rows). Used for MAC tables, protocol
 *  operational gets, and any column/row grid. */
export function DataTable({ columns, rows, cellClass }: DataTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="border-b border-border text-fg-subtle">
            {columns.map((c) => (
              <th key={c} className="py-1.5 pr-4 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="nb-mono">
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border/40">
              {row.map((cell, j) => (
                <td key={j} className={`py-1 pr-4 ${cellClass?.(j) ?? 'text-fg-muted'}`}>
                  {cell || '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
