export type ParsedCostImportRow = {
  sku: string
  cost: string
  vat?: string
  validFrom?: string
  validTo?: string
  sourceRow: number
}

export type ParsedCostImport = {
  rows: ParsedCostImportRow[]
  errors: string[]
  warnings: string[]
}

export type CostImportMappingKey = 'sku' | 'cost' | 'vat' | 'validFrom' | 'validTo'

export type CostImportMapping = Record<CostImportMappingKey, number | ''>

export type CsvTable = {
  delimiter: string
  headers: string[]
  rows: string[][]
  headerRow: number
  skippedRows: string[][]
}

const HEADER_ALIASES = {
  sku: ['sku', 'kod sku', 'sku_key', 'sku key'],
  cost: ['cena zakupu', 'koszt zakupu', 'cost', 'purchase cost', 'purchase_cost'],
  vat: ['vat', 'vat rate', 'stawka vat'],
  validFrom: ['start ceny zakupu', 'valid from', 'valid_from', 'od', 'data od'],
  validTo: ['koniec ceny zakupu', 'valid to', 'valid_to', 'do', 'data do'],
} as const

export function normalizeHeader(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/["']/g, '')
}

export function detectDelimiter(firstLine: string): string {
  const candidates = [';', ',', '\t']
  return candidates
    .map(delimiter => ({ delimiter, count: firstLine.split(delimiter).length }))
    .sort((a, b) => b.count - a.count)[0]?.delimiter ?? ';'
}

function detectDelimiterForLines(lines: string[]): string {
  const candidates = [';', ',', '\t']
  return candidates
    .map(delimiter => ({
      delimiter,
      count: lines.slice(0, 10).reduce((sum, line) => sum + Math.max(0, line.split(delimiter).length - 1), 0),
    }))
    .sort((a, b) => b.count - a.count)[0]?.delimiter ?? ';'
}

export function parseCsvLine(line: string, delimiter: string): string[] {
  const out: string[] = []
  let current = ''
  let inQuotes = false

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i]
    const next = line[i + 1]
    if (char === '"' && inQuotes && next === '"') {
      current += '"'
      i += 1
      continue
    }
    if (char === '"') {
      inQuotes = !inQuotes
      continue
    }
    if (char === delimiter && !inQuotes) {
      out.push(current.trim())
      current = ''
      continue
    }
    current += char
  }
  out.push(current.trim())
  return out
}

function findColumn(headers: string[], aliases: readonly string[]): number {
  return headers.findIndex(header => aliases.includes(header))
}

function headerScore(cells: string[]): number {
  const normalized = cells.map(normalizeHeader)
  const groups = Object.values(HEADER_ALIASES)
  return groups.reduce((score, aliases) => score + (findColumn(normalized, aliases) >= 0 ? 1 : 0), 0)
}

function normalizeMoney(value: string): string | null {
  const cleaned = value
    .trim()
    .replace(/\s/g, '')
    .replace(/zł|pln/gi, '')
    .replace(',', '.')
  if (!cleaned) return null
  const parsed = Number(cleaned)
  if (!Number.isFinite(parsed) || parsed < 0) return null
  return parsed.toFixed(4).replace(/\.?0+$/, '')
}

function normalizeVat(value: string): string | undefined {
  const cleaned = value.trim().replace('%', '').replace(',', '.')
  if (!cleaned) return undefined
  const parsed = Number(cleaned)
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 25) return undefined
  return String(parsed)
}

function normalizeDate(value: string): string | undefined {
  const cleaned = value.trim()
  if (!cleaned) return undefined
  const iso = cleaned.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (iso) return cleaned
  const pl = cleaned.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/)
  if (!pl) return undefined
  const day = pl[1].padStart(2, '0')
  const month = pl[2].padStart(2, '0')
  return `${pl[3]}-${month}-${day}`
}

export function parseCsvTable(text: string): CsvTable {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter(line => line.trim())
  if (!lines.length) return { delimiter: ';', headers: [], rows: [], headerRow: -1, skippedRows: [] }
  const delimiter = detectDelimiterForLines(lines)
  const parsedLines = lines.map(line => parseCsvLine(line, delimiter))
  let headerRow = 0
  let bestScore = -1
  parsedLines.slice(0, 20).forEach((cells, idx) => {
    const score = headerScore(cells)
    if (score > bestScore) {
      bestScore = score
      headerRow = idx
    }
  })
  return {
    delimiter,
    headers: parsedLines[headerRow] ?? [],
    rows: parsedLines.slice(headerRow + 1),
    headerRow,
    skippedRows: parsedLines.slice(0, headerRow),
  }
}

export function guessCostImportMapping(headers: string[]): CostImportMapping {
  const normalized = headers.map(normalizeHeader)
  const col = (aliases: readonly string[]) => {
    const found = findColumn(normalized, aliases)
    return found >= 0 ? found : ''
  }
  return {
    sku: col(HEADER_ALIASES.sku),
    cost: col(HEADER_ALIASES.cost),
    vat: col(HEADER_ALIASES.vat),
    validFrom: col(HEADER_ALIASES.validFrom),
    validTo: col(HEADER_ALIASES.validTo),
  }
}

export function parseMappedCostImport(table: CsvTable, mapping: CostImportMapping): ParsedCostImport {
  const errors: string[] = []
  const warnings: string[] = []
  if (!table.headers.length || !table.rows.length) {
    return { rows: [], errors: ['Plik CSV jest pusty albo nie ma wierszy danych.'], warnings }
  }
  if (table.skippedRows.length > 0) {
    warnings.push(`Pominięto ${table.skippedRows.length} wiersz(e) przed nagłówkiem.`)
  }

  const skuCol = mapping.sku
  const costCol = mapping.cost
  const vatCol = mapping.vat
  const fromCol = mapping.validFrom
  const toCol = mapping.validTo

  if (skuCol === '') errors.push('Wybierz kolumnę SKU.')
  if (costCol === '') errors.push('Wybierz kolumnę "cena zakupu".')
  if (errors.length) return { rows: [], errors, warnings }
  const skuIndex = skuCol as number
  const costIndex = costCol as number

  const rows: ParsedCostImportRow[] = []
  for (let i = 0; i < table.rows.length; i += 1) {
    const cells = table.rows[i]
    const rowNo = table.headerRow + i + 2
    const sku = cells[skuIndex]?.trim()
    const cost = normalizeMoney(cells[costIndex] ?? '')
    if (!sku && !cost) continue
    if (!sku) {
      errors.push(`Wiersz ${rowNo}: brak SKU.`)
      continue
    }
    if (!cost) {
      errors.push(`Wiersz ${rowNo}: nieprawidłowa cena zakupu.`)
      continue
    }

    const validFrom = fromCol !== '' ? normalizeDate(cells[fromCol] ?? '') : undefined
    const validTo = toCol !== '' ? normalizeDate(cells[toCol] ?? '') : undefined
    if (fromCol !== '' && cells[fromCol]?.trim() && !validFrom) {
      errors.push(`Wiersz ${rowNo}: nieprawidłowa data startu ceny zakupu.`)
      continue
    }
    if (toCol !== '' && cells[toCol]?.trim() && !validTo) {
      errors.push(`Wiersz ${rowNo}: nieprawidłowa data końca ceny zakupu.`)
      continue
    }
    rows.push({
      sku,
      cost,
      vat: vatCol !== '' ? normalizeVat(cells[vatCol] ?? '') : undefined,
      validFrom,
      validTo,
      sourceRow: rowNo,
    })
  }

  if (!rows.length && !errors.length) errors.push('Nie znaleziono żadnego poprawnego wiersza kosztu.')
  return { rows, errors, warnings }
}

export function parseCostImportCsv(text: string): ParsedCostImport {
  const table = parseCsvTable(text)
  return parseMappedCostImport(table, guessCostImportMapping(table.headers))
}
