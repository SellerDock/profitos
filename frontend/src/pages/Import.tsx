import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, CheckCircle2, AlertCircle, Clock, ShoppingCart, Receipt, Package } from 'lucide-react'
import { importApi, type SyncResult } from '../api/client'

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const utcIso = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`
  const d = new Date(utcIso)
  const local = d.toLocaleString('pl-PL', {
    timeZone: 'Europe/Warsaw',
    dateStyle: 'short',
    timeStyle: 'short',
  })
  const diffMs = Date.now() - d.getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  let elapsed: string
  if (diffMin < 60) {
    elapsed = `${diffMin} min temu`
  } else if (diffMin < 60 * 24) {
    elapsed = `${Math.floor(diffMin / 60)} godz. temu`
  } else {
    elapsed = `${Math.floor(diffMin / 1440)} dni temu`
  }
  return `${local} (Europe/Warsaw) — ${elapsed}`
}

function StatPill({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: number }) {
  return (
    <span className="flex items-center gap-1 text-xs text-slate-400">
      <Icon size={11} className="text-slate-500" />
      {value} {label}
    </span>
  )
}

export default function Import() {
  const queryClient = useQueryClient()
  const [results, setResults] = useState<Record<number, SyncResult>>({})

  const { data: statuses = [], isLoading } = useQuery({
    queryKey: ['import-status'],
    queryFn: importApi.status,
    refetchInterval: 30_000,
  })

  const syncMutation = useMutation({
    mutationFn: (accountId: number) => importApi.sync(accountId, 90),
    onSuccess: (data) => {
      setResults(prev => ({ ...prev, [data.account_id]: data }))
      queryClient.invalidateQueries({ queryKey: ['import-status'] })
    },
  })

  const isSyncing = (accountId: number) =>
    syncMutation.isPending && syncMutation.variables === accountId

  return (
    <div className="max-w-2xl">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-white">Import danych</h2>
          <p className="text-slate-400 text-sm mt-1 flex items-center gap-1.5">
            <Clock size={13} />
            Automatyczna synchronizacja co godzinę (ostatnie 48h) działa w tle dla połączonych kont
          </p>
        </div>
      </div>

      {isLoading ? (
        <p className="text-slate-400 text-sm">Ładowanie...</p>
      ) : statuses.length === 0 ? (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-8 text-center">
          <AlertCircle size={32} className="text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400 text-sm">Brak połączonych kont Allegro.</p>
          <p className="text-slate-500 text-xs mt-1">
            Przejdź do Ustawień, dodaj konto i autoryzuj je przez OAuth.
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {statuses.map(s => {
            const freshResult = results[s.account_id]
            const last = freshResult
              ? {
                  synced_at: freshResult.synced_at,
                  orders_count: freshResult.orders_count,
                  billing_count: freshResult.billing_count,
                  offers_count: freshResult.offers_count,
                  days_fetched: freshResult.days_fetched,
                  error: freshResult.error,
                }
              : s.last_sync
            const syncing = isSyncing(s.account_id)

            return (
              <li key={s.account_id} className="bg-slate-800 rounded-xl border border-slate-700 p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <span
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: s.color }}
                    />
                    <p className="text-white font-medium text-sm">{s.account_name}</p>
                  </div>
                  <button
                    onClick={() => syncMutation.mutate(s.account_id)}
                    disabled={syncing}
                    className="flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg px-3 py-1.5 transition-colors"
                  >
                    <RefreshCw size={12} className={syncing ? 'animate-spin' : ''} />
                    {syncing ? 'Synchronizuję...' : 'Synchronizuj dane (90 dni)'}
                  </button>
                </div>

                {last ? (
                  <div className="bg-slate-900 rounded-lg p-3 space-y-2">
                    <div className="flex items-center gap-2">
                      {last.error ? (
                        <AlertCircle size={13} className="text-red-400 flex-shrink-0" />
                      ) : (
                        <CheckCircle2 size={13} className="text-emerald-400 flex-shrink-0" />
                      )}
                      <span className="text-xs text-slate-400">
                        Ostatnia synchronizacja:{' '}
                        <span className="text-slate-300">{formatDate(last.synced_at)}</span>
                      </span>
                    </div>
                    {last.error ? (
                      <p className="text-xs text-red-400 pl-5">{last.error}</p>
                    ) : (
                      <div className="flex items-center gap-4 pl-5">
                        <StatPill icon={ShoppingCart} label="zamówień" value={last.orders_count} />
                        <StatPill icon={Receipt} label="wpisów rozliczeń" value={last.billing_count} />
                        <StatPill icon={Package} label="ofert" value={last.offers_count} />
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="bg-slate-900 rounded-lg p-3">
                    <p className="text-xs text-slate-500 flex items-center gap-1.5">
                      <Clock size={11} />
                      Brak danych — uruchom pierwszą synchronizację
                    </p>
                  </div>
                )}

                {syncMutation.isError && syncMutation.variables === s.account_id && (
                  <p className="text-xs text-red-400 mt-2 flex items-center gap-1">
                    <AlertCircle size={11} />
                    {(syncMutation.error as Error).message}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <div className="mt-4 bg-yellow-950/30 rounded-xl border border-yellow-800/40 px-4 py-3">
        <p className="text-xs text-yellow-500/90 flex items-start gap-2">
          <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
          <span>
            <strong className="text-yellow-400">Zamówienia w walutach obcych (CZK / EUR / HUF)</strong>{' '}
            są zapisywane do bazy danych, ale pomijane w obliczeniach wyników finansowych.
            Obsługa wielu walut zostanie dodana w przyszłej wersji.
          </span>
        </p>
      </div>

      <div className="mt-3 bg-slate-800/50 rounded-xl border border-slate-700/50 px-4 py-3">
        <p className="text-xs text-slate-500 flex items-center gap-2">
          <Clock size={12} />
          <span>
            <strong className="text-slate-400">Automatyczna synchronizacja</strong> działa co godzinę i pobiera dane
            z ostatnich 48h. Kliknij <em>"Synchronizuj dane"</em> aby pobrać pełne 90 dni historii.
          </span>
        </p>
      </div>
    </div>
  )
}
