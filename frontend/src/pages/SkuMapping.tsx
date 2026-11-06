import { useState, useCallback, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Pencil, Trash2, RefreshCw, X, Check, FlaskConical } from 'lucide-react'
import {
  skuMappingApi,
  type SkuMultiplierPattern,
  type PatternCreate,
  type PatternUpdate,
  type TestPatternResultItem,
} from '../api/client'

// ── Helpers ───────────────────────────────────────────────────────────────────

function useDebounce<T extends (...args: Parameters<T>) => void>(fn: T, delay: number): T {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  return useCallback((...args: Parameters<T>) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => fn(...args), delay)
  }, [fn, delay]) as T
}

// ── Pattern row (inline edit) ─────────────────────────────────────────────────

interface EditState {
  pattern_regex: string
  multiplier: string
  description: string
  priority: string
  enabled: boolean
}

function PatternRow({
  pattern,
  onSaved,
  onDeleted,
}: {
  pattern: SkuMultiplierPattern
  onSaved: () => void
  onDeleted: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<EditState>({
    pattern_regex: pattern.pattern_regex,
    multiplier: String(pattern.multiplier),
    description: pattern.description ?? '',
    priority: String(pattern.priority),
    enabled: pattern.enabled,
  })
  const [error, setError] = useState<string | null>(null)

  const updateMut = useMutation({
    mutationFn: (data: PatternUpdate) => skuMappingApi.update(pattern.id, data),
    onSuccess: () => { setEditing(false); setError(null); onSaved() },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Błąd zapisu')
    },
  })
  const deleteMut = useMutation({
    mutationFn: () => skuMappingApi.delete(pattern.id),
    onSuccess: onDeleted,
  })

  function startEdit() {
    setForm({
      pattern_regex: pattern.pattern_regex,
      multiplier: String(pattern.multiplier),
      description: pattern.description ?? '',
      priority: String(pattern.priority),
      enabled: pattern.enabled,
    })
    setError(null)
    setEditing(true)
  }

  function handleSave() {
    const mult = parseFloat(form.multiplier)
    if (isNaN(mult) || mult <= 0) { setError('Mnożnik musi być > 0'); return }
    const prio = parseInt(form.priority, 10)
    if (isNaN(prio)) { setError('Priorytet musi być liczbą'); return }
    updateMut.mutate({
      pattern_regex: form.pattern_regex.trim(),
      multiplier: mult,
      description: form.description.trim() || null,
      priority: prio,
      enabled: form.enabled,
    })
  }

  const tdBase = 'px-3 py-2 text-sm'

  if (editing) {
    return (
      <tr className="bg-slate-700/40">
        <td className={tdBase}>
          <input
            className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-100 font-mono text-xs"
            value={form.pattern_regex}
            onChange={e => setForm(f => ({ ...f, pattern_regex: e.target.value }))}
          />
        </td>
        <td className={tdBase}>
          <input
            type="number" step="0.1" min="0.1"
            className="w-20 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
            value={form.multiplier}
            onChange={e => setForm(f => ({ ...f, multiplier: e.target.value }))}
          />
        </td>
        <td className={tdBase}>
          <input
            className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
          />
        </td>
        <td className={tdBase}>
          <input
            type="number"
            className="w-16 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
            value={form.priority}
            onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}
          />
        </td>
        <td className={`${tdBase} text-center`}>
          <input
            type="checkbox" checked={form.enabled}
            onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))}
            className="accent-emerald-500"
          />
        </td>
        <td className={tdBase}>
          <div className="flex items-center gap-2">
            {error && <span className="text-rose-400 text-xs">{error}</span>}
            <button
              onClick={handleSave}
              disabled={updateMut.isPending}
              className="text-emerald-400 hover:text-emerald-300 disabled:opacity-40"
              title="Zapisz"
            >
              <Check size={16} />
            </button>
            <button
              onClick={() => setEditing(false)}
              className="text-slate-400 hover:text-slate-200"
              title="Anuluj"
            >
              <X size={16} />
            </button>
          </div>
        </td>
      </tr>
    )
  }

  return (
    <tr className="border-t border-slate-700/50 hover:bg-slate-700/20">
      <td className={`${tdBase} font-mono text-xs text-sky-300`}>{pattern.pattern_regex}</td>
      <td className={`${tdBase} text-right text-slate-200`}>{parseFloat(pattern.multiplier).toLocaleString('pl-PL')}</td>
      <td className={`${tdBase} text-slate-400`}>{pattern.description ?? '—'}</td>
      <td className={`${tdBase} text-right text-slate-400`}>{pattern.priority}</td>
      <td className={`${tdBase} text-center`}>
        <span className={pattern.enabled ? 'text-emerald-400' : 'text-slate-500'}>
          {pattern.enabled ? 'tak' : 'nie'}
        </span>
      </td>
      <td className={tdBase}>
        <div className="flex items-center gap-2">
          <button onClick={startEdit} className="text-slate-400 hover:text-sky-400" title="Edytuj">
            <Pencil size={14} />
          </button>
          <button
            onClick={() => { if (confirm('Usunąć ten wzorzec?')) deleteMut.mutate() }}
            disabled={deleteMut.isPending}
            className="text-slate-400 hover:text-rose-400 disabled:opacity-40"
            title="Usuń"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </td>
    </tr>
  )
}

// ── Add pattern modal ─────────────────────────────────────────────────────────

interface AddModalProps { onClose: () => void; onSaved: () => void }

function AddModal({ onClose, onSaved }: AddModalProps) {
  const [form, setForm] = useState<PatternCreate>({
    pattern_regex: '',
    multiplier: 2,
    description: '',
    priority: 100,
    enabled: true,
  })
  const [previewInput, setPreviewInput] = useState('')
  const [previewResults, setPreviewResults] = useState<TestPatternResultItem[] | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const createMut = useMutation({
    mutationFn: (data: PatternCreate) => skuMappingApi.create(data),
    onSuccess: () => { onSaved(); onClose() },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      if (Array.isArray(detail)) {
        setSaveError(detail.map((d: { msg?: string }) => d.msg).join('; '))
      } else {
        setSaveError(String(detail ?? 'Błąd zapisu'))
      }
    },
  })

  const runPreview = useCallback(async (regex: string, sample: string) => {
    if (!regex.trim() || !sample.trim()) { setPreviewResults(null); return }
    setPreviewError(null)
    try {
      const results = await skuMappingApi.test({ pattern_regex: regex, sample_offer_names: [sample] })
      setPreviewResults(results)
    } catch {
      setPreviewError('Błąd testu regex')
      setPreviewResults(null)
    }
  }, [])

  const debouncedPreview = useDebounce(runPreview, 400)

  function handleRegexChange(val: string) {
    setForm(f => ({ ...f, pattern_regex: val }))
    debouncedPreview(val, previewInput)
  }

  function handlePreviewInputChange(val: string) {
    setPreviewInput(val)
    debouncedPreview(form.pattern_regex, val)
  }

  function handleSave() {
    setSaveError(null)
    if (!form.pattern_regex.trim()) { setSaveError('Regex nie może być pusty'); return }
    if (form.multiplier <= 0) { setSaveError('Mnożnik musi być > 0'); return }
    createMut.mutate({ ...form, description: form.description || undefined })
  }

  const previewMatch = previewResults?.[0]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-slate-800 border border-slate-700 rounded-xl w-full max-w-lg p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Dodaj wzorzec</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Wyrażenie regularne</label>
            <input
              className="w-full bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sky-300 font-mono text-sm"
              placeholder="^3 x (.*)$"
              value={form.pattern_regex}
              onChange={e => handleRegexChange(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Mnożnik</label>
              <input
                type="number" step="0.1" min="0.1"
                className="w-full bg-slate-900 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
                value={form.multiplier}
                onChange={e => setForm(f => ({ ...f, multiplier: parseFloat(e.target.value) || 1 }))}
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Priorytet</label>
              <input
                type="number"
                className="w-full bg-slate-900 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
                value={form.priority}
                onChange={e => setForm(f => ({ ...f, priority: parseInt(e.target.value, 10) || 100 }))}
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1">Opis</label>
            <input
              className="w-full bg-slate-900 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="Pakiet 3 sztuki"
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox" id="enabled-chk" checked={form.enabled}
              onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))}
              className="accent-emerald-500"
            />
            <label htmlFor="enabled-chk" className="text-sm text-slate-300">Aktywny</label>
          </div>

          {/* Live preview */}
          <div className="border border-slate-700 rounded-lg p-3 space-y-2">
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <FlaskConical size={13} />
              <span>Podgląd dopasowania</span>
            </div>
            <input
              className="w-full bg-slate-900 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="Wpisz przykładową nazwę oferty…"
              value={previewInput}
              onChange={e => handlePreviewInputChange(e.target.value)}
            />
            {previewError && (
              <p className="text-xs text-rose-400">{previewError}</p>
            )}
            {previewMatch && (
              previewMatch.matched ? (
                <div className="text-xs text-emerald-400 space-y-0.5">
                  <p>Pasuje.</p>
                  {previewMatch.captured_group != null && (
                    <p>Przechwycona nazwa bazowa: <span className="font-mono text-white">{previewMatch.captured_group}</span></p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-amber-400">Nie pasuje.</p>
              )
            )}
          </div>
        </div>

        {saveError && <p className="mt-3 text-sm text-rose-400">{saveError}</p>}

        <div className="flex justify-end gap-3 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">
            Anuluj
          </button>
          <button
            onClick={handleSave}
            disabled={createMut.isPending}
            className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg disabled:opacity-50"
          >
            {createMut.isPending ? 'Zapisuję…' : 'Zapisz'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SkuMapping() {
  const qc = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [reapplyMsg, setReapplyMsg] = useState<string | null>(null)

  const patternsQ = useQuery({
    queryKey: ['sku-mapping-patterns'],
    queryFn: () => skuMappingApi.list(),
  })

  const unmatchedQ = useQuery({
    queryKey: ['sku-mapping-unmatched'],
    queryFn: () => skuMappingApi.unmatchedOffers(5),
  })

  const reapplyMut = useMutation({
    mutationFn: () => skuMappingApi.reapply(),
    onSuccess: (r) => {
      setReapplyMsg(`Zaktualizowano ${r.updated_count} aliasów (bez zmian: ${r.unchanged_count})`)
      setTimeout(() => setReapplyMsg(null), 5000)
    },
  })

  function refresh() {
    qc.invalidateQueries({ queryKey: ['sku-mapping-patterns'] })
    qc.invalidateQueries({ queryKey: ['sku-mapping-unmatched'] })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-white mb-1">Wzorce mnożnika SKU</h2>
        <p className="text-slate-400 text-sm max-w-2xl">
          Wzorce wykrywają oferty wielopakowe (np. "2 x Glicynian") i przypisują mnożnik kosztu.
          Dodaj własne wzorce dla pakietów 3x, 12x lub innych konwencji.
        </p>
      </div>

      {/* Action bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded-lg"
        >
          <Plus size={16} />
          Dodaj wzorzec
        </button>
        <button
          onClick={() => reapplyMut.mutate()}
          disabled={reapplyMut.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded-lg disabled:opacity-50"
        >
          <RefreshCw size={16} className={reapplyMut.isPending ? 'animate-spin' : ''} />
          Zastosuj ponownie
        </button>
        {reapplyMsg && (
          <span className="text-sm text-emerald-400">{reapplyMsg}</span>
        )}
      </div>

      {/* Patterns table */}
      <div className="apos-scroll-table-dark">
        {patternsQ.isLoading && (
          <p className="text-slate-400 text-sm p-4">Ładowanie…</p>
        )}
        {patternsQ.isError && (
          <p className="text-rose-400 text-sm p-4">Błąd ładowania wzorców.</p>
        )}
        {patternsQ.data && (
          <table className="w-full min-w-[56rem]">
            <thead className="bg-slate-700/50">
              <tr>
                <th className="px-3 py-2.5 text-left text-xs text-slate-400 font-medium">Regex</th>
                <th className="px-3 py-2.5 text-right text-xs text-slate-400 font-medium">Mnożnik</th>
                <th className="px-3 py-2.5 text-left text-xs text-slate-400 font-medium">Opis</th>
                <th className="px-3 py-2.5 text-right text-xs text-slate-400 font-medium">Priorytet</th>
                <th className="px-3 py-2.5 text-center text-xs text-slate-400 font-medium">Aktywny</th>
                <th className="px-3 py-2.5 text-left text-xs text-slate-400 font-medium">Akcje</th>
              </tr>
            </thead>
            <tbody>
              {patternsQ.data.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-slate-500 text-sm">
                    Brak wzorców. Dodaj pierwszy.
                  </td>
                </tr>
              ) : (
                patternsQ.data.map(p => (
                  <PatternRow
                    key={p.id}
                    pattern={p}
                    onSaved={refresh}
                    onDeleted={refresh}
                  />
                ))
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* Unmatched offers suggestions */}
      {unmatchedQ.data && unmatchedQ.data.length > 0 && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-slate-300 mb-2">
            Przykładowe oferty bez dopasowania
          </h3>
          <p className="text-xs text-slate-500 mb-3">
            Te oferty nie pasują do żadnego aktywnego wzorca — możesz je użyć jako inspirację.
          </p>
          <ul className="space-y-1">
            {unmatchedQ.data.map(o => (
              <li key={o.offer_id} className="flex items-center gap-2 text-sm">
                <span className="font-mono text-xs text-slate-500 w-36 truncate">{o.sku ?? '—'}</span>
                <span className="text-slate-300">{o.name}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {showAdd && (
        <AddModal
          onClose={() => setShowAdd(false)}
          onSaved={refresh}
        />
      )}
    </div>
  )
}
