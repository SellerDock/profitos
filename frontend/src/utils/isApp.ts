const APP_UA_MARKER = 'pl.profitos.app'
const APP_UA_VERSION_PATTERN = /pl\.profitos\.app\/(\S+)/

const userAgent = typeof navigator !== 'undefined' ? navigator.userAgent : ''

export const IS_APP = userAgent.includes(APP_UA_MARKER)

const appVersionMatch = userAgent.match(APP_UA_VERSION_PATTERN)
export const APP_VERSION: string | null = appVersionMatch ? appVersionMatch[1] : null
