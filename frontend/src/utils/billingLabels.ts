import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

/**
 * Hardcoded fallback mapping used when the API has no data yet or a code is missing.
 * Official labels are fetched from the backend (which mirrors Allegro's /billing/billing-types).
 */
const FALLBACK_LABELS: Record<string, string> = {
  // Prowizje od sprzedaży
  SUC: 'Prowizja od sprzedaży',
  FSF: 'Prowizja od oferty wyróżnionej',

  // Koszt ADS
  CPF: 'Opłata za monety',

  // Dodatkowe koszty per-oferta
  FEA: 'Dopłata Smart (wysyłka)',
  BRG: 'Opłata za wyróżnienie',
  DPM: 'Dodatkowe oznaczenie',
  INS: 'Allegro Protect',
  MPS: 'Dopłata lokalna',
  ABO: 'Abonament',
  CMP: 'Udział w kampanii',
  LAB: 'Dodatkowa etykieta',

  // Opłaty konto-level
  HB4: 'Dopłata Smart (konto)',
  HB1: 'Dopłata Smart (konto)',
  HB2: 'Dopłata Smart (konto)',
  HB8: 'Dopłata Smart (konto)',
  DPB: 'Opłata za dostawę (Smart)',
  DXP: 'Opłata za dostawę (Smart)',
  DHR: 'Opłata dodatkowa za dostawę DHL',
  DPA: 'Opłata za dostawę (Smart)',
  HB9: 'Opłata za dostawę Packeta',
  XOR: 'Opłata dodatkowa za dostawę One Kurier Allegro Delivery',
  HLB: 'Opłata za wyróżnienie (pakiet)',
  HXO: 'Opłata za wyróżnienie (pakiet)',
  ORB: 'Pozycjonowanie organiczne',
  NSP: 'Opłata abonamentowa',
  SB1: 'Abonament Smart',

  // Wyrównania (positive)
  PS1: 'Wyrównanie Allegro Ceny',
  PSA: 'Wyrównanie Allegro Ceny',
  CB2: 'Korekta',

  // Zwroty prowizji (positive)
  REF: 'Zwrot prowizji',
  RCP: 'Zwrot opłaty za monety',

  // Fulfillment
  SHIPMENT_SURCHARGE: 'Dopłata do wysyłki (Fulfillment)',
}

/** Fetch official type→label map from backend (populated from Allegro API). */
async function fetchBillingLabels(): Promise<Record<string, string>> {
  const resp = await api.get<Record<string, string>>('/billing/types')
  return resp.data
}

/**
 * React hook — returns a stable `getLabel(code)` function.
 * Uses API labels when available, falls back to FALLBACK_LABELS, then the raw code.
 */
export function useBillingLabels(): (code: string) => string {
  const { data: apiLabels = {} } = useQuery({
    queryKey: ['billing-types'],
    queryFn: fetchBillingLabels,
    staleTime: 24 * 60 * 60 * 1000, // 24h — refreshed server-side weekly
  })

  return (code: string) =>
    apiLabels[code] ?? FALLBACK_LABELS[code] ?? code
}

/**
 * Synchronous fallback — use when not inside a React component.
 * Falls back to hardcoded map only (no API data available in this path).
 */
export function getBillingLabel(code: string): string {
  return FALLBACK_LABELS[code] ?? code
}

export default FALLBACK_LABELS
