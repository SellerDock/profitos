import { useEffect, useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronUp, ChevronDown, ChevronRight, ChevronsUpDown, RefreshCw, User, Cpu, AlertTriangle, CheckCircle, Settings, X } from 'lucide-react'
import { accountsApi, stockApi, type StockRow, type StockSettings } from '../api/client'
import { formatNumber } from '../utils/money'

// ── Formatting ────────────────────────────────────────────────────────────────
const f1 = (v: number) => formatNumber(v, 1)

function fDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit', year: '2-digit' })
    + ' ' + d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })
}

// ── Sorting ───────────────────────────────────────────────────────────────────
type SortKey = 'name' | 'quantity' | 'sync_from_allegro' | 'avg_daily' | 'sold_15d' | 'sold_30d' | 'sold_90d' | 'days_left' | 'updated_at'
type SortDir = 'asc' | 'desc'

interface ColDef { key: SortKey; label: string; align: 'left' | 'right' | 'center' }

const COLS: ColDef[] = [
  { key: 'name',       label: 'Nazwa SKU',             align: 'left'   },
  { key: 'quantity',   label: 'Stan',                   align: 'right'  },
  { key: 'sync_from_allegro', label: 'Źródło stanu',    align: 'center' },
  { key: 'avg_daily',  label: 'Śr. sprzedaż/dzień',    align: 'right'  },
  { key: 'sold_15d',   label: 'Sprzedaż 15d',           align: 'right'  },
  { key: 'sold_30d',   label: 'Sprzedaż 30d',           align: 'right'  },
  { key: 'sold_90d',   label: 'Sprzedaż 90d',           align: 'right'  },
  { key: 'days_left',  label: 'Dni do wyczerpania',     align: 'right'  },
  { key: 'updated_at', label: 'Ostatnia aktualizacja',  align: 'center' },
]

function sortRows(rows: StockRow[], key: SortKey, dir: SortDir): StockRow[] {
  return [...rows].sort((a, b) => {
    if (key === 'name') {
      const cmp = a.name.localeCompare(b.name, 'pl')
      return dir === 'asc' ? cmp : -cmp
    }
    let av: number, bv: number
    if (key === 'days_left') {
      av = a.days_left ?? Infinity
      bv = b.days_left ?? Infinity
    } else if (key === 'sync_from_allegro') {
      av = a.sync_from_allegro ? 1 : 0
      bv = b.sync_from_allegro ? 1 : 0
    } else if (key === 'updated_at') {
      av = a.updated_at ? new Date(a.updated_at).getTime() : 0
      bv = b.updated_at ? new Date(b.updated_at).getTime() : 0
    } else {
      av = a[key] as number
      bv = b[key] as number
    }
    return dir === 'asc' ? av - bv : bv - av
  })
}

function SortTh({ col, sortKey, sortDir, onSort }: {
  col: ColDef; sortKey: SortKey; sortDir: SortDir; onSort: (k: SortKey) => void
}) {
  const active = sortKey === col.key
  const Icon = active ? (sortDir === 'asc' ? ChevronUp : ChevronDown) : ChevronsUpDown
  const align = col.align === 'right' ? 'justify-end' : col.align === 'center' ? 'justify-center' : 'justify-start'
  return (
    <th
      onClick={() => onSort(col.key)}
      className={`px-3 py-2 text-xs font-semibold uppercase tracking-wide cursor-pointer select-none whitespace-nowrap
        ${active ? 'text-blue-300' : 'text-slate-400 hover:text-slate-200'}`}
    >
      <div className={`flex items-center gap-1 ${align}`}>
        {col.align === 'right' && <Icon size={12} className="shrink-0" />}
        <span>{col.label}</span>
        {col.align !== 'right' && <Icon size={12} className="shrink-0" />}
      </div>
    </th>
  )
}

// ── Days-left badge ───────────────────────────────────────────────────────────
function formatDaysLeft(days: number): string {
  if (days < 31) return `${days} dni`
  const years = Math.floor(days / 365)
  const months = Math.floor((days % 365) / 30)
  const remDays = days - years * 365 - months * 30
  const parts: string[] = []
  if (years > 0) parts.push(`${years} ${years === 1 ? 'rok' : years < 5 ? 'lata' : 'lat'}`)
  if (months > 0) parts.push(`${months} mies.`)
  if (years === 0 && remDays > 0) parts.push(`${remDays} dni`)
  return parts.join(' ') || `${days} dni`
}

function DaysLeftBadge({ days, critical, warning }: { days: number | null; critical: number; warning: number }) {
  if (days === null) return <span className="text-slate-500 text-sm">—</span>
  const label = formatDaysLeft(days)
  const title = `${days.toLocaleString('pl-PL')} dni do wyczerpania`
  if (days < critical)
    return <span title={title} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-red-900/50 text-red-300 border border-red-700/50"><AlertTriangle size={10} />{label}</span>
  if (days < warning)
    return <span title={title} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-yellow-900/50 text-yellow-300 border border-yellow-700/50">{label}</span>
  return <span title={title} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-900/50 text-emerald-300 border border-emerald-700/50"><CheckCircle size={10} />{label}</span>
}

// ── Settings modal ────────────────────────────────────────────────────────────
function SettingsModal({ current, onSave, onClose }: {
  current: StockSettings
  onSave: (s: StockSettings) => void
  onClose: () => void
}) {
  const [critical, setCritical] = useState(String(current.threshold_critical))
  const [warning, setWarning]   = useState(String(current.threshold_warning))
  const [error, setError]       = useState<string | null>(null)

  function handleSave() {
    const c = parseInt(critical, 10)
    const w = parseInt(warning,  10)
    if (isNaN(c) || isNaN(w) || c <= 0 || w <= 0) {
      setError('Wartości muszą być liczbami całkowitymi > 0.')
      return
    }
    if (c >= w) {
      setError('Próg czerwony musi być mniejszy niż żółty.')
      return
    }
    setError(null)
    onSave({ threshold_critical: c, threshold_warning: w })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-80 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl p-5">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">Ustawienia progów</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Fields */}
        <div className="space-y-3">
          <label className="flex items-center gap-3">
            <span className="w-5 h-5 rounded-full bg-red-500/20 border border-red-500/50 flex items-center justify-center shrink-0">
              <span className="w-2 h-2 rounded-full bg-red-400" />
            </span>
            <span className="text-sm text-slate-300 flex-1">Czerwony poniżej</span>
            <div className="flex items-center gap-1.5">
              <input
                type="number"
                min="1"
                value={critical}
                onChange={e => setCritical(e.target.value)}
                className="w-16 text-right bg-slate-800 border border-slate-600 rounded px-2 py-1 text-white text-sm focus:outline-none focus:border-red-500"
              />
              <span className="text-slate-500 text-xs">dni</span>
            </div>
          </label>

          <label className="flex items-center gap-3">
            <span className="w-5 h-5 rounded-full bg-yellow-500/20 border border-yellow-500/50 flex items-center justify-center shrink-0">
              <span className="w-2 h-2 rounded-full bg-yellow-400" />
            </span>
            <span className="text-sm text-slate-300 flex-1">Żółty poniżej</span>
            <div className="flex items-center gap-1.5">
              <input
                type="number"
                min="1"
                value={warning}
                onChange={e => setWarning(e.target.value)}
                className="w-16 text-right bg-slate-800 border border-slate-600 rounded px-2 py-1 text-white text-sm focus:outline-none focus:border-yellow-500"
              />
              <span className="text-slate-500 text-xs">dni</span>
            </div>
          </label>
        </div>

        {error && <p className="mt-3 text-xs text-red-400">{error}</p>}

        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            Anuluj
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
          >
            Zapisz
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Inline editable quantity cell ─────────────────────────────────────────────
function QuantityCell({ row, onSave }: { row: StockRow; onSave: (skuId: number, qty: number) => void }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue]     = useState(String(row.quantity))
  const inputRef = useRef<HTMLInputElement>(null)

  function startEdit() {
    setValue(String(row.quantity))
    setEditing(true)
    setTimeout(() => inputRef.current?.select(), 0)
  }

  function commit() {
    const n = parseInt(value, 10)
    if (!isNaN(n) && n >= 0 && n !== row.quantity) onSave(row.sku_id, n)
    setEditing(false)
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter') commit()
    if (e.key === 'Escape') setEditing(false)
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="number"
        min="0"
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={handleKey}
        className="w-20 text-right bg-slate-700 border border-blue-500 rounded px-2 py-0.5 text-white text-sm focus:outline-none"
        autoFocus
      />
    )
  }

  return (
    <button onClick={startEdit} title="Kliknij aby edytować" className="flex items-center justify-end gap-1.5 w-full group">
      <span className="text-sm font-medium tabular-nums text-white group-hover:text-blue-300 transition-colors">
        {row.quantity.toLocaleString('pl-PL')}
      </span>
      {row.updated_by === 'manual'
        ? <User size={10} className="text-slate-500 group-hover:text-blue-400 shrink-0" />
        : <Cpu  size={10} className="text-slate-600 shrink-0" />}
    </button>
  )
}

function AllegroStockToggle({ row, onChange }: { row: StockRow; onChange: (syncFromAllegro: boolean) => void }) {
  const disabled = !row.sync_from_allegro

  return (
    <label className="inline-flex items-center justify-center gap-2 text-xs text-slate-400 hover:text-slate-200 cursor-pointer">
      <input
        type="checkbox"
        checked={disabled}
        onChange={e => onChange(!e.target.checked)}
        className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
      />
      <span className="whitespace-nowrap">Nie pobieraj z Allegro</span>
    </label>
  )
}

// ── Mobile card view ──────────────────────────────────────────────────────────
function StockCard({ row, crit, warn, onUpdate }: {
  row: StockRow
  crit: number
  warn: number
  onUpdate: (args: { skuId: number; quantity: number; syncFromAllegro?: boolean }) => void
}) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
      <div className="min-w-0">
        <div className="font-medium text-slate-200 leading-tight">{row.name}</div>
        <div className="font-mono text-xs text-slate-500 mt-0.5 truncate">{row.sku_key}</div>
      </div>

      <div className="mt-3 flex items-end justify-between gap-3 border-t border-slate-800 pt-3">
        <div className="min-w-0 [&_button]:justify-start">
          <p className="text-[11px] text-slate-500">Stan</p>
          <QuantityCell
            row={row}
            onSave={(skuId, quantity) => onUpdate({ skuId, quantity, syncFromAllegro: row.sync_from_allegro })}
          />
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[11px] text-slate-500 mb-1">Źródło stanu</p>
          <AllegroStockToggle
            row={row}
            onChange={syncFromAllegro => onUpdate({ skuId: row.sku_id, quantity: row.quantity, syncFromAllegro })}
          />
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
        <div>
          <p className="text-[11px] text-slate-500">Śr. sprzedaż/dzień</p>
          <p className="text-sm font-medium text-slate-300 tabular-nums">
            {row.avg_daily > 0 ? f1(row.avg_daily) : <span className="text-slate-600">—</span>}
          </p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500">Dni do wyczerpania</p>
          <div className="mt-0.5">
            <DaysLeftBadge days={row.days_left} critical={crit} warning={warn} />
          </div>
        </div>
      </div>

      <details className="group mt-3">
        <summary className="flex cursor-pointer list-none items-center justify-between rounded-md border border-slate-800 px-3 py-2 text-xs font-medium text-slate-300">
          <span>Szczegóły</span>
          <ChevronRight size={14} className="text-slate-500 transition-transform group-open:rotate-90" />
        </summary>
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-3 gap-3 text-[11px]">
            <div>
              <p className="text-slate-500">Sprzedaż 15d</p>
              <p className="text-slate-300 tabular-nums">
                {row.sold_15d > 0 ? row.sold_15d : <span className="text-slate-600">0</span>}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Sprzedaż 30d</p>
              <p className="text-slate-300 tabular-nums">
                {row.sold_30d > 0 ? row.sold_30d : <span className="text-slate-600">0</span>}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Sprzedaż 90d</p>
              <p className="text-slate-300 tabular-nums">
                {row.sold_90d > 0 ? row.sold_90d : <span className="text-slate-600">0</span>}
              </p>
            </div>
          </div>
          <div className="text-[11px]">
            <p className="text-slate-500">Ostatnia aktualizacja</p>
            <p className="text-slate-400">{fDate(row.updated_at)}</p>
          </div>
        </div>
      </details>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Stock() {
  const qc = useQueryClient()
  const [sortKey, setSortKey]       = useState<SortKey>('days_left')
  const [sortDir, setSortDir]       = useState<SortDir>('asc')
  const [search, setSearch]         = useState('')
  const [page, setPage]             = useState(1)
  const [pageSize, setPageSize]     = useState(50)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [selectedAccountId, setSelectedAccountId] = useState<number | undefined>(undefined)

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['stock', selectedAccountId ?? 'all'],
    queryFn: () => stockApi.list(selectedAccountId),
    refetchInterval: 60_000,
  })
  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: accountsApi.list })
  const connectedAccounts = accounts.filter(a => a.is_connected)
  const selectedAccountName = connectedAccounts.find(a => a.id === selectedAccountId)?.name

  const { data: settings = { threshold_critical: 14, threshold_warning: 30 } } = useQuery({
    queryKey: ['stock-settings'],
    queryFn: stockApi.getSettings,
    staleTime: Infinity,
  })

  const updateMutation = useMutation({
    mutationFn: ({ skuId, quantity, syncFromAllegro }: { skuId: number; quantity: number; syncFromAllegro?: boolean }) =>
      stockApi.update(skuId, { quantity, sync_from_allegro: syncFromAllegro }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['stock'] }),
  })

  const autoImportMutation = useMutation({
    mutationFn: stockApi.autoImport,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['stock'] })
      alert(`Auto-import zakończony. Pobrano ${data.imported} ofert z ${data.accounts} kont Allegro. Dodano ${data.added} brakujących SKU.`)
    },
  })

  const settingsMutation = useMutation({
    mutationFn: stockApi.updateSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stock-settings'] })
      setSettingsOpen(false)
    },
  })

  function handleSort(key: SortKey) {
    if (key === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  const { threshold_critical: crit, threshold_warning: warn } = settings

  const filtered = rows.filter(r =>
    !search || r.name.toLowerCase().includes(search.toLowerCase()) || r.sku_key.toLowerCase().includes(search.toLowerCase())
  )
  const sorted = sortRows(filtered, sortKey, sortDir)
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const safePage = Math.min(page, totalPages)
  const pagedRows = sorted.slice((safePage - 1) * pageSize, safePage * pageSize)

  useEffect(() => {
    setPage(1)
  }, [search, pageSize, selectedAccountId])

  useEffect(() => {
    if (selectedAccountId && !connectedAccounts.some(a => a.id === selectedAccountId)) {
      setSelectedAccountId(undefined)
    }
  }, [connectedAccounts, selectedAccountId])

  const criticalCount = rows.filter(r => r.days_left !== null && r.days_left < crit).length
  const warningCount  = rows.filter(r => r.days_left !== null && r.days_left >= crit && r.days_left < warn).length

  return (
    <div className="space-y-4">
      {/* Settings modal */}
      {settingsOpen && (
        <SettingsModal
          current={settings}
          onSave={s => settingsMutation.mutate(s)}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Magazyn</h2>
          <p className="text-slate-400 text-sm mt-0.5">
            {rows.length} SKU
            {criticalCount > 0 && <span className="ml-2 text-red-400">· {criticalCount} krytycznych (&lt;{crit}d)</span>}
            {warningCount  > 0 && <span className="ml-2 text-yellow-400">· {warningCount} ostrzeżeń (&lt;{warn}d)</span>}
          </p>
          {selectedAccountName && <p className="mt-0.5 text-sm text-slate-500">Widok konta: {selectedAccountName}</p>}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSettingsOpen(true)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-400 hover:text-slate-200 text-sm transition-colors"
            title="Ustawienia progów"
          >
            <Settings size={14} />
            <span className="hidden sm:inline">Ustawienia</span>
          </button>
          <button
            onClick={() => autoImportMutation.mutate()}
            disabled={autoImportMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium transition-colors disabled:opacity-50"
          >
            <RefreshCw size={14} className={autoImportMutation.isPending ? 'animate-spin' : ''} />
            Auto-import
          </button>
        </div>
      </div>

      {connectedAccounts.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setSelectedAccountId(undefined)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              selectedAccountId === undefined
                ? 'border-blue-400 bg-blue-500/15 text-blue-100'
                : 'border-slate-700 bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            Wszystkie
          </button>
          {connectedAccounts.map(account => (
            <button
              key={account.id}
              type="button"
              onClick={() => setSelectedAccountId(account.id)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                selectedAccountId === account.id
                  ? 'border-blue-400 bg-blue-500/15 text-blue-100'
                  : 'border-slate-700 bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {account.name}
            </button>
          ))}
        </div>
      )}

      {/* Search + pagination size */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <input
          type="text"
          placeholder="Szukaj SKU lub nazwy…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-full max-w-sm bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <span>Na stronę</span>
          <select
            value={pageSize}
            onChange={e => setPageSize(parseInt(e.target.value, 10))}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
          >
            <option value={20}>20</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
      </div>

      {/* Table (desktop) */}
      <div className="hidden lg:block rounded-xl border border-slate-700/60 overflow-x-auto">
        <table className="w-full min-w-[62rem] text-sm">
          <thead className="bg-slate-800/80 border-b border-slate-700/60">
            <tr>
              {COLS.map(col => (
                <SortTh key={col.key} col={col} sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              [...Array(8)].map((_, i) => (
                <tr key={i} className="border-b border-slate-800 animate-pulse">
                  {COLS.map(c => (
                    <td key={c.key} className="px-3 py-3">
                      <div className="h-3 bg-slate-700 rounded w-3/4" />
                    </td>
                  ))}
                </tr>
              ))
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={COLS.length} className="px-3 py-10 text-center text-slate-500">
                  {search ? 'Brak wyników dla podanej frazy.' : selectedAccountId ? 'Brak SKU dla tego konta.' : 'Brak SKU. Kliknij Auto-import aby zainicjować stany.'}
                </td>
              </tr>
            ) : (
              pagedRows.map(row => (
                <tr key={row.sku_id} className="border-b border-slate-800/60 hover:bg-slate-800/40 transition-colors">
                  <td className="px-3 py-2.5">
                    <div className="font-medium text-slate-200 leading-tight">{row.name}</div>
                    <div className="text-xs text-slate-500 mt-0.5">{row.sku_key}</div>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <QuantityCell
                      row={row}
                      onSave={(skuId, quantity) => updateMutation.mutate({
                        skuId,
                        quantity,
                        syncFromAllegro: row.sync_from_allegro,
                      })}
                    />
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <AllegroStockToggle
                      row={row}
                      onChange={syncFromAllegro => updateMutation.mutate({
                        skuId: row.sku_id,
                        quantity: row.quantity,
                        syncFromAllegro,
                      })}
                    />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-300">
                    {row.avg_daily > 0 ? f1(row.avg_daily) : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-300">
                    {row.sold_15d > 0 ? row.sold_15d : <span className="text-slate-600">0</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-300">
                    {row.sold_30d > 0 ? row.sold_30d : <span className="text-slate-600">0</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-300">
                    {row.sold_90d > 0 ? row.sold_90d : <span className="text-slate-600">0</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <DaysLeftBadge days={row.days_left} critical={crit} warning={warn} />
                  </td>
                  <td className="px-3 py-2.5 text-center text-xs text-slate-500">
                    {fDate(row.updated_at)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Cards (mobile) */}
      <div className="space-y-3 lg:hidden">
        {isLoading ? (
          [...Array(4)].map((_, i) => (
            <div key={i} className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4 animate-pulse space-y-3">
              <div className="h-3 bg-slate-700 rounded w-2/5" />
              <div className="h-3 bg-slate-700 rounded w-1/3" />
              <div className="h-7 bg-slate-700 rounded w-1/2" />
            </div>
          ))
        ) : sorted.length === 0 ? (
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-10 text-center text-slate-500">
            {search ? 'Brak wyników dla podanej frazy.' : selectedAccountId ? 'Brak SKU dla tego konta.' : 'Brak SKU. Kliknij Auto-import aby zainicjować stany.'}
          </div>
        ) : (
          pagedRows.map(row => (
            <StockCard
              key={row.sku_id}
              row={row}
              crit={crit}
              warn={warn}
              onUpdate={args => updateMutation.mutate(args)}
            />
          ))
        )}
      </div>

      {sorted.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500">
          <span>
            Pokazuję {(safePage - 1) * pageSize + 1}-{Math.min(safePage * pageSize, sorted.length)} z {sorted.length}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={safePage <= 1}
              className="rounded border border-slate-700 px-3 py-1.5 disabled:opacity-40"
            >
              Poprzednia
            </button>
            <span className="tabular-nums">{safePage} / {totalPages}</span>
            <button
              type="button"
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={safePage >= totalPages}
              className="rounded border border-slate-700 px-3 py-1.5 disabled:opacity-40"
            >
              Następna
            </button>
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1"><User size={10} /> ręczny wpis</span>
        <span className="flex items-center gap-1"><Cpu size={10} /> auto-import</span>
        <span className="text-slate-600">Kliknij w Stan aby edytować · Enter zapisuje · Esc anuluje</span>
        <span className="ml-auto flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-full bg-red-400" />
            &lt;{crit}d
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-full bg-yellow-400" />
            &lt;{warn}d
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-400" />
            ≥{warn}d
          </span>
        </span>
      </div>
    </div>
  )
}
