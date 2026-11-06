import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, Trash2, AlertTriangle, CheckCircle2, FileText, RefreshCw } from 'lucide-react'
import { adsImportApi, accountsApi, type AdsImportResult, type AdsImportListEntry } from '../api/client'

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })
}

function formatPln(v: string): string {
  const n = Number(v)
  return isNaN(n) ? v : n.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' zł'
}

export default function AdsImport() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null)
  const [uploadResult, setUploadResult] = useState<AdsImportResult | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [deleteRange, setDeleteRange] = useState<{ from: string; to: string } | null>(null)

  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
  })

  const importableAccounts = accounts.filter(account =>
    account.is_connected || account.token_expires_at || account.allegro_client_id !== 'dummy_id'
  )
  const accountId = selectedAccountId ?? (importableAccounts[0]?.id ?? null)

  useEffect(() => {
    if (selectedAccountId && !importableAccounts.some(account => account.id === selectedAccountId)) {
      setSelectedAccountId(null)
    }
  }, [importableAccounts, selectedAccountId])

  const { data: imports = [], isLoading: importsLoading } = useQuery({
    queryKey: ['ads-imports', accountId],
    queryFn: () => (accountId ? adsImportApi.list(accountId) : Promise.resolve([])),
    enabled: !!accountId,
  })

  const uploadMutation = useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) => adsImportApi.upload(id, file),
    onSuccess: (data) => {
      setUploadResult(data)
      setUploadError(null)
      queryClient.invalidateQueries({ queryKey: ['ads-imports', accountId] })
    },
    onError: (err: any) => {
      setUploadError(err?.response?.data?.detail ?? String(err))
      setUploadResult(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ from, to }: { from: string; to: string }) =>
      adsImportApi.delete(accountId!, from, to),
    onSuccess: () => {
      setDeleteRange(null)
      queryClient.invalidateQueries({ queryKey: ['ads-imports', accountId] })
    },
  })

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !accountId) return
    setUploadResult(null)
    setUploadError(null)
    uploadMutation.mutate({ id: accountId, file })
    e.target.value = ''
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Import reklam</h2>
        <p className="text-slate-400 text-sm mt-1">
          Wgraj plik CSV lub XLSX ze "Statystyki ofert" z panelu reklam Allegro,
          aby przypisać koszty kampanii do konkretnych ofert i dni.
        </p>
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
        <h3 className="text-white font-semibold">Jak pobrać plik z Allegro Ads</h3>
        <ol className="mt-3 space-y-2 text-sm leading-6 text-slate-300">
          <li><span className="font-semibold text-white">1.</span> Wejdź w Allegro Ads i otwórz statystyki ofert.</li>
          <li><span className="font-semibold text-white">2.</span> Wybierz zakres dat, który chcesz rozliczyć.</li>
          <li><span className="font-semibold text-white">3.</span> Eksportuj plik ze statystykami ofert, nie plik sprzedażowy.</li>
          <li><span className="font-semibold text-white">4.</span> Wgraj tutaj plik z kolumnami: <span className="font-mono text-slate-100">Okres</span>, <span className="font-mono text-slate-100">Numer klikniętej oferty</span>, <span className="font-mono text-slate-100">Koszt(PLN)</span>.</li>
        </ol>
        <p className="mt-3 text-xs text-slate-500">
          Jeśli oferta nie jest jeszcze znana w ProfitOS, najpierw uruchom import danych Allegro, a potem ponów import reklam.
        </p>
      </div>

      {/* Account selector */}
      {importableAccounts.length > 1 && (
        <div className="flex items-center gap-3">
          <label className="text-slate-400 text-sm">Konto:</label>
          <select
            value={accountId ?? ''}
            onChange={e => setSelectedAccountId(Number(e.target.value))}
            className="bg-slate-800 border border-slate-600 text-white text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {importableAccounts.map(a => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Upload section */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
        <h3 className="text-white font-semibold flex items-center gap-2">
          <Upload size={16} className="text-indigo-400" />
          Wgraj plik statystyk
        </h3>
        <p className="text-slate-400 text-xs">
          Plik musi zawierać nagłówek z kolumnami: <span className="font-mono text-slate-300">Koszt(PLN)</span>,{' '}
          <span className="font-mono text-slate-300">Numer klikniętej oferty</span>,{' '}
          <span className="font-mono text-slate-300">Okres</span>.{' '}
          Nie wgrywaj pliku <span className="font-mono text-slate-300">_sprzedaż.csv</span>.
        </p>

        <div className="flex items-center gap-3">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending || !accountId}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {uploadMutation.isPending
              ? <><RefreshCw size={14} className="animate-spin" /> Importowanie...</>
              : <><Upload size={14} /> Wybierz plik (.csv / .xlsx)</>}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx"
            onChange={handleFileChange}
            className="hidden"
          />
        </div>

        {/* Upload result */}
        {uploadResult && (
          <div className="bg-emerald-950/50 border border-emerald-800/60 rounded-lg p-4 space-y-2">
            <div className="flex items-center gap-2 text-emerald-400 font-semibold text-sm">
              <CheckCircle2 size={15} />
              Import zakończony
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-slate-300">
              <span className="text-slate-400">Wiersze sparsowane:</span>
              <span>{uploadResult.rows_parsed}</span>
              <span className="text-slate-400">Wiersze zaimportowane:</span>
              <span>{uploadResult.rows_imported}</span>
              <span className="text-slate-400">Pominięte:</span>
              <span>{uploadResult.rows_skipped}</span>
              {uploadResult.date_range && (
                <>
                  <span className="text-slate-400">Zakres dat:</span>
                  <span>{uploadResult.date_range.from} – {uploadResult.date_range.to}</span>
                </>
              )}
              <span className="text-slate-400">Łączny koszt:</span>
              <span className="text-red-300">{formatPln(uploadResult.total_cost)}</span>
            </div>
            {uploadResult.unmatched_offers.length > 0 && (
              <div className="mt-2">
                <p className="text-yellow-400 text-xs font-medium flex items-center gap-1.5 mb-1">
                  <AlertTriangle size={12} />
                  Oferty nieznane w bazie ({uploadResult.unmatched_offers.length}):
                </p>
                <p className="text-slate-400 text-xs font-mono break-all">
                  {uploadResult.unmatched_offers.join(', ')}
                </p>
              </div>
            )}
          </div>
        )}

        {uploadError && (
          <div className="bg-red-950/50 border border-red-800/60 rounded-lg p-3 text-red-300 text-sm flex items-start gap-2">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            {uploadError}
          </div>
        )}
      </div>

      {/* Past imports list */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
        <h3 className="text-white font-semibold flex items-center gap-2">
          <FileText size={16} className="text-slate-400" />
          Poprzednie importy
        </h3>

        {importsLoading && (
          <div className="text-slate-500 text-sm">Ładowanie...</div>
        )}

        {!importsLoading && imports.length === 0 && (
          <p className="text-slate-500 text-sm">Brak zaimportowanych danych dla tego konta.</p>
        )}

        {imports.length > 0 && (
          <div className="space-y-2">
            {imports.map((entry: AdsImportListEntry) => (
              <div
                key={`${entry.imported_filename}-${entry.imported_at}`}
                className="flex items-center justify-between bg-slate-900/50 border border-slate-700/50 rounded-lg px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-white text-sm font-medium truncate">{entry.imported_filename || '(bez nazwy)'}</p>
                  <p className="text-slate-400 text-xs mt-0.5">
                    {entry.date_from} – {entry.date_to}
                    <span className="mx-2 text-slate-600">·</span>
                    {entry.rows_count} wierszy
                    <span className="mx-2 text-slate-600">·</span>
                    <span className="text-red-300">{formatPln(entry.total_cost)}</span>
                  </p>
                  <p className="text-slate-600 text-xs mt-0.5">
                    Wgrano: {formatDate(entry.imported_at)}
                  </p>
                </div>
                <button
                  onClick={() => setDeleteRange({ from: entry.date_from, to: entry.date_to })}
                  className="ml-4 p-2 text-slate-500 hover:text-red-400 hover:bg-red-900/30 rounded-lg transition-colors"
                  title="Usuń dane z tego zakresu"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Delete confirmation modal */}
      {deleteRange && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-800 border border-slate-600 rounded-xl p-6 max-w-sm w-full space-y-4">
            <h3 className="text-white font-semibold text-lg">Potwierdź usunięcie</h3>
            <p className="text-slate-300 text-sm">
              Usunąć wszystkie zaimportowane dane Ads dla zakresu{' '}
              <span className="font-mono text-white">{deleteRange.from} – {deleteRange.to}</span>?
              Możesz ponownie wgrać plik.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => deleteMutation.mutate({ from: deleteRange.from, to: deleteRange.to })}
                disabled={deleteMutation.isPending}
                className="flex-1 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {deleteMutation.isPending ? 'Usuwanie...' : 'Usuń'}
              </button>
              <button
                onClick={() => setDeleteRange(null)}
                className="flex-1 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium rounded-lg transition-colors"
              >
                Anuluj
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
