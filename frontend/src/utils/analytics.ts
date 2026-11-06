export interface AnalyticsConfig {
  ga_id: string | null
  ahrefs_key: string | null
  ads_conversion?: string | null
}

export function loadAnalytics(config?: AnalyticsConfig | null): void {
  const tagId = config?.ga_id || config?.ads_conversion?.split('/')[0]
  if (tagId && !document.getElementById('analytics-gtag')) {
    const script = document.createElement('script')
    script.id = 'analytics-gtag'
    script.async = true
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(tagId)}`
    document.head.appendChild(script)
    window.dataLayer = window.dataLayer || []
    window.gtag = function () { window.dataLayer!.push(arguments) }
    window.gtag('js', new Date())
    window.gtag('config', tagId)
    const adsId = config?.ads_conversion?.split('/')[0]
    if (adsId && adsId !== tagId) window.gtag('config', adsId)
  }
  if (config?.ahrefs_key && !document.getElementById('analytics-ahrefs')) {
    const script = document.createElement('script')
    script.id = 'analytics-ahrefs'
    script.async = true
    script.src = 'https://analytics.ahrefs.com/analytics.js'
    script.dataset.key = config.ahrefs_key
    document.head.appendChild(script)
  }
}
