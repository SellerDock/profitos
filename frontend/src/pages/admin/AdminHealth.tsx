import { useQuery } from '@tanstack/react-query'
import { adminApi, type SystemHealth } from '../../api/client'

const labels: Record<keyof SystemHealth, string> = {
  status: 'Status',
  db_ok: 'Baza danych',
  tenants_count: 'Konta',
  users_count: 'Użytkownicy',
  active_sessions: 'Aktywne sesje',
  pending_activations: 'Oczekujące aktywacje',
  pending_waitlist: 'Zgłoszenia oczekujące',
  last_sync_at: 'Ostatnia synchronizacja',
  checked_at: 'Ostatnie sprawdzenie',
}

function formatValue(key: keyof SystemHealth, value: SystemHealth[keyof SystemHealth]) {
  if (value === null) return 'brak'
  if (typeof value === 'boolean') return value ? 'OK' : 'problem'
  if (typeof value === 'string' && key.endsWith('_at')) return value.slice(0, 19).replace('T', ' ')
  return String(value)
}

export default function AdminHealth() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-system-health'],
    queryFn: adminApi.systemHealth,
    refetchInterval: 30_000,
  })

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Zdrowie systemu</h2>
          <p className="mt-1 text-sm text-slate-400">Odświeżane automatycznie co 30 sekund.</p>
        </div>
        {data && (
          <span className={`rounded px-2.5 py-1 text-xs font-medium ${
            data.db_ok ? 'bg-emerald-500/15 text-emerald-200' : 'bg-red-500/15 text-red-200'
          }`}>
            {data.status === 'ok' ? 'Wszystko wygląda dobrze' : 'Wymaga sprawdzenia'}
          </span>
        )}
      </div>

      <div className="overflow-x-auto rounded border border-slate-700">
        <table className="min-w-[42rem] divide-y divide-slate-700 text-sm">
          <tbody className="divide-y divide-slate-800 bg-slate-900 text-slate-200">
            {isLoading && <tr><td className="px-3 py-4" colSpan={2}>Ładowanie...</td></tr>}
            {isError && <tr><td className="px-3 py-4 text-red-200" colSpan={2}>Nie udało się pobrać metryk.</td></tr>}
            {data && (Object.keys(labels) as Array<keyof SystemHealth>).map(key => (
              <tr key={key}>
                <th className="w-64 bg-slate-800 px-3 py-2 text-left font-medium text-slate-300">
                  {labels[key]}
                </th>
                <td className="px-3 py-2 font-mono text-xs text-slate-100">
                  {formatValue(key, data[key])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
