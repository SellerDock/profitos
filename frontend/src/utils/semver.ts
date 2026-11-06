const VERSION_CORE_PATTERN = /^\d+(\.\d+)*$/

// Parses the numeric core of a 2- or 3-component version, ignoring any
// pre-release/build suffix (e.g. "0.2.0-beta" -> [0, 2, 0]). Pads to
// 3 components so "0.1" == "0.1.0". Anything else (4+ components,
// non-numeric) is rejected so the caller fails silent.
function parseSemver(version: string): [number, number, number] | null {
  const core = version.trim().split(/[-+]/)[0]
  if (!VERSION_CORE_PATTERN.test(core)) return null
  const parts = core.split('.').map(Number)
  if (parts.length > 3) return null
  while (parts.length < 3) parts.push(0)
  return [parts[0], parts[1], parts[2]]
}

// Returns a positive number when a > b, negative when a < b, 0 when equal,
// or null when either version cannot be parsed.
export function compareSemver(a: string, b: string): number | null {
  const pa = parseSemver(a)
  const pb = parseSemver(b)
  if (!pa || !pb) return null
  for (let i = 0; i < 3; i++) {
    const diff = pa[i] - pb[i]
    if (diff !== 0) return diff
  }
  return 0
}

export function isNewerVersion(latest: string, current: string): boolean {
  const cmp = compareSemver(latest, current)
  return cmp !== null && cmp > 0
}
