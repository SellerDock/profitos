export interface AnalyticsConfig {
  ga_id: string | null
  ahrefs_key: string | null
}

export function loadAnalytics(config?: AnalyticsConfig | null): void {
  if (config?.ga_id && !document.getElementById('analytics-gtag')) {
    const script = document.createElement('script')
    script.id = 'analytics-gtag'
    script.async = true
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(config.ga_id)}`
    document.head.appendChild(script)
    window.dataLayer = window.dataLayer || []
    window.gtag = function () { window.dataLayer!.push(arguments) }
    window.gtag('js', new Date())
    window.gtag('config', config.ga_id)
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
