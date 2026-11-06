import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, Copy, ExternalLink, Loader2, Terminal } from 'lucide-react'
import { securityApi } from '../api/client'

type TabKey = 'unix' | 'powershell' | 'attestation'

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600">
      {children}
    </span>
  )
}

function repoOwner(repoUrl: string): string {
  try {
    const url = new URL(repoUrl)
    return url.pathname.split('/').filter(Boolean)[0] || 'rise-co-pl'
  } catch {
    return 'rise-co-pl'
  }
}

function versionTag(version: string): string {
  return version.startsWith('v') ? version : `v${version}`
}

function CopyLine({ line, id }: { line: string; id: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(line)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="apos-code-row">
      <code className="overflow-x-auto whitespace-pre px-3 py-2 font-mono text-xs">{line}</code>
      <button
        type="button"
        onClick={copy}
        aria-label={`Kopiuj linię ${id}`}
        className="apos-copy-button"
      >
        {copied ? <Check size={14} className="text-emerald-300" /> : <Copy size={14} />}
        {copied ? 'Skopiowano' : 'Kopiuj'}
      </button>
    </div>
  )
}

function SnippetBlock({ lines, prefix }: { lines: string[]; prefix: string }) {
  return (
    <div className="apos-code-shell">
      {lines.map((line, index) => (
        <CopyLine key={`${prefix}-${index}`} id={`${prefix}-${index + 1}`} line={line} />
      ))}
    </div>
  )
}

export function CliVerificationSnippets() {
  const [active, setActive] = useState<TabKey>('unix')
  const { data, isLoading, error } = useQuery({
    queryKey: ['security', 'crypto-proof'],
    queryFn: securityApi.cryptoProof,
  })

  const snippets = useMemo(() => {
    if (!data) return null
    const tag = versionTag(data.verifiable.cryptoVersion)
    const repo = data.verifiable.sourceRepo.replace(/\/$/, '')
    const assetBase = `${repo}/releases/download/${tag}`
    const owner = repoOwner(repo)
    return {
      unix: [
        `curl -fsSLO ${assetBase}/profitos-crypto.iife.js`,
        `curl -fsSLO ${assetBase}/profitos-crypto.iife.js.sha256`,
        'sha256sum -c profitos-crypto.iife.js.sha256',
      ],
      powershell: [
        `iwr ${assetBase}/profitos-crypto.iife.js -OutFile profitos-crypto.iife.js`,
        `$expected = "${data.verifiable.bundleSha256}"`,
        '$actual = (Get-FileHash profitos-crypto.iife.js -Algorithm SHA256).Hash.ToLower()',
        'if ($actual -eq $expected) { "OK" } else { "MISMATCH: $actual vs $expected" }',
      ],
      attestation: [
        `gh attestation verify profitos-crypto.iife.js --owner ${owner}`,
      ],
    }
  }, [data])

  return (
    <section className="apos-panel p-5">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Terminal size={18} className="text-slate-500" />
        <h2 className="text-lg font-semibold text-slate-950">Dla osób technicznych</h2>
        <Badge>Opcjonalnie</Badge>
      </div>
      <p className="mb-4 max-w-3xl text-sm leading-6 text-slate-600">
        Jeśli chcesz sprawdzić plik bez używania panelu, możesz pobrać go z GitHuba i porównać
        odcisk SHA-256 na własnym komputerze. Te komendy nie wymagają hasła sejfu.
      </p>

      {isLoading && (
        <p className="flex items-center gap-2 text-sm text-slate-400">
          <Loader2 size={16} className="animate-spin" /> Ładowanie poleceń...
        </p>
      )}
      {error && <p className="text-sm text-red-300">Nie udało się pobrać danych do snippetów.</p>}
      {snippets && (
        <>
          <div className="mb-3 flex flex-wrap gap-2">
            {[
              ['unix', 'macOS / Linux'],
              ['powershell', 'Windows PowerShell'],
              ['attestation', 'GitHub attestation'],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setActive(key as TabKey)}
                className={`rounded border px-3 py-1.5 text-sm ${
                  active === key
                    ? 'border-finance-blue bg-blue-50 text-finance-blue'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-slate-400'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <SnippetBlock lines={snippets[active]} prefix={active} />
          {active === 'attestation' && (
            <a
              href="https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds"
              target="_blank"
              rel="noopener"
              className="mt-3 inline-flex items-center gap-1 text-sm text-finance-blue hover:text-finance-blue"
            >
              Dokumentacja potwierdzania plików na GitHubie
              <ExternalLink size={13} />
            </a>
          )}
        </>
      )}
    </section>
  )
}
