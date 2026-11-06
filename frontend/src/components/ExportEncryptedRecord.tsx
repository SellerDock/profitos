import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, Loader2 } from 'lucide-react'
import { productsApi, securityApi, type EncryptedCostExport } from '../api/client'

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-200">
      {children}
    </span>
  )
}

function safeName(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'sku'
}

function downloadJson(data: EncryptedCostExport): void {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
  const filename = `profitos-cost-${safeName(data.sku.sku_key)}-${timestamp}.json`
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export default function ExportEncryptedRecord() {
  const [selectedId, setSelectedId] = useState('')
  const { data: products = [], isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: productsApi.list,
  })

  const exportable = useMemo(() => products.filter(product => product.encrypted_cost), [products])

  const mutation = useMutation({
    mutationFn: (id: number) => securityApi.encryptedCostExport(id),
    onSuccess: downloadJson,
  })

  const submit = () => {
    const id = Number(selectedId)
    if (Number.isFinite(id) && id > 0) mutation.mutate(id)
  }

  return (
    <section className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-white">Eksport zaszyfrowanego rekordu</h2>
        <Badge>Weryfikowalne</Badge>
      </div>
      <div className="flex flex-col gap-3 md:flex-row md:items-end">
        <label className="flex-1">
          <span className="mb-1 block text-xs text-slate-400">SKU z zaszyfrowanym kosztem</span>
          <select
            value={selectedId}
            onChange={e => setSelectedId(e.target.value)}
            disabled={isLoading || exportable.length === 0}
            className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
          >
            <option value="">{isLoading ? 'Ładowanie...' : 'Wybierz SKU'}</option>
            {exportable.map(product => (
              <option key={product.id} value={product.id}>
                {product.sku_key} · {product.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={submit}
          disabled={!selectedId || mutation.isPending}
          className="inline-flex items-center justify-center gap-2 rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
          Pobierz zaszyfrowany rekord (JSON)
        </button>
      </div>
      {exportable.length === 0 && !isLoading && (
        <p className="mt-3 text-sm text-slate-500">Nie ma jeszcze SKU z zaszyfrowanym kosztem.</p>
      )}
      {mutation.isError && (
        <p className="mt-3 text-sm text-red-300">Nie udało się pobrać zaszyfrowanego rekordu.</p>
      )}
    </section>
  )
}
