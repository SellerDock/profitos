import { useState } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, RotateCw, ShieldCheck } from 'lucide-react'
import type { CryptoProof } from '../api/client'
import { supportEmail } from '../config/brand'

type VerifyState = 'idle' | 'running' | 'ok' | 'mismatch' | 'error'

function hashBytesToHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes))
    .map(byte => byte.toString(16).padStart(2, '0'))
    .join('')
}

function Badge({ tone, children }: { tone: 'green' | 'red' | 'slate'; children: ReactNode }) {
  const classes = {
    green: 'border-emerald-200 bg-emerald-50 text-finance-green',
    red: 'border-red-200 bg-red-50 text-finance-red',
    slate: 'border-slate-200 bg-slate-50 text-slate-600',
  }
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${classes[tone]}`}>
      {children}
    </span>
  )
}

function HashLine({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-slate-500">{label}</p>
      <p className="apos-code-block break-all">
        {value || '—'}
      </p>
    </div>
  )
}

export function VerifyBundleHash() {
  const [state, setState] = useState<VerifyState>('idle')
  const [computedHash, setComputedHash] = useState<string | null>(null)
  const [expectedHash, setExpectedHash] = useState<string | null>(null)
  const [releaseUrl, setReleaseUrl] = useState<string | null>(null)

  async function verify() {
    setState('running')
    setComputedHash(null)
    try {
      const proofResponse = await fetch('/api/v1/security/crypto-proof', { cache: 'no-store' })
      if (!proofResponse.ok) throw new Error(`crypto-proof failed: ${proofResponse.status}`)
      const proof = await proofResponse.json() as CryptoProof
      const expected = proof.verifiable.bundleSha256.trim().toLowerCase()
      const url = proof.verifiable.bundleUrl
      setExpectedHash(expected)
      setReleaseUrl(proof.verifiable.releaseUrl)

      const bundle = await fetch(url, { cache: 'reload' })
      if (!bundle.ok) throw new Error(`bundle download failed: ${bundle.status}`)
      const buf = await bundle.arrayBuffer()
      const hashBuf = await crypto.subtle.digest('SHA-256', buf)
      const hex = hashBytesToHex(hashBuf)
      setComputedHash(hex)
      setState(hex === expected ? 'ok' : 'mismatch')
    } catch (error) {
      console.error('Bundle hash verification failed', error)
      setState('error')
    }
  }

  return (
    <section className="apos-panel p-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <ShieldCheck size={18} className="text-finance-green" />
            <h2 className="text-lg font-semibold text-slate-950">Sprawdź plik szyfrujący</h2>
            <Badge tone="green">Można sprawdzić</Badge>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-slate-600">
            Po kliknięciu przeglądarka sprawdzi, czy plik odpowiedzialny za szyfrowanie jest taki
            sam jak wersja opublikowana na GitHubie. Hasło sejfu ani dane finansowe nie są do tego
            potrzebne.
          </p>
        </div>
        <button
          type="button"
          onClick={verify}
          disabled={state === 'running'}
          className="apos-button-primary"
        >
          {state === 'running' ? <Loader2 size={16} className="animate-spin" /> : <RotateCw size={16} />}
          Sprawdź teraz
        </button>
      </div>

      {state === 'idle' && (
        <p className="rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          Kliknij przycisk. Wynik pojawi się tutaj.
        </p>
      )}

      {state === 'running' && (
        <div className="flex items-center gap-3 rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          <Loader2 size={16} className="animate-spin text-finance-green" />
          Sprawdzanie pliku...
        </div>
      )}

      {state === 'ok' && (
        <div className="space-y-4 rounded border border-emerald-200 bg-emerald-50 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <CheckCircle2 size={18} className="text-finance-green" />
            <Badge tone="green">Hash zgodny</Badge>
            <p className="text-sm text-finance-green">
              Plik jest zgodny z publiczną wersją na GitHubie.
            </p>
          </div>
          <HashLine label="Policzony w tej przeglądarce" value={computedHash} />
          {releaseUrl && (
            <a href={releaseUrl} target="_blank" rel="noopener" className="text-sm text-finance-green underline underline-offset-4 hover:text-finance-green">
              Otwórz GitHub Release
            </a>
          )}
        </div>
      )}

      {state === 'mismatch' && (
        <div className="space-y-4 rounded border border-red-200 bg-red-50 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <AlertTriangle size={18} className="text-finance-red" />
            <Badge tone="red">Niezgodność</Badge>
            {supportEmail() && <p className="text-sm text-finance-red">Skontaktuj się z {supportEmail()} przed wpisaniem hasła sejfu.</p>}
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <HashLine label="Policzony hash" value={computedHash} />
            <HashLine label="Oczekiwany hash" value={expectedHash} />
          </div>
        </div>
      )}

      {state === 'error' && (
        <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          <Badge tone="slate">Nie udało się zweryfikować</Badge>
          <p className="mt-2">Spróbuj ponownie po odświeżeniu strony.</p>
        </div>
      )}
    </section>
  )
}
