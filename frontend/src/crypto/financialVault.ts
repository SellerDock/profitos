import type { EncryptedValue, FinancialVaultStatus } from '../api/client'

type ProfitOSCryptoBridge = {
  CRYPTO_VERSION: 1
  ALGORITHM: 'AES-256-GCM'
  KDF: 'argon2id'
  deriveKey(
    password: string,
    salt: Uint8Array,
    params: { memoryCost: number; timeCost: number; parallelism: number },
    options?: { extractable?: boolean },
  ): Promise<CryptoKey>
  encryptCost(key: CryptoKey, plaintext: string, aad: string): Promise<{ iv: Uint8Array; ct: Uint8Array }>
  decryptCost(key: CryptoKey, iv: Uint8Array, ct: Uint8Array, aad: string): Promise<string>
  bytesToBase64(bytes: Uint8Array): string
  base64ToBytes(value: string): Uint8Array
}

declare global {
  interface Window {
    ProfitOSCrypto?: ProfitOSCryptoBridge
  }
}

export const DEFAULT_KDF = {
  memory_cost: 128 * 1024,
  time_cost: 4,
  parallelism: 1,
}

export const VAULT_VERIFIER_AAD = 'profitos:vault-verifier:v1'

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
}

function assertCryptoLoaded(): ProfitOSCryptoBridge {
  if (typeof window === 'undefined' || !window.ProfitOSCrypto) {
    throw new Error('Moduł szyfrujący nie został załadowany. Sprawdź połączenie i odśwież stronę.')
  }
  return window.ProfitOSCrypto
}

export const bytesToBase64 = (bytes: Uint8Array): string => assertCryptoLoaded().bytesToBase64(bytes)

export const base64ToBytes = (value: string): Uint8Array => assertCryptoLoaded().base64ToBytes(value)

export function randomBase64(length = 16): string {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return bytesToBase64(bytes)
}

export async function deriveFinancialKey(
  password: string,
  params: Pick<FinancialVaultStatus, 'salt' | 'memory_cost' | 'time_cost' | 'parallelism'>,
  options: { extractable?: boolean } = {},
): Promise<CryptoKey> {
  if (!params.salt || !params.memory_cost || !params.time_cost || !params.parallelism) {
    throw new Error('Vault KDF parameters are incomplete')
  }

  return assertCryptoLoaded().deriveKey(password, base64ToBytes(params.salt), {
    memoryCost: params.memory_cost,
    timeCost: params.time_cost,
    parallelism: params.parallelism,
  }, {
    extractable: Boolean(options.extractable),
  })
}

export async function exportKey(key: CryptoKey): Promise<string> {
  const raw = await crypto.subtle.exportKey('raw', key)
  return bytesToBase64(new Uint8Array(raw))
}

export async function importKey(base64: string): Promise<CryptoKey> {
  return crypto.subtle.importKey('raw', toArrayBuffer(base64ToBytes(base64)), 'AES-GCM', false, ['encrypt', 'decrypt'])
}

export function skuCostAad(skuId: number, keyVersion = 1): string {
  return `profitos:sku-cost:${skuId}:current:v${keyVersion}`
}

export function skuCostHistoryAad(skuId: number, validFrom: string, keyVersion = 1): string {
  return `profitos:sku-cost:${skuId}:history:${validFrom}:v${keyVersion}`
}

export async function encryptText(key: CryptoKey, value: string, aad: string, keyVersion = 1): Promise<EncryptedValue> {
  const encrypted = await assertCryptoLoaded().encryptCost(key, value, aad)
  return {
    ciphertext: bytesToBase64(encrypted.ct),
    nonce: bytesToBase64(encrypted.iv),
    key_version: keyVersion,
    aad_context: aad,
  }
}

export async function decryptText(key: CryptoKey, value: EncryptedValue, aad: string): Promise<string> {
  return assertCryptoLoaded().decryptCost(key, base64ToBytes(value.nonce), base64ToBytes(value.ciphertext), aad)
}

export async function encryptCost(key: CryptoKey, cost: string | number, aad: string, keyVersion = 1): Promise<EncryptedValue> {
  return encryptText(key, String(cost), aad, keyVersion)
}

export async function decryptCost(key: CryptoKey, value: EncryptedValue | null | undefined): Promise<number | null> {
  if (!value) return null
  const plaintext = await decryptText(key, value, value.aad_context)
  const parsed = Number(plaintext)
  return Number.isFinite(parsed) ? parsed : null
}

export async function createVerifier(key: CryptoKey, keyVersion = 1): Promise<EncryptedValue> {
  return encryptText(key, 'profitos-financial-vault-v1', VAULT_VERIFIER_AAD, keyVersion)
}

export async function verifyKey(key: CryptoKey, status: FinancialVaultStatus): Promise<boolean> {
  if (!status.verify_ciphertext || !status.verify_nonce) return false
  const text = await decryptText(key, {
    ciphertext: status.verify_ciphertext,
    nonce: status.verify_nonce,
    key_version: status.key_version ?? 1,
    aad_context: VAULT_VERIFIER_AAD,
  }, VAULT_VERIFIER_AAD)
  return text === 'profitos-financial-vault-v1'
}

export function computeFinancials(input: {
  revenue: number
  units: number
  // Units to price COGS against. Can differ from `units` (e.g. a "2 x" bundle
  // with a partial, sub-unit refund is still 1 unit sold but only 0.5 unit of
  // cost). Defaults to `units` when not supplied.
  costUnits?: number
  unitCost: number | null
  totalAllegro: number
  priceAdjust?: number
  campaignBonus?: number
  refundCommission?: number
  commissionRefunds?: number
}) {
  if (input.unitCost == null) {
    return { cogs: null, profit: null, marginPct: null, roiPct: null, profitPerUnit: null }
  }
  const netUnits = Math.max(input.units, 0)
  const netCostUnits = Math.max(input.costUnits ?? input.units, 0)
  const cogs = input.unitCost * netCostUnits
  const profit = input.revenue - input.totalAllegro + (input.priceAdjust ?? 0) + (input.campaignBonus ?? 0) + (input.refundCommission ?? 0) + (input.commissionRefunds ?? 0) - cogs
  return {
    cogs,
    profit,
    marginPct: input.revenue > 0 ? (profit / input.revenue) * 100 : null,
    roiPct: cogs > 0 ? (profit / cogs) * 100 : null,
    profitPerUnit: netUnits > 0 ? profit / netUnits : null,
  }
}
