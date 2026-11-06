import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Building2, Search, Trash2, Link2, CheckCircle2, AlertCircle } from 'lucide-react'
import { accountsApi, appSettingsApi, authApi, billingApi, buildApiUrl, devicesApi, type BillingProfile, type TotpSetupResponse } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useDeploymentMode } from '../context/DeploymentContext'
import { productName } from '../config/brand'

function formatExpiry(isoDate: string | null): string {
  if (!isoDate) return ''
  const d = new Date(isoDate)
  return d.toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })
}

function formatLastUsed(isoDate: string | null): string {
  if (!isoDate) return 'Nigdy nieużywane'
  const d = new Date(isoDate)
  return d.toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })
}

export default function Settings() {
  const queryClient = useQueryClient()
  const mode = useDeploymentMode()
  const { user, enrollTotp, refresh } = useAuth()
  const [totpSetup, setTotpSetup] = useState<TotpSetupResponse | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [totpPassword, setTotpPassword] = useState('')
  const [totpMessage, setTotpMessage] = useState('')
  const [totpError, setTotpError] = useState('')
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState<'accounts' | 'billing' | 'preferences' | 'security'>(() => searchParams.get('tab') === 'billing' ? 'billing' : 'accounts')
  const connectedId = searchParams.get('connected')
  const allegroError = searchParams.get('allegro_error')
  const allegroErrorDescription = searchParams.get('allegro_error_description')

  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
  })
  const { data: appSettings = { is_vat_payer: false } } = useQuery({
    queryKey: ['app-settings'],
    queryFn: appSettingsApi.get,
  })

  const appSettingsMutation = useMutation({
    mutationFn: appSettingsApi.update,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['app-settings'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: accountsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['accounts'] }),
  })

  const startTotpSetup = async () => {
    setTotpMessage('')
    setTotpError('')
    setTotpCode('')
    try {
      setTotpSetup(await authApi.setupTotp())
    } catch {
      setTotpError('Nie udało się rozpocząć konfiguracji 2FA.')
    }
  }

  const confirmTotpSetup = async () => {
    setTotpMessage('')
    setTotpError('')
    try {
      await enrollTotp(totpCode)
      await refresh()
      setTotpSetup(null)
      setTotpCode('')
      setTotpMessage('2FA zostało włączone.')
    } catch {
      setTotpError('Kod 2FA jest nieprawidłowy albo wygasł.')
    }
  }

  const disableTotp = async () => {
    setTotpMessage('')
    setTotpError('')
    try {
      await authApi.disableTotp({ password: totpPassword })
      await refresh()
      setTotpPassword('')
      setTotpMessage('2FA zostało wyłączone.')
    } catch {
      setTotpError('Nie udało się wyłączyć 2FA. Sprawdź hasło.')
    }
  }

  const dismissConnected = () => {
    searchParams.delete('connected')
    setSearchParams(searchParams)
  }

  const dismissAllegroError = () => {
    searchParams.delete('allegro_error')
    searchParams.delete('allegro_error_description')
    setSearchParams(searchParams)
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Konfiguracja</p>
        <h2 className="mt-1 text-2xl font-bold text-slate-950">Ustawienia</h2>
      </div>

      {connectedId && (
        <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} />
            Konto zostało pomyślnie połączone z Allegro.
          </div>
          <button onClick={dismissConnected} className="text-emerald-700 hover:text-emerald-950">✕</button>
        </div>
      )}

      {allegroError && (
        <div className="flex items-start justify-between gap-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <div className="flex gap-2">
            <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
            <div>
              <p className="font-medium">Nie udało się połączyć konta Allegro.</p>
              <p className="mt-1 text-red-700">
                {allegroError === 'invalid_scope'
                  ? 'Allegro odrzuciło zakres uprawnień aplikacji. Sprawdź scope w ustawieniach aplikacji Allegro.'
                  : allegroErrorDescription || allegroError}
              </p>
            </div>
          </div>
          <button onClick={dismissAllegroError} className="text-red-700 hover:text-red-950">✕</button>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {([
          ['accounts', 'Konta Allegro'],
          ['billing', 'Dane do faktury'],
          ['preferences', 'Ustawienia'],
          ['security', 'Bezpieczeństwo'],
        ] as const).filter(([key]) => key !== 'billing' || mode === 'hosted').map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key)}
            className={`rounded border px-3 py-2 text-sm font-medium ${
              activeTab === key
                ? 'border-slate-950 bg-slate-950 text-white'
                : 'border-slate-200 bg-white text-slate-600 hover:border-slate-400'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'preferences' && <section className="apos-panel p-5">
        <h3 className="mb-2 font-semibold text-slate-950">Ustawienia rozliczeń</h3>
        <p className="mb-4 text-sm leading-6 text-slate-600">
          Gdy ta opcja jest włączona, panel marży pokazuje kwoty netto, a po najechaniu na wartość zobaczysz jej brutto.
        </p>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={appSettings.is_vat_payer}
            onChange={e => appSettingsMutation.mutate({ is_vat_payer: e.target.checked })}
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-finance-blue focus:ring-finance-blue"
          />
          <div>
            <p className="text-sm font-medium text-slate-950">Jestem VATowcem</p>
            <p className="mt-0.5 text-xs text-slate-500">
              Sprzedaż i koszty Allegro liczymy netto. Koszt towaru już pozostaje netto tak jak teraz.
            </p>
          </div>
        </label>
      </section>}

      {mode === 'hosted' && activeTab === 'billing' && <BillingProfileSection />}

      {activeTab === 'security' && <section className="apos-panel p-5">
        <h3 className="mb-2 font-semibold text-slate-950">Uwierzytelnianie 2FA</h3>
        <p className="mb-4 text-sm leading-6 text-slate-600">
          Zabezpiecz konto dodatkowym kodem z aplikacji uwierzytelniającej. To chroni dostęp nawet wtedy,
          gdy samo hasło trafi w niepowołane ręce.
        </p>
        {user?.is_operator ? (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            2FA jest wymagane dla administratora i nie można go wyłączyć w panelu.
          </div>
        ) : user?.totp_enrolled ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
              2FA jest włączone dla tego konta.
            </div>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">Hasło do konta</span>
              <input
                type="password"
                value={totpPassword}
                onChange={event => setTotpPassword(event.target.value)}
                className="apos-control w-full"
                placeholder="Potwierdź hasłem, aby wyłączyć 2FA"
              />
            </label>
            <button
              type="button"
              onClick={() => void disableTotp()}
              disabled={totpPassword.length < 8}
              className="apos-button"
            >
              Wyłącz 2FA
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {!totpSetup && (
              <button type="button" onClick={() => void startTotpSetup()} className="apos-button-primary">
                Włącz 2FA
              </button>
            )}
            {totpSetup && (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm font-medium text-slate-950">Zeskanuj QR i wpisz kod</p>
                <div
                  className="mt-3 inline-block rounded bg-white p-3"
                  dangerouslySetInnerHTML={{ __html: totpSetup.qr_svg }}
                />
                <p className="mt-3 break-all rounded bg-white p-2 font-mono text-xs text-slate-700">
                  {totpSetup.secret}
                </p>
                <label className="mt-3 block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">Kod 2FA</span>
                  <input
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    value={totpCode}
                    onChange={event => setTotpCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                    className="apos-control w-full"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void confirmTotpSetup()}
                  disabled={totpCode.length !== 6}
                  className="apos-button-primary mt-3"
                >
                  Potwierdź i włącz 2FA
                </button>
              </div>
            )}
          </div>
        )}
        {totpMessage && <p className="mt-3 text-sm text-emerald-700">{totpMessage}</p>}
        {totpError && <p className="mt-3 text-sm text-red-500">{totpError}</p>}
      </section>}

      {activeTab === 'security' && <DeviceSessionsSection />}

      {activeTab === 'accounts' && <section className="apos-panel p-5">
        <h3 className="mb-4 flex items-center gap-2 font-semibold text-slate-950">
          <Link2 size={16} /> Dodaj konto Allegro
        </h3>
        <p className="mb-4 text-sm leading-6 text-slate-600">
          Po kliknięciu otworzy się Allegro, gdzie zalogujesz się i potwierdzisz dostęp {productName()} do konta.
        </p>
        <a href={buildApiUrl('/allegro/auth')} className="apos-button-primary w-full justify-center">
          <Link2 size={14} />
          Przejdź do Allegro
        </a>
      </section>}

      {activeTab === 'accounts' && <section className="apos-panel p-5">
        <h3 className="mb-4 font-semibold text-slate-950">Konta Allegro</h3>
        {isLoading ? (
          <p className="text-slate-400 text-sm">Ładowanie...</p>
        ) : accounts.length === 0 ? (
          <p className="text-slate-500 text-sm">Brak dodanych kont.</p>
        ) : (
          <ul className="space-y-3">
            {accounts.map(account => (
              <li
                key={account.id}
                className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: account.color }}
                    />
                    <div>
                      <p className="text-sm font-medium text-slate-950">{account.name}</p>
                      <p className="text-slate-400 text-xs">Konto Allegro</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {account.is_connected ? (
                      <span className="flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                        <CheckCircle2 size={11} />
                        Połączone
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-500">
                        <AlertCircle size={11} />
                        Nie połączone
                      </span>
                    )}
                    <a
                      href={buildApiUrl(`/allegro/auth/${account.id}`)}
                      className="flex items-center gap-1 text-xs bg-orange-600 hover:bg-orange-500 text-white rounded-full px-3 py-1 transition-colors whitespace-nowrap"
                    >
                      <Link2 size={11} />
                      {account.is_connected ? 'Odnów' : 'Połącz z Allegro'}
                    </a>
                    <button
                      onClick={() => deleteMutation.mutate(account.id)}
                      className="text-slate-500 hover:text-red-400 transition-colors ml-1"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
                {account.is_connected && account.token_expires_at && (
                  <p className="text-xs text-slate-500 mt-1.5 pl-6">
                    Token ważny do: {formatExpiry(account.token_expires_at)}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>}
    </div>
  )
}

const emptyProfile: BillingProfile = {
  company_name: '',
  nip: '',
  regon: '',
  krs: '',
  street: '',
  postal_code: '',
  city: '',
  country: 'PL',
  invoice_email: '',
  vat_status: '',
}

function BillingProfileSection() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<BillingProfile>(emptyProfile)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['billing-profile'],
    queryFn: billingApi.profile,
  })

  useEffect(() => {
    if (data) {
      setForm({
        ...emptyProfile,
        ...data,
        company_name: data.company_name ?? '',
        nip: data.nip ?? '',
        regon: data.regon ?? '',
        krs: data.krs ?? '',
        street: data.street ?? '',
        postal_code: data.postal_code ?? '',
        city: data.city ?? '',
        country: data.country || 'PL',
        invoice_email: data.invoice_email ?? '',
        vat_status: data.vat_status ?? '',
      })
    }
  }, [data])

  const saveMutation = useMutation({
    mutationFn: billingApi.updateProfile,
    onSuccess: data => {
      setMessage('Dane do faktury zostały zapisane.')
      setError('')
      queryClient.setQueryData(['billing-profile'], data)
    },
    onError: () => {
      setMessage('')
      setError('Nie udało się zapisać danych do faktury.')
    },
  })

  const lookupMutation = useMutation({
    mutationFn: billingApi.vatLookup,
    onSuccess: data => {
      setForm(prev => ({ ...prev, ...data, invoice_email: prev.invoice_email }))
      setMessage('Pobrano dane z wykazu VAT. Sprawdź je przed zapisem.')
      setError('')
    },
    onError: () => {
      setMessage('')
      setError('Nie udało się pobrać danych dla tego NIP.')
    },
  })

  const update = (field: keyof BillingProfile, value: string) => {
    setMessage('')
    setError('')
    setForm(prev => ({ ...prev, [field]: value }))
  }

  return (
    <section className="apos-panel p-5">
      <h3 className="mb-2 flex items-center gap-2 font-semibold text-slate-950">
        <Building2 size={16} />
        Dane do faktury
      </h3>
      <p className="mb-5 text-sm leading-6 text-slate-600">
        Uzupełnij dane firmy. Po wpisaniu NIP możesz pobrać dane z publicznego wykazu VAT i poprawić je przed zapisem.
      </p>

      {isLoading ? (
        <p className="text-sm text-slate-500">Ładowanie...</p>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[1fr_auto]">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">NIP</span>
              <input
                value={form.nip ?? ''}
                onChange={event => update('nip', event.target.value)}
                className="apos-control w-full"
                placeholder="1234567890"
              />
            </label>
            <button
              type="button"
              disabled={!form.nip || lookupMutation.isPending}
              onClick={() => lookupMutation.mutate(String(form.nip))}
              className="apos-button-primary self-end"
            >
              <Search size={14} />
              Pobierz dane
            </button>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Nazwa firmy" value={form.company_name ?? ''} onChange={value => update('company_name', value)} />
            <Field label="Email do faktur" value={form.invoice_email ?? ''} onChange={value => update('invoice_email', value)} />
            <Field label="REGON" value={form.regon ?? ''} onChange={value => update('regon', value)} />
            <Field label="KRS" value={form.krs ?? ''} onChange={value => update('krs', value)} />
            <Field label="Ulica i numer" value={form.street ?? ''} onChange={value => update('street', value)} />
            <Field label="Kod pocztowy" value={form.postal_code ?? ''} onChange={value => update('postal_code', value)} />
            <Field label="Miasto" value={form.city ?? ''} onChange={value => update('city', value)} />
            <Field label="Kraj" value={form.country ?? 'PL'} onChange={value => update('country', value)} />
          </div>

          {form.vat_status && (
            <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              Status VAT z wykazu: <span className="font-semibold text-slate-950">{form.vat_status}</span>
            </p>
          )}
          {message && <p className="text-sm text-emerald-700">{message}</p>}
          {error && <p className="text-sm text-red-500">{error}</p>}
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => saveMutation.mutate(form)}
              disabled={saveMutation.isPending}
              className="apos-button-primary"
            >
              Zapisz dane
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <input value={value} onChange={event => onChange(event.target.value)} className="apos-control w-full" />
    </label>
  )
}

function DeviceSessionsSection() {
  const queryClient = useQueryClient()
  const { data: devices = [], isLoading, isError } = useQuery({
    queryKey: ['devices'],
    queryFn: devicesApi.list,
  })
  const revokeMutation = useMutation({
    mutationFn: devicesApi.revoke,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['devices'] }),
  })

  return (
    <section className="apos-panel p-5">
      <h3 className="mb-2 font-semibold text-slate-950">Zaufane urządzenia</h3>
      <p className="mb-4 text-sm leading-6 text-slate-600">
        To urządzenia z zapamiętanym logowaniem, np. aplikacja mobilna. Wylogowanie urządzenia
        z tego miejsca wymaga na nim ponownego pełnego logowania (hasło i 2FA).
      </p>
      {isLoading ? (
        <p className="text-sm text-slate-400">Ładowanie...</p>
      ) : isError ? (
        <p className="text-sm text-red-500">Nie udało się wczytać listy urządzeń.</p>
      ) : devices.length === 0 ? (
        <p className="text-sm text-slate-500">Brak zapamiętanych urządzeń.</p>
      ) : (
        <ul className="space-y-3">
          {devices.map(device => (
            <li key={device.id} className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-950">
                    {device.device_label || 'Nieznane urządzenie'}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {device.app_version && <>Wersja {device.app_version} · </>}
                    Ostatnio użyte: {formatLastUsed(device.last_used_at)}
                    {device.ip_created && <> · IP: {device.ip_created}</>}
                  </p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {device.status === 'active' ? (
                    <span className="flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                      <CheckCircle2 size={11} />
                      Aktywne
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-500">
                      <AlertCircle size={11} />
                      Wylogowane
                    </span>
                  )}
                  {device.status === 'active' && (
                    <button
                      type="button"
                      onClick={() => revokeMutation.mutate(device.id)}
                      disabled={revokeMutation.isPending && revokeMutation.variables === device.id}
                      className="text-xs text-red-500 hover:text-red-700 transition-colors whitespace-nowrap"
                    >
                      Wyloguj to urządzenie
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
