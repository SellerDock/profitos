export interface BrandConfig {
  product_name: string
  support_email: string | null
  public_site_url: string | null
  app_url: string | null
}

let brand: BrandConfig | undefined

export function setBrandConfig(config?: BrandConfig): void {
  brand = config
}

export function productName(): string { return brand?.product_name ?? 'ProfitOS' }
export function supportEmail(): string | null { return brand?.support_email ?? null }
export function publicSiteUrl(): string { return (brand?.public_site_url ?? window.location.origin).replace(/\/$/, '') }
export function appUrl(path = '/'): string {
  const base = (brand?.app_url ?? window.location.origin).replace(/\/$/, '')
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}
export function isAppHost(hostname = window.location.hostname): boolean {
  return brand?.app_url ? hostname === new URL(brand.app_url).hostname : true
}
