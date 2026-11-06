import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ExternalLink, Loader2, ShieldCheck } from 'lucide-react'
import { securityApi } from '../api/client'

function Badge({ tone, children }: { tone: 'green' | 'slate'; children: ReactNode }) {
  const classes = {
    green: 'border-emerald-200 bg-emerald-50 text-finance-green',
    slate: 'border-slate-200 bg-slate-50 text-slate-600',
  }
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${classes[tone]}`}>
      {children}
    </span>
  )
}

function FieldRow({ label, value, href }: { label: string; value: string; href?: string }) {
  return (
    <tr className="border-b border-slate-200 last:border-0">
      <th className="w-48 px-3 py-2 text-left text-xs font-medium text-slate-500">{label}</th>
      <td className="px-3 py-2 text-sm text-slate-700">
        {href ? (
          <a href={href} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-finance-blue hover:text-finance-blue">
            <span className="break-all">{value}</span>
            <ExternalLink size={13} />
          </a>
        ) : (
          <span className="break-all font-mono text-xs">{value}</span>
        )}
      </td>
    </tr>
  )
}

export default function CryptoProof() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['security', 'crypto-proof'],
    queryFn: securityApi.cryptoProof,
  })

  if (isLoading) {
    return <p className="flex items-center gap-2 text-sm text-slate-400"><Loader2 size={16} className="animate-spin" />Ładowanie danych weryfikacyjnych...</p>
  }

  if (error || !data) {
    return <p className="text-sm text-red-300">Nie udało się pobrać danych weryfikacyjnych modułu crypto.</p>
  }

  const params = data.verifiable.argon2idParams

  return (
    <div className="space-y-5">
      <section className="apos-panel overflow-hidden">
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
          <ShieldCheck size={17} className="text-finance-green" />
          <h2 className="font-semibold text-slate-950">Jak chronimy koszty zakupu</h2>
          <Badge tone="green">Jawne informacje</Badge>
        </div>
        <p className="px-4 pt-4 text-sm leading-6 text-slate-600">
          To są publiczne informacje o sposobie szyfrowania. Dzięki nim możesz sprawdzić,
          jakim plikiem szyfrujemy dane i skąd pochodzi ten plik.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[42rem] border-collapse">
            <tbody>
              <FieldRow label="Wersja szyfrowania" value={data.verifiable.cryptoVersion} />
              <FieldRow label="Kod źródłowy" value={data.verifiable.sourceRepo} href={data.verifiable.sourceRepo} />
              <FieldRow label="Dokładna wersja kodu" value={data.verifiable.sourceCommit} />
              <FieldRow label="Publiczny release" value={data.verifiable.releaseUrl} href={data.verifiable.releaseUrl} />
              <FieldRow label="Szyfrowanie" value={data.verifiable.algorithm} />
              <FieldRow label="Wyprowadzenie klucza z hasła" value={data.verifiable.kdf} />
              <FieldRow label="Ustawienia Argon2id" value={`memoryCost=${params.memoryCost}, timeCost=${params.timeCost}, parallelism=${params.parallelism}`} />
              <FieldRow label="Odcisk pliku szyfrującego" value={data.verifiable.bundleSha256} />
              <FieldRow label="Kontrola ładowania w przeglądarce" value={data.verifiable.bundleSri} />
              <FieldRow label="Plik używany przez panel" value={data.verifiable.bundleUrl} />
              <FieldRow label="Narzędzie offline" value={data.verifiable.decryptToolUrl} href={data.verifiable.decryptToolUrl} />
              <FieldRow label="Odcisk narzędzia offline" value={data.verifiable.decryptToolSha256} />
            </tbody>
          </table>
        </div>
      </section>

      <section className="apos-panel p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">Nasza deklaracja</h2>
          <Badge tone="slate">Oświadczenie</Badge>
        </div>
        <p className="text-sm leading-6 text-slate-600">{data.operatorStatement.text}</p>
        <p className="mt-2 text-xs text-slate-500">
          To jest deklaracja, a nie techniczny dowód. {data.operatorStatement.note}
        </p>
      </section>
    </div>
  )
}
