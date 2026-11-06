import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Check, Copy, Download, FileCode2, Loader2 } from 'lucide-react'
import { productsApi, securityApi, type EncryptedCostExport } from '../api/client'

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

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-medium text-finance-blue">
      {children}
    </span>
  )
}

function CopyButton({ value, label = 'Kopiuj' }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 hover:border-slate-400 hover:bg-slate-50"
    >
      {copied ? <Check size={13} className="text-emerald-300" /> : <Copy size={13} />}
      {copied ? 'Skopiowano' : label}
    </button>
  )
}

function Step({
  number,
  title,
  children,
}: {
  number: number
  title: string
  children: ReactNode
}) {
  return (
    <div className="relative border-l-2 border-blue-500/50 pl-5">
      <div className="absolute -left-[13px] top-0 flex h-6 w-6 items-center justify-center rounded-full border border-blue-300 bg-blue-50 text-xs font-semibold text-finance-blue">
        {number}
      </div>
      <div className="min-w-0">
        <h3 className="mb-2 text-base font-semibold text-slate-950">{title}</h3>
        {children}
      </div>
    </div>
  )
}

export function OfflineDecryptWalkthrough() {
  const [selectedId, setSelectedId] = useState('')
  const { data: proof } = useQuery({
    queryKey: ['security', 'crypto-proof'],
    queryFn: securityApi.cryptoProof,
  })
  const { data: products = [], isLoading: productsLoading } = useQuery({
    queryKey: ['products'],
    queryFn: productsApi.list,
  })

  const exportable = useMemo(() => products.filter(product => product.encrypted_cost), [products])
  const decryptUrl = proof?.verifiable.decryptToolUrl || '#'
  const decryptHash = proof?.verifiable.decryptToolSha256 || ''
  const hashSnippet = decryptUrl !== '#'
    ? `curl -fsSLO ${decryptUrl}\necho "${decryptHash}  decrypt.html" | sha256sum -c -`
    : 'sha256sum decrypt.html'

  const mutation = useMutation({
    mutationFn: (id: number) => securityApi.encryptedCostExport(id),
    onSuccess: downloadJson,
  })

  const submit = () => {
    const id = Number(selectedId)
    if (Number.isFinite(id) && id > 0) mutation.mutate(id)
  }

  return (
    <section className="apos-panel p-5">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <FileCode2 size={18} className="text-finance-blue" />
        <h2 className="text-lg font-semibold text-slate-950">Sprawdź własny zaszyfrowany koszt</h2>
        <Badge>Opcjonalnie</Badge>
      </div>
      <p className="mb-6 max-w-3xl text-sm leading-6 text-slate-600">
        Możesz pobrać zaszyfrowany koszt jednego SKU i odszyfrować go lokalnie. To prosty test,
        że w bazie trzymamy zaszyfrowany zapis, a jawna kwota pojawia się dopiero po użyciu hasła
        sejfu.
      </p>

      <div className="mb-6 h-1 overflow-hidden rounded bg-slate-700">
        <div className="h-full w-full bg-finance-blue" />
      </div>

      <div className="space-y-7">
        <Step
          number={1}
          title="Pobierz narzędzie offline"
        >
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={decryptUrl}
              target="_blank"
              rel="noopener"
              className="apos-button-primary"
            >
              <Download size={15} />
              Pobierz decrypt.html
            </a>
            {decryptHash && <CopyButton value={decryptHash} label="Kopiuj SHA-256" />}
          </div>
          <p className="mt-2 break-all font-mono text-xs text-slate-500">SHA-256: {decryptHash || 'ładowanie...'}</p>
        </Step>

        <Step
          number={2}
          title="Sprawdź, czy plik jest właściwy"
        >
          <p className="mb-2 text-sm text-slate-600">To opcjonalny test przed wpisaniem hasła sejfu.</p>
          <div className="apos-code-block overflow-x-auto p-3">
            <pre className="whitespace-pre font-mono text-xs">{hashSnippet}</pre>
          </div>
          <div className="mt-2">
            <CopyButton value={hashSnippet} label="Kopiuj polecenie" />
          </div>
        </Step>

        <Step
          number={3}
          title="Pobierz zaszyfrowany koszt SKU"
        >
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
            <label>
              <span className="mb-1 block text-xs text-slate-500">SKU z zaszyfrowanym kosztem</span>
              <select
                value={selectedId}
                onChange={event => setSelectedId(event.target.value)}
                disabled={productsLoading || exportable.length === 0}
                className="apos-control w-full"
              >
                <option value="">{productsLoading ? 'Ładowanie...' : 'Wybierz SKU'}</option>
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
              className="apos-button-primary"
            >
              {mutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
              Pobierz zaszyfrowany plik
            </button>
          </div>
          {exportable.length === 0 && !productsLoading && (
            <p className="mt-2 text-sm text-slate-500">Nie ma jeszcze SKU z zaszyfrowanym kosztem.</p>
          )}
          {mutation.isError && <p className="mt-2 text-sm text-red-600">Nie udało się pobrać pliku.</p>}
        </Step>

        <Step
          number={4}
          title="Odszyfruj lokalnie"
        >
          <p className="text-sm leading-6 text-slate-600">
            Otwórz pobrany plik `decrypt.html`, wklej zaszyfrowany koszt i wpisz hasło sejfu.
            Jeśli chcesz mieć dodatkową pewność, możesz zrobić to po odłączeniu internetu.
          </p>
        </Step>
      </div>
    </section>
  )
}
