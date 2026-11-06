import { useRef, useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles, Loader2, ChevronDown, ChevronRight, Plus, Trash2, CheckCircle2, Upload, X, FileSpreadsheet, ChevronsUpDown, Lock } from 'lucide-react'
import { productsApi, accountsApi, type EncryptedValue, type ProductManageRow, type SkuPatch } from '../api/client'
import { useFinancialVault } from '../context/FinancialVaultContext'
import { useFinancialDisplayMode } from '../context/FinancialDisplayModeContext'
import { decryptCost, encryptCost, skuCostAad, skuCostHistoryAad, decryptText } from '../crypto/financialVault'
import { yieldToBrowser } from '../utils/browserYield'
import {
  guessCostImportMapping,
  parseCsvTable,
  parseMappedCostImport,
  type CostImportMapping,
  type CsvTable,
  type ParsedCostImportRow,
} from '../utils/costImportCsv'
import { formatNumber } from '../utils/money'

// ── Sorting ───────────────────────────────────────────────────────────────────
type PSortKey = 'sku_key' | 'name' | 'cost_per_unit' | 'vat_rate' | 'target_margin_pct' | 'history'
type PSortDir = 'asc' | 'desc'
const PAGE_SIZE_OPTIONS = [20, 50, 100] as const

function sortManageRows(rows: ProductManageRow[], key: PSortKey, dir: PSortDir, costs: Record<number, number | null>, showNet: boolean) {
  return [...rows].sort((a, b) => {
    let av: string | number, bv: string | number
    if (key === 'history') { av = a.cost_history.length; bv = b.cost_history.length }
    else if (key === 'sku_key' || key === 'name') {
      const cmp = String(a[key]).localeCompare(String(b[key]), 'pl')
      return dir === 'asc' ? cmp : -cmp
    }
    else if (key === 'cost_per_unit') {
      av = visibleCost(costs[a.id], a.vat_rate, showNet) ?? -1
      bv = visibleCost(costs[b.id], b.vat_rate, showNet) ?? -1
    }
    else { av = Number(a[key]); bv = Number(b[key]) }
    return dir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number)
  })
}

type PColDef = { label: string; key: PSortKey; align: 'left' | 'right' }
const PCOLS: PColDef[] = [
  { label: 'SKU',              key: 'sku_key',           align: 'left'  },
  { label: 'Nazwa',            key: 'name',              align: 'left'  },
  { label: 'Koszt zakupu',     key: 'cost_per_unit',     align: 'right' },
  { label: 'VAT',              key: 'vat_rate',          align: 'right' },
  { label: 'Cel marży',        key: 'target_margin_pct', align: 'right' },
  { label: 'Wpisów historii',  key: 'history',           align: 'right' },
]

function PSortTh({ col, sortKey, sortDir, onSort }: {
  col: PColDef; sortKey: PSortKey; sortDir: PSortDir; onSort: (k: PSortKey) => void
}) {
  const active = sortKey === col.key
  return (
    <th
      onClick={() => onSort(col.key)}
      className={`px-3 py-3 font-medium whitespace-nowrap cursor-pointer select-none
        ${col.align === 'left' ? 'text-left' : 'text-right'}
        ${active ? 'text-white' : 'text-slate-400 hover:text-white'}`}
    >
      <span className={`inline-flex items-center gap-0.5 ${col.align === 'right' ? 'flex-row-reverse' : ''}`}>
        {col.label}
        {active
          ? (sortDir === 'asc' ? <ChevronDown size={10} /> : <ChevronDown size={10} className="rotate-180" />)
          : <ChevronsUpDown size={10} className="text-slate-600" />}
      </span>
    </th>
  )
}

// ── Formatting ────────────────────────────────────────────────────────────────
const f = (v: string | number, dec = 2) => formatNumber(Number(v), dec)

// Local VAT helpers intentionally differ from utils/money: normalizeVatRate also
// accepts fractional rates (0.23 → 23) and netCostFromVisible returns a string.
function normalizeVatRate(value: string | number): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return n > 0 && n < 1 ? n * 100 : n
}

function vatMultiplier(vatRate: string | number): number {
  return 1 + normalizeVatRate(vatRate) / 100
}

function visibleCost(netCost: number | null | undefined, vatRate: string | number, showNet: boolean): number | null {
  if (netCost == null || !Number.isFinite(netCost)) return null
  return showNet ? netCost : netCost * vatMultiplier(vatRate)
}

function netCostFromVisible(value: string, vatRate: string | number, showNet: boolean): string {
  const parsed = Number(value.replace(',', '.'))
  if (!Number.isFinite(parsed)) return value
  const net = showNet ? parsed : parsed / vatMultiplier(vatRate)
  return net.toFixed(2)
}

function normalizePercentDraft(value: string, min: number, max: number): string | null {
  const n = Number(value.replace(',', '.'))
  if (!Number.isFinite(n) || n < min || n > max) return null
  return String(n)
}

// ── Inline editable cell ──────────────────────────────────────────────────────
function InlineCell({ value, onSave, saving = false, suffix = '', min, max }: {
  value: string; onSave: (v: string) => void; saving?: boolean; suffix?: string; min?: number; max?: number
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => setDraft(value), [value])
  useEffect(() => { if (editing) ref.current?.select() }, [editing])
  const commit = () => {
    if (min !== undefined && max !== undefined) {
      const normalized = normalizePercentDraft(draft, min, max)
      if (normalized === null) {
        setDraft(value)
        setEditing(false)
        return
      }
      setEditing(false)
      if (normalized !== value) onSave(normalized)
      return
    }
    setEditing(false)
    if (draft !== value) onSave(draft)
  }
  if (saving) return <span className="text-slate-500 flex items-center gap-1"><Loader2 size={10} className="animate-spin" />{f(value)}{suffix}</span>
  if (editing) return <input ref={ref} type="number" min={min} max={max} step="0.01" className="w-24 bg-slate-700 border border-indigo-500 rounded px-1.5 py-0.5 text-white text-xs focus:outline-none"
    value={draft} onChange={e => setDraft(e.target.value)}
    onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }} />
  return <span className="cursor-pointer hover:text-indigo-400 hover:underline decoration-dotted transition-colors"
    title="Kliknij aby edytować" onClick={() => setEditing(true)}>{f(value)}{suffix}</span>
}

// ── Cost history panel ────────────────────────────────────────────────────────
function CostHistoryPanel({ sku, onDelete, onAdd, adding }: {
  sku: ProductManageRow
  onDelete: (histId: number, currentEncryptedCost?: EncryptedValue) => void
  onAdd: (cost: string, validFrom: string, note?: string) => void
  adding: boolean
}) {
  const vault = useFinancialVault()
  const financialDisplay = useFinancialDisplayMode()
  const [historyCosts, setHistoryCosts] = useState<Record<number, number | null>>({})
  const [showForm, setShowForm] = useState(false)
  const [cost, setCost] = useState('')
  const [validFrom, setValidFrom] = useState(new Date().toISOString().slice(0, 10))
  const [note, setNote] = useState('')
  const [deletingHistId, setDeletingHistId] = useState<number | null>(null)

  const handleDelete = async (histId: number) => {
    if (!vault.key || !vault.status) {
      window.alert('Odblokuj sejf finansowy, aby usunąć wpis historii kosztu.')
      return
    }
    const message = sku.cost_history.length === 1
      ? 'To jedyny wpis historii kosztu dla tego SKU. Bieżący koszt zostanie zachowany, ale ten wpis historii zniknie bezpowrotnie. Usunąć?'
      : 'Usunąć ten wpis historii kosztu? Tej operacji nie można cofnąć.'
    if (!window.confirm(message)) return

    const remaining = sku.cost_history
      .filter(h => h.id !== histId && h.encrypted_cost)
      .sort((a, b) => (b.valid_from || '').localeCompare(a.valid_from || ''))
    if (remaining.length > 0) {
      try {
        setDeletingHistId(histId)
        const latest = remaining[0]
        const plaintext = await decryptText(vault.key, latest.encrypted_cost!, latest.encrypted_cost!.aad_context)
        const keyVersion = vault.status.key_version ?? 1
        const currentEncryptedCost = await encryptCost(vault.key, plaintext, skuCostAad(sku.id, keyVersion), keyVersion)
        onDelete(histId, currentEncryptedCost)
      } catch {
        window.alert('Nie udało się odszyfrować wpisu historii. Sprawdź stan sejfu finansowego i spróbuj ponownie.')
      } finally {
        setDeletingHistId(null)
      }
    } else {
      onDelete(histId)
    }
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!cost || !validFrom) return
    onAdd(netCostFromVisible(cost, sku.vat_rate, financialDisplay.showNet), validFrom, note || undefined)
    setCost(''); setNote(''); setShowForm(false)
  }

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!vault.key) {
        setHistoryCosts({})
        return
      }
      const entries: [number, number | null][] = []
      for (let i = 0; i < sku.cost_history.length; i += 1) {
        if (cancelled) return
        const h = sku.cost_history[i]
        entries.push([h.id, await decryptCost(vault.key!, h.encrypted_cost)])
        if ((i + 1) % 5 === 0) await yieldToBrowser()
      }
      if (!cancelled) setHistoryCosts(Object.fromEntries(entries))
    }
    run().catch(() => setHistoryCosts({}))
    return () => { cancelled = true }
  }, [sku.cost_history, vault.key])

  return (
    <div className="mt-2 bg-slate-900/70 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs text-slate-400 font-medium">Historia kosztów zakupu</p>
        <button onClick={() => setShowForm(s => !s)}
          className="flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
          <Plus size={11} />Dodaj
        </button>
      </div>

      {showForm && (
        <form onSubmit={submit} className="flex items-end gap-2 mb-3">
          <div>
            <label className="text-slate-500 text-xs">Koszt ({financialDisplay.showNet ? 'netto' : 'brutto'})</label>
            <input className="block w-24 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-white text-xs focus:outline-none focus:border-indigo-500"
              value={cost} onChange={e => setCost(e.target.value)} placeholder="0.00" required />
          </div>
          <div>
            <label className="text-slate-500 text-xs">Obowiązuje od</label>
            <input type="date" className="block bg-slate-800 border border-slate-600 rounded px-2 py-1 text-white text-xs focus:outline-none focus:border-indigo-500"
              value={validFrom} onChange={e => setValidFrom(e.target.value)} required />
          </div>
          <div className="flex-1">
            <label className="text-slate-500 text-xs">Notatka</label>
            <input className="block w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-white text-xs focus:outline-none focus:border-indigo-500"
              value={note} onChange={e => setNote(e.target.value)} placeholder="opcjonalna" />
          </div>
          <button type="submit" disabled={adding}
            className="flex items-center gap-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs rounded px-3 py-1.5">
            {adding ? <Loader2 size={10} className="animate-spin" /> : <CheckCircle2 size={10} />}Zapisz
          </button>
        </form>
      )}

      {!vault.unlocked ? (
        <p className="flex items-center gap-1 text-slate-500 text-xs"><Lock size={11} />Odblokuj sejf finansowy, aby zobaczyć i dodać historię kosztów.</p>
      ) : sku.cost_history.length === 0 ? (
        <p className="text-slate-600 text-xs">Brak historii zaszyfrowanych kosztów</p>
      ) : (
        <div className="space-y-1">
          {sku.cost_history.map(h => (
            <div key={h.id} className="flex items-center justify-between text-xs">
              <span className="text-slate-300 font-mono w-20">
                {historyCosts[h.id] != null ? `${f(visibleCost(historyCosts[h.id], sku.vat_rate, financialDisplay.showNet) ?? 0)} zł` : '—'}
              </span>
              <span className="text-slate-500">
                {h.valid_from} → {h.valid_to ?? '∞'}
              </span>
              {h.note && <span className="text-slate-600 italic flex-1 mx-3 truncate">{h.note}</span>}
              <button
                onClick={() => handleDelete(h.id)}
                disabled={deletingHistId === h.id}
                className="text-slate-600 hover:text-red-400 disabled:opacity-50 transition-colors ml-2"
              >
                {deletingHistId === h.id ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Encrypted CSV Import Modal ────────────────────────────────────────────────
type CostImportResult = {
  updated: number
  not_found: string[]
  warnings: string[]
}

type PreparedEncryptedRow = {
  row: ParsedCostImportRow
  product: ProductManageRow
  encryptedCurrent: EncryptedValue
  encryptedHistory: EncryptedValue
  validFrom: string
  validTo?: string
}

const OPEN_ENDED_HISTORY_START = '1900-01-01'

function normalizeSku(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ')
}

function digitsOnly(value: string): string {
  return value.replace(/\D/g, '')
}

function productLookupKeys(product: ProductManageRow): string[] {
  return [
    product.sku_key,
    product.name,
    ...(product.offer_ids ?? []),
    ...(product.eans ?? []),
  ].map(normalizeSku).filter(Boolean)
}

function findProductForImport(rowSku: string, byKey: Map<string, ProductManageRow>, products: ProductManageRow[]): ProductManageRow | undefined {
  const normalized = normalizeSku(rowSku)
  const exact = byKey.get(normalized)
  if (exact) return exact

  const rowDigits = digitsOnly(rowSku)
  if (rowDigits.length < 8) return undefined
  const candidates = products.filter(product =>
    (product.offer_ids ?? []).some(offerId => {
      const offerDigits = digitsOnly(offerId)
      return offerDigits.length >= 8 && rowDigits.includes(offerDigits)
    })
    || (product.eans ?? []).some(ean => digitsOnly(ean) === rowDigits),
  )
  return candidates.length === 1 ? candidates[0] : undefined
}

function ImportModal({ products, onClose, onSuccess }: {
  products: ProductManageRow[]
  onClose: () => void
  onSuccess: () => void
}) {
  const vault = useFinancialVault()
  const [fileName, setFileName] = useState('')
  const [table, setTable] = useState<CsvTable | null>(null)
  const [mapping, setMapping] = useState<CostImportMapping>({ sku: '', cost: '', vat: '', validFrom: '', validTo: '' })
  const [parsedRows, setParsedRows] = useState<ParsedCostImportRow[]>([])
  const [parseWarnings, setParseWarnings] = useState<string[]>([])
  const [parseErrors, setParseErrors] = useState<string[]>([])
  const [preparedRows, setPreparedRows] = useState<PreparedEncryptedRow[]>([])
  const [notFound, setNotFound] = useState<string[]>([])
  const [result, setResult] = useState<CostImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const primaryButtonClass = 'inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold shadow-sm transition enabled:bg-ink-950 enabled:text-white enabled:hover:bg-ink-800 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500 disabled:shadow-none'

  useEffect(() => {
    if (!table) return
    const parsed = parseMappedCostImport(table, mapping)
    setParsedRows(parsed.rows)
    setParseWarnings(parsed.warnings)
    setParseErrors(parsed.errors)
    setPreparedRows([])
    setNotFound([])
  }, [mapping, table])

  async function handleFileSelected(selected: File | null) {
    setError(null)
    setResult(null)
    setProgress(null)
    setPreparedRows([])
    setParsedRows([])
    setParseWarnings([])
    setParseErrors([])
    setNotFound([])
    setTable(null)
    setFileName(selected?.name ?? '')
    if (!selected) return
    if (!selected.name.toLowerCase().endsWith('.csv')) {
      setError('Na tym etapie przyjmujemy CSV. Zapisz XLSX jako CSV, żeby plik był parsowany i szyfrowany wyłącznie w przeglądarce.')
      return
    }
    try {
      const text = await selected.text()
      const nextTable = parseCsvTable(text)
      const nextMapping = guessCostImportMapping(nextTable.headers)
      setTable(nextTable)
      setMapping(nextMapping)
      const parsed = parseMappedCostImport(nextTable, nextMapping)
      setParsedRows(parsed.rows)
      setParseWarnings(parsed.warnings)
      setParseErrors(parsed.errors)
    } catch (err) {
      setError(err instanceof Error ? `Nie udało się odczytać pliku: ${err.message}` : 'Nie udało się odczytać pliku.')
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function prepareEncryptedRows(rows: ParsedCostImportRow[]): Promise<void> {
    if (!vault.key) throw new Error('Odblokuj sejf finansowy przed importem kosztów.')
    if (!vault.status?.configured) throw new Error('Sejf finansowy nie jest skonfigurowany.')

    const keyVersion = vault.status.key_version ?? 1
    const today = new Date().toISOString().slice(0, 10)
    const bySku = new Map<string, ProductManageRow>()
    products.forEach(product => {
      productLookupKeys(product).forEach(key => {
        if (!bySku.has(key)) bySku.set(key, product)
      })
    })
    const notFound = new Set<string>()
    const warnings: string[] = []
    const matched = rows
      .map(row => ({ row, product: findProductForImport(row.sku, bySku, products) }))
      .filter(({ row, product }) => {
        if (!product) {
          notFound.add(row.sku)
          return false
        }
        return true
      }) as Array<{ row: ParsedCostImportRow; product: ProductManageRow }>

    matched.sort((a, b) => {
      const skuCmp = a.product.id - b.product.id
      if (skuCmp !== 0) return skuCmp
      return String(a.row.validFrom ?? '9999-12-31').localeCompare(String(b.row.validFrom ?? '9999-12-31'))
    })

    const prepared: PreparedEncryptedRow[] = []
    for (let i = 0; i < matched.length; i += 1) {
      const { row, product } = matched[i]
      const validFrom = row.validFrom || (row.validTo ? OPEN_ENDED_HISTORY_START : today)
      setProgress(`Szyfrowanie podglądu ${i + 1}/${matched.length}: ${product.sku_key}`)
      const encryptedCurrent = await encryptCost(vault.key, row.cost, skuCostAad(product.id, keyVersion), keyVersion)
      const encryptedHistory = await encryptCost(
        vault.key,
        row.cost,
        skuCostHistoryAad(product.id, validFrom, keyVersion),
        keyVersion,
      )
      prepared.push({ row, product, encryptedCurrent, encryptedHistory, validFrom, validTo: row.validTo })
      if ((i + 1) % 10 === 0) await yieldToBrowser()
    }

    setPreparedRows(prepared)
    setNotFound([...notFound])
    setProgress(null)
  }

  async function importPreparedRows(rows: PreparedEncryptedRow[]): Promise<CostImportResult> {
    let updated = 0
    for (let i = 0; i < rows.length; i += 1) {
      const { row, product, encryptedCurrent, encryptedHistory, validFrom } = rows[i]
      setProgress(`Zapisywanie ${i + 1}/${rows.length}: ${product.sku_key}`)
      if (row.validFrom || row.validTo) {
        await productsApi.addCostHistory(product.id, {
          encrypted_cost: encryptedHistory,
          current_encrypted_cost: encryptedCurrent,
          valid_from: validFrom,
          ...(row.validTo ? { valid_to: row.validTo } : {}),
          note: `Import CSV ${fileName}, wiersz ${row.sourceRow}`,
        })
      } else {
        await productsApi.patch(product.id, {
          encrypted_cost: encryptedCurrent,
          history_encrypted_cost: encryptedHistory,
          ...(row.vat ? { vat_rate: row.vat } : {}),
        })
      }

      if ((row.validFrom || row.validTo) && row.vat) {
        await productsApi.patch(product.id, { vat_rate: row.vat })
      }
      updated += 1
      if ((i + 1) % 10 === 0) await yieldToBrowser()
    }

    return { updated, not_found: notFound, warnings: parseWarnings }
  }

  const handlePrepare = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!parsedRows.length || parseErrors.length) return
    setError(null)
    setResult(null)
    setProgress(null)
    try {
      await prepareEncryptedRows(parsedRows)
    } catch (err) {
      setProgress(null)
      setError(err instanceof Error ? err.message : 'Błąd szyfrowania')
    }
  }

  const handleImport = async () => {
    if (!preparedRows.length) return
    setError(null)
    setResult(null)
    try {
      const data = await importPreparedRows(preparedRows)
      setResult(data)
      setProgress(null)
      onSuccess()
    } catch (err) {
      setProgress(null)
      setError(err instanceof Error ? err.message : 'Błąd importu')
    }
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 p-4 backdrop-blur-sm">
      <div className="mx-auto my-6 w-full max-w-lg">
        <div className="apos-panel p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700">
              <FileSpreadsheet size={18} strokeWidth={2.4} />
            </span>
            <h3 className="text-slate-950 font-semibold">Szyfrowany import kosztów CSV</h3>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X size={16} /></button>
        </div>

        <p className="text-slate-600 text-xs leading-5 mb-4">
          Plik powinien zawierać kolumny: <span className="font-mono text-slate-300">sku</span>,{' '}
          <span className="font-mono text-slate-300">cena zakupu</span>,{' '}
          <span className="font-mono text-slate-300">vat</span>,{' '}
          <span className="font-mono text-slate-300">start ceny zakupu</span>,{' '}
          <span className="font-mono text-slate-300">koniec ceny zakupu</span>.
          Wiersz bez dat = aktualny koszt. Po wyborze pliku zobaczysz kolumny, wybierzesz mapowanie,
          a przed zapisem pokażemy zaszyfrowane payloady.
        </p>
        <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
          <p className="font-medium">Najprostszy układ pliku</p>
          <p>
            Koszty wpisuj netto. VAT i daty możesz zostawić puste, jeśli cena obowiązuje od teraz.
          </p>
          <a
            href="/demo/profitos-koszty-demo.csv"
            download
            className="mt-2 inline-flex rounded border border-blue-300 bg-white px-2 py-1 font-medium text-blue-800 hover:bg-blue-100"
          >
            Pobierz przykładowy CSV
          </a>
        </div>

        {!vault.unlocked && (
          <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Odblokuj sejf finansowy w panelu bocznym, żeby import mógł zaszyfrować koszty.
          </p>
        )}

        {!result ? (
          <form onSubmit={handlePrepare} className="space-y-4">
            <div
              className="cursor-pointer rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 p-6 text-center transition-colors hover:border-finance-blue"
              onClick={() => fileRef.current?.click()}
            >
              <input ref={fileRef} type="file" accept=".csv,.xlsx" className="hidden"
                onChange={e => void handleFileSelected(e.target.files?.[0] ?? null)} />
              {fileName ? (
                <div className="flex items-center justify-center gap-3 text-emerald-800">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md border border-emerald-200 bg-white text-emerald-700 shadow-sm">
                    <FileSpreadsheet size={20} strokeWidth={2.4} />
                  </span>
                  <span className="text-sm font-medium">{fileName}</span>
                </div>
              ) : (
                <div className="text-slate-500">
                  <Upload size={24} className="mx-auto mb-2" />
                  <p className="text-sm">Kliknij aby wybrać plik .csv</p>
                </div>
              )}
            </div>

            {table && (
              <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mapowanie kolumn</p>
                  <p className="text-xs text-slate-500">
                    {table.rows.length} wierszy danych
                    {table.skippedRows.length > 0 ? `, pominięto ${table.skippedRows.length} przed nagłówkiem` : ''}
                  </p>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {[
                    ['sku', 'SKU *'],
                    ['cost', 'Cena zakupu *'],
                    ['vat', 'VAT'],
                    ['validFrom', 'Start ceny'],
                    ['validTo', 'Koniec ceny'],
                  ].map(([key, label]) => (
                    <label key={key} className="text-xs text-slate-600">
                      <span className="mb-1 block font-medium">{label}</span>
                      <select
                        value={mapping[key as keyof CostImportMapping]}
                        onChange={e => setMapping(prev => ({
                          ...prev,
                          [key]: e.target.value === '' ? '' : Number(e.target.value),
                        }))}
                        className="apos-control w-full py-1.5 text-xs"
                      >
                        <option value="">Nie importuj</option>
                        {table.headers.map((header, idx) => (
                          <option key={`${header}-${idx}`} value={idx}>{header || `Kolumna ${idx + 1}`}</option>
                        ))}
                      </select>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {table && (
              <div className="max-h-44 overflow-auto rounded-lg border border-slate-200">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-left text-slate-500">
                    <tr>{table.headers.map((header, idx) => <th key={`${header}-${idx}`} className="px-2 py-1.5 font-medium">{header || `Kolumna ${idx + 1}`}</th>)}</tr>
                  </thead>
                  <tbody>
                    {table.rows.slice(0, 5).map((row, idx) => (
                      <tr key={idx} className="border-t border-slate-100">
                        {table.headers.map((_, cellIdx) => <td key={cellIdx} className="max-w-40 truncate px-2 py-1.5 text-slate-600">{row[cellIdx]}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {parsedRows.length > 0 && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                Rozpoznano {parsedRows.length} wierszy kosztów. Podgląd: {parsedRows.slice(0, 3).map(row => `${row.sku}: ${row.cost} zł`).join(', ')}
              </div>
            )}

            {preparedRows.length > 0 && (
              <div className="max-h-44 overflow-auto rounded-lg border border-slate-200">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-left text-slate-500">
                    <tr>
                      <th className="px-2 py-1.5 font-medium">SKU</th>
                      <th className="px-2 py-1.5 font-medium">Koszt</th>
                      <th className="px-2 py-1.5 font-medium">AAD</th>
                      <th className="px-2 py-1.5 font-medium">Ciphertext</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preparedRows.slice(0, 8).map(prepared => (
                      <tr key={`${prepared.product.id}-${prepared.row.sourceRow}`} className="border-t border-slate-100">
                        <td className="px-2 py-1.5 font-mono text-slate-700">{prepared.product.sku_key}</td>
                        <td className="px-2 py-1.5 text-slate-600">{prepared.row.cost} zł</td>
                        <td className="max-w-48 truncate px-2 py-1.5 font-mono text-slate-500">{prepared.encryptedCurrent.aad_context}</td>
                        <td className="max-w-44 truncate px-2 py-1.5 font-mono text-slate-500">{prepared.encryptedCurrent.ciphertext}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {progress && (
              <p className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">{progress}</p>
            )}

            {parseErrors.length > 0 && (
              <p className="whitespace-pre-line rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{parseErrors.slice(0, 8).join('\n')}</p>
            )}

            {notFound.length > 0 && (
              <p className="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
                Nie znaleziono SKU: {notFound.slice(0, 8).join(', ')}
              </p>
            )}

            {error && (
              <p className="whitespace-pre-line rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>
            )}

            <div className="flex gap-2 justify-end">
              <button type="button" onClick={onClose}
                className="apos-button">
                Anuluj
              </button>
              <button type="submit" disabled={!parsedRows.length || parseErrors.length > 0 || Boolean(progress) || !vault.unlocked}
                className={primaryButtonClass}>
                {progress ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />}
                Zaszyfruj podgląd
              </button>
              <button type="button" disabled={!preparedRows.length || Boolean(progress)}
                onClick={() => void handleImport()}
                className={primaryButtonClass}>
                <Upload size={14} />
                Zapisz import
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-4">
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
              <div className="flex items-center gap-2 text-emerald-800 font-medium">
                <CheckCircle2 size={16} />
                Zaktualizowano {result.updated} SKU
              </div>
            </div>

            {result.not_found.length > 0 && (
              <div className="rounded-xl border border-yellow-200 bg-yellow-50 px-4 py-3">
                <p className="text-yellow-800 text-xs font-medium mb-1">
                  Nie znaleziono {result.not_found.length} SKU:
                </p>
                <div className="text-yellow-700 text-xs font-mono space-y-0.5 max-h-32 overflow-y-auto">
                  {result.not_found.map(s => <p key={s}>{s}</p>)}
                </div>
              </div>
            )}

            {result.warnings.length > 0 && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-slate-700 text-xs font-medium mb-1">Uwagi:</p>
                <div className="max-h-28 space-y-0.5 overflow-y-auto text-xs text-slate-500">
                  {result.warnings.slice(0, 8).map(w => <p key={w}>{w}</p>)}
                </div>
              </div>
            )}

            <div className="flex justify-end">
              <button onClick={onClose}
                className={primaryButtonClass}>
                Zamknij
              </button>
            </div>
          </div>
        )}
        </div>
      </div>
    </div>
  )
}

// ── Mobile card view ──────────────────────────────────────────────────────────
function ProductCard({ p, cost, saving, selected, showNet, unlocked, addingHistory, onToggleSelect, onSaveCost, onSaveVat, onSaveMargin, onDeleteHistory, onAddHistory }: {
  p: ProductManageRow
  cost: number | null | undefined
  saving: boolean
  selected: boolean
  showNet: boolean
  unlocked: boolean
  addingHistory: boolean
  onToggleSelect: () => void
  onSaveCost: (netValue: string) => void
  onSaveVat: (v: string) => void
  onSaveMargin: (v: string) => void
  onDeleteHistory: (histId: number, currentEncryptedCost?: EncryptedValue) => void
  onAddHistory: (cost: string, validFrom: string, note?: string) => void
}) {
  return (
    <div className={`rounded-xl border p-4 transition-colors ${selected ? 'border-indigo-500/60 bg-indigo-500/10' : 'border-slate-700/60 bg-slate-800/40'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-xs text-slate-300 truncate">{p.sku_key}</div>
          <div className="text-[11px] text-slate-500 truncate" title={p.name}>{p.name}</div>
        </div>
        <input
          type="checkbox"
          checked={selected}
          aria-label={`Zaznacz produkt ${p.sku_key}`}
          onChange={onToggleSelect}
          className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-600 bg-slate-900 text-indigo-500 focus:ring-indigo-500 focus:ring-offset-0"
        />
      </div>

      <div className="mt-3 border-t border-slate-800 pt-3">
        <p className="text-[11px] text-slate-500">Koszt zakupu</p>
        <div className="text-lg font-bold text-white tabular-nums">
          {unlocked ? (
            <InlineCell
              value={String(visibleCost(cost, p.vat_rate, showNet) ?? 0)}
              saving={saving}
              suffix={showNet ? ' zł netto' : ' zł brutto'}
              onSave={v => onSaveCost(netCostFromVisible(v, p.vat_rate, showNet))}
            />
          ) : (
            <span className="inline-flex items-center gap-1 text-sm font-normal text-slate-500"><Lock size={11} />Zablokowane</span>
          )}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <div>
          <p className="text-[11px] text-slate-500">VAT</p>
          <p className="text-sm font-medium text-slate-300 tabular-nums">
            <InlineCell value={String(normalizeVatRate(p.vat_rate))} saving={saving} suffix="%" min={0} max={25}
              onSave={onSaveVat} />
          </p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500">Cel marży</p>
          <p className="text-sm font-medium text-slate-300 tabular-nums">
            <InlineCell value={p.target_margin_pct} saving={saving} suffix="%"
              onSave={onSaveMargin} />
          </p>
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
              <p className="text-slate-500">Wpisów historii</p>
              <p className="text-slate-300 tabular-nums">{p.cost_history.length || '—'}</p>
            </div>
          </div>
          <CostHistoryPanel
            sku={p}
            onDelete={onDeleteHistory}
            onAdd={onAddHistory}
            adding={addingHistory}
          />
        </div>
      </details>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function Products() {
  const queryClient = useQueryClient()
  const vault = useFinancialVault()
  const financialDisplay = useFinancialDisplayMode()
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [savingId, setSavingId] = useState<number | null>(null)
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [showImportModal, setShowImportModal] = useState(false)
  const [sortCol, setSortCol] = useState<PSortKey>('name')
  const [sortDir, setSortDir] = useState<PSortDir>('asc')
  const [costs, setCosts] = useState<Record<number, number | null>>({})
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(20)
  const [page, setPage] = useState(1)
  const [selectedAccountId, setSelectedAccountId] = useState<number | undefined>(undefined)
  const [selectedProductIds, setSelectedProductIds] = useState<Set<number>>(new Set())
  const [bulkVatDraft, setBulkVatDraft] = useState('')

  const handleSort = (key: PSortKey) => {
    if (sortCol === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(key); setSortDir('asc') }
  }

  const { data: products = [], isLoading } = useQuery({
    queryKey: ['products-manage', selectedAccountId ?? 'all'],
    queryFn: () => productsApi.list(selectedAccountId),
  })
  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: accountsApi.list })
  const connectedAccounts = accounts.filter(a => a.is_connected)
  const selectedAccountName = connectedAccounts.find(a => a.id === selectedAccountId)?.name

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!vault.key) {
        setCosts({})
        return
      }
      const entries: [number, number | null][] = []
      for (let i = 0; i < products.length; i += 1) {
        if (cancelled) return
        const p = products[i]
        entries.push([p.id, await decryptCost(vault.key!, p.encrypted_cost)])
        if ((i + 1) % 10 === 0) await yieldToBrowser()
      }
      if (!cancelled) setCosts(Object.fromEntries(entries))
    }
    run().catch(() => setCosts({}))
    return () => { cancelled = true }
  }, [products, vault.key])

  const patchMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: SkuPatch }) => productsApi.patch(id, data),
    onMutate: ({ id }) => setSavingId(id),
    onSettled: () => setSavingId(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products-manage'] }),
  })

  const addHistoryMutation = useMutation({
    mutationFn: ({ id, encrypted_cost, current_encrypted_cost, validFrom, note }: {
      id: number; encrypted_cost: EncryptedValue; current_encrypted_cost: EncryptedValue; validFrom: string; note?: string
    }) => productsApi.addCostHistory(id, { encrypted_cost, current_encrypted_cost, valid_from: validFrom, note }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products-manage'] }),
  })

  const delHistoryMutation = useMutation({
    mutationFn: ({ skuId, histId, currentEncryptedCost }: { skuId: number; histId: number; currentEncryptedCost?: EncryptedValue }) =>
      productsApi.deleteCostHistory(skuId, histId, currentEncryptedCost),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products-manage'] }),
  })

  const importMutation = useMutation({
    mutationFn: (accountId: number) => productsApi.autoImport(accountId),
    onSuccess: (data, accountId) => {
      queryClient.invalidateQueries({ queryKey: ['products-manage'] })
      setImportMsg(`Konto #${accountId}: +${data.added} SKU, ${data.skipped} istniejących`)
      setTimeout(() => setImportMsg(null), 5000)
    },
  })

  const toggle = (id: number) => setExpandedIds(prev => {
    const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s
  })

  const filtered = sortManageRows(
    search
      ? products.filter(p => p.sku_key.toLowerCase().includes(search.toLowerCase()) || p.name.toLowerCase().includes(search.toLowerCase()))
      : products,
    sortCol, sortDir, costs, financialDisplay.showNet,
  )
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const pageStart = filtered.length === 0 ? 0 : (currentPage - 1) * pageSize + 1
  const pageEnd = Math.min(currentPage * pageSize, filtered.length)
  const pagedProducts = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const selectedCount = selectedProductIds.size
  const pagedProductIds = pagedProducts.map(p => p.id)
  const pageSelectionCount = pagedProductIds.filter(id => selectedProductIds.has(id)).length
  const isPageSelected = pagedProductIds.length > 0 && pageSelectionCount === pagedProductIds.length
  const hasPartialPageSelection = pageSelectionCount > 0 && !isPageSelected

  useEffect(() => {
    setPage(1)
  }, [pageSize, products.length, search, sortCol, sortDir, selectedAccountId, financialDisplay.showNet])

  useEffect(() => {
    if (selectedAccountId && !connectedAccounts.some(a => a.id === selectedAccountId)) {
      setSelectedAccountId(undefined)
    }
  }, [connectedAccounts, selectedAccountId])

  useEffect(() => {
    const productIds = new Set(products.map(p => p.id))
    setSelectedProductIds(prev => {
      const next = new Set([...prev].filter(id => productIds.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [products])

  const toggleSelection = (id: number) => {
    setSelectedProductIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const togglePageSelection = () => {
    setSelectedProductIds(prev => {
      const next = new Set(prev)
      if (isPageSelected) pagedProductIds.forEach(id => next.delete(id))
      else pagedProductIds.forEach(id => next.add(id))
      return next
    })
  }

  async function saveEncryptedCost(id: number, value: string) {
    if (!vault.key) return
    const today = new Date().toISOString().slice(0, 10)
    const keyVersion = vault.status?.key_version ?? 1
    const encrypted = await encryptCost(vault.key, value, skuCostAad(id, keyVersion), keyVersion)
    const historyEncrypted = await encryptCost(vault.key, value, skuCostHistoryAad(id, today, keyVersion), keyVersion)
    patchMutation.mutate({ id, data: { encrypted_cost: encrypted, history_encrypted_cost: historyEncrypted } })
  }

  async function addEncryptedHistory(id: number, cost: string, validFrom: string, note?: string) {
    if (!vault.key) return
    const keyVersion = vault.status?.key_version ?? 1
    const encrypted = await encryptCost(vault.key, cost, skuCostHistoryAad(id, validFrom, keyVersion), keyVersion)
    const currentEncrypted = await encryptCost(vault.key, cost, skuCostAad(id, keyVersion), keyVersion)
    addHistoryMutation.mutate({ id, encrypted_cost: encrypted, current_encrypted_cost: currentEncrypted, validFrom, note })
  }

  const bulkVatMutation = useMutation({
    mutationFn: async ({ ids, vatRate }: { ids: number[]; vatRate: string }) => {
      for (let i = 0; i < ids.length; i += 1) {
        await productsApi.patch(ids[i], { vat_rate: vatRate })
        if ((i + 1) % 10 === 0) await yieldToBrowser()
      }
      return { updated: ids.length, vatRate }
    },
    onSuccess: data => {
      queryClient.invalidateQueries({ queryKey: ['products-manage'] })
      setSelectedProductIds(new Set())
      setBulkVatDraft('')
      setImportMsg(`Zmieniono VAT na ${f(data.vatRate)}% dla ${data.updated} produktów`)
      setTimeout(() => setImportMsg(null), 5000)
    },
  })

  const applyBulkVat = () => {
    const normalized = normalizePercentDraft(bulkVatDraft, 0, 25)
    if (!normalized || selectedProductIds.size === 0 || bulkVatMutation.isPending) return
    bulkVatMutation.mutate({ ids: [...selectedProductIds], vatRate: normalized })
  }

  return (
    <div>
      {showImportModal && (
        <ImportModal
          products={products}
          onClose={() => setShowImportModal(false)}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ['products-manage'] })}
        />
      )}

      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-2xl font-bold text-white">Zarządzanie produktami</h2>
          {selectedAccountName && <p className="mt-0.5 text-sm text-slate-400">Widok konta: {selectedAccountName}</p>}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowImportModal(true)}
            title="CSV jest parsowany i szyfrowany lokalnie w przeglądarce."
            className="flex items-center gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg px-3 py-2">
            <FileSpreadsheet size={12} />Import kosztów
          </button>
          {connectedAccounts.map(a => (
            <button key={a.id} onClick={() => importMutation.mutate(a.id)}
              disabled={importMutation.isPending}
              className="flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg px-3 py-2">
              {importMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              {a.name}
            </button>
          ))}
        </div>
      </div>

      {connectedAccounts.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setSelectedAccountId(undefined)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              selectedAccountId === undefined
                ? 'border-indigo-400 bg-indigo-500/15 text-indigo-100'
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
                  ? 'border-indigo-400 bg-indigo-500/15 text-indigo-100'
                  : 'border-slate-700 bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {account.name}
            </button>
          ))}
        </div>
      )}

      {importMsg && (
        <div className="flex items-center gap-2 text-sm text-emerald-300 bg-emerald-900/30 border border-emerald-800 rounded-xl px-4 py-2.5 mb-4">
          <CheckCircle2 size={14} />{importMsg}
        </div>
      )}

      <div className="mb-4 flex items-center justify-between gap-3">
        <input
          className="w-full max-w-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          placeholder="Szukaj SKU lub nazwy…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500">
            {pageStart}-{pageEnd} z {filtered.length} produktów
          </span>
          <select
            value={pageSize}
            onChange={e => setPageSize(Number(e.target.value) as (typeof PAGE_SIZE_OPTIONS)[number])}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            {PAGE_SIZE_OPTIONS.map(size => <option key={size} value={size}>{size}/str.</option>)}
          </select>
          <button
            type="button"
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={currentPage <= 1}
            className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-700"
          >
            Poprzednia
          </button>
          <span className="min-w-10 text-center text-xs text-slate-500 tabular-nums">
            {currentPage}/{totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={currentPage >= totalPages}
            className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-700"
          >
            Następna
          </button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <button
            type="button"
            onClick={() => setSelectedProductIds(new Set())}
            disabled={selectedCount === 0 || bulkVatMutation.isPending}
            className="inline-flex h-7 items-center gap-1 rounded border border-slate-700 px-2 text-slate-300 disabled:opacity-40 hover:bg-slate-700"
          >
            <X size={12} />Wyczyść
          </button>
          <span>{selectedCount} zaznaczonych</span>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400" htmlFor="bulk-vat">VAT</label>
          <input
            id="bulk-vat"
            type="number"
            min={0}
            max={25}
            step="0.01"
            value={bulkVatDraft}
            onChange={e => setBulkVatDraft(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') applyBulkVat() }}
            className="h-8 w-24 rounded border border-slate-700 bg-slate-900 px-2 text-right text-xs text-white focus:border-indigo-500 focus:outline-none"
            placeholder="23"
          />
          <span className="text-xs text-slate-500">%</span>
          <button
            type="button"
            onClick={applyBulkVat}
            disabled={selectedCount === 0 || !normalizePercentDraft(bulkVatDraft, 0, 25) || bulkVatMutation.isPending}
            className="inline-flex h-8 items-center gap-1.5 rounded bg-indigo-600 px-3 text-xs font-medium text-white disabled:opacity-50 hover:bg-indigo-500"
          >
            {bulkVatMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
            Zastosuj
          </button>
        </div>
      </div>

      <div className="hidden lg:block w-full max-w-full overflow-x-auto overscroll-x-contain rounded-xl border border-slate-700/60 bg-slate-800 [-webkit-overflow-scrolling:touch]">
        <table className="min-w-[72rem] table-auto text-xs">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="w-6 px-2 py-3" />
              <th className="w-9 px-2 py-3 text-center">
                <input
                  type="checkbox"
                  checked={isPageSelected}
                  aria-label="Zaznacz produkty na bieżącej stronie"
                  title={hasPartialPageSelection ? 'Część strony jest zaznaczona' : 'Zaznacz bieżącą stronę'}
                  onChange={togglePageSelection}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500 focus:ring-indigo-500 focus:ring-offset-0"
                />
              </th>
              {PCOLS.map(col => (
                <PSortTh key={col.key} col={col} sortKey={sortCol} sortDir={sortDir} onSort={handleSort} />
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={8} className="py-10 text-center"><Loader2 size={20} className="animate-spin mx-auto text-slate-600" /></td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={8} className="py-10 text-center text-slate-500">
                {search ? 'Brak wyników' : selectedAccountId ? 'Brak produktów dla tego konta' : 'Brak produktów — auto-importuj SKU z Allegro'}
              </td></tr>
            ) : pagedProducts.map((p: ProductManageRow) => {
              const expanded = expandedIds.has(p.id)
              const saving = savingId === p.id || (bulkVatMutation.isPending && selectedProductIds.has(p.id))
              const selected = selectedProductIds.has(p.id)
              return [
                <tr key={p.id} className={`border-t border-slate-700/40 transition-colors ${selected ? 'bg-indigo-500/10 hover:bg-indigo-500/15' : 'hover:bg-slate-700/20'}`}>
                  <td className="px-2 py-2.5">
                    <button onClick={() => toggle(p.id)} className="text-slate-500 hover:text-slate-300">
                      {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    </button>
                  </td>
                  <td className="px-2 py-2.5 text-center">
                    <input
                      type="checkbox"
                      checked={selected}
                      aria-label={`Zaznacz produkt ${p.sku_key}`}
                      onChange={() => toggleSelection(p.id)}
                      className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500 focus:ring-indigo-500 focus:ring-offset-0"
                    />
                  </td>
                  <td className="px-3 py-2.5 font-mono text-slate-300 cursor-pointer" onClick={() => toggle(p.id)}>{p.sku_key}</td>
                  <td className="px-3 py-2.5 text-slate-400 max-w-[220px] truncate" title={p.name}>{p.name}</td>
                  <td className="px-3 py-2.5 text-right font-medium text-white">
                    {vault.unlocked ? (
                      <InlineCell
                        value={String(visibleCost(costs[p.id], p.vat_rate, financialDisplay.showNet) ?? 0)}
                        saving={saving}
                        suffix={financialDisplay.showNet ? ' zł netto' : ' zł brutto'}
                        onSave={v => saveEncryptedCost(p.id, netCostFromVisible(v, p.vat_rate, financialDisplay.showNet))}
                      />
                    ) : (
                      <span className="inline-flex items-center justify-end gap-1 text-slate-500"><Lock size={11} />Zablokowane</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-400">
                    <InlineCell value={String(normalizeVatRate(p.vat_rate))} saving={saving} suffix="%" min={0} max={25}
                      onSave={v => patchMutation.mutate({ id: p.id, data: { vat_rate: v } })} />
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-400">
                    <InlineCell value={p.target_margin_pct} saving={saving} suffix="%"
                      onSave={v => patchMutation.mutate({ id: p.id, data: { target_margin_pct: v } })} />
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-500">{p.cost_history.length || '—'}</td>
                </tr>,
                expanded && (
                  <tr key={`${p.id}-detail`} className="border-t border-slate-700/20">
                    <td colSpan={8} className="px-4 pb-3 bg-slate-900/40">
                      <CostHistoryPanel
                        sku={p}
                        onDelete={(histId, currentEncryptedCost) => delHistoryMutation.mutate({ skuId: p.id, histId, currentEncryptedCost })}
                        onAdd={(cost, validFrom, note) => addEncryptedHistory(p.id, cost, validFrom, note)}
                        adding={addHistoryMutation.isPending && (addHistoryMutation.variables as any)?.id === p.id}
                      />
                    </td>
                  </tr>
                ),
              ]
            })}
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
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-10 text-center text-slate-500">
            {search ? 'Brak wyników' : selectedAccountId ? 'Brak produktów dla tego konta' : 'Brak produktów — auto-importuj SKU z Allegro'}
          </div>
        ) : pagedProducts.map((p: ProductManageRow) => (
          <ProductCard
            key={p.id}
            p={p}
            cost={costs[p.id]}
            saving={savingId === p.id || (bulkVatMutation.isPending && selectedProductIds.has(p.id))}
            selected={selectedProductIds.has(p.id)}
            showNet={financialDisplay.showNet}
            unlocked={vault.unlocked}
            addingHistory={addHistoryMutation.isPending && (addHistoryMutation.variables as any)?.id === p.id}
            onToggleSelect={() => toggleSelection(p.id)}
            onSaveCost={net => void saveEncryptedCost(p.id, net)}
            onSaveVat={v => patchMutation.mutate({ id: p.id, data: { vat_rate: v } })}
            onSaveMargin={v => patchMutation.mutate({ id: p.id, data: { target_margin_pct: v } })}
            onDeleteHistory={(histId, currentEncryptedCost) => delHistoryMutation.mutate({ skuId: p.id, histId, currentEncryptedCost })}
            onAddHistory={(cost, validFrom, note) => addEncryptedHistory(p.id, cost, validFrom, note)}
          />
        ))}
      </div>
    </div>
  )
}
