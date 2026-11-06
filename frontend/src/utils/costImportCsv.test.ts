import { describe, it, expect } from 'vitest'
import {
  normalizeHeader,
  detectDelimiter,
  parseCsvLine,
  parseCsvTable,
  guessCostImportMapping,
  parseCostImportCsv,
} from './costImportCsv'

const HEADER = 'sku;cena zakupu;vat;start ceny zakupu;koniec ceny zakupu'

describe('normalizeHeader', () => {
  it('trims, lowercases and collapses whitespace', () => {
    expect(normalizeHeader('  Cena   Zakupu  ')).toBe('cena zakupu')
  })

  it('strips quotes', () => {
    expect(normalizeHeader('"SKU"')).toBe('sku')
    expect(normalizeHeader("'cost'")).toBe('cost')
  })
})

describe('detectDelimiter', () => {
  it('detects semicolon, comma and tab', () => {
    expect(detectDelimiter('a;b;c')).toBe(';')
    expect(detectDelimiter('a,b,c')).toBe(',')
    expect(detectDelimiter('a\tb\tc')).toBe('\t')
  })

  it('falls back to semicolon when no delimiter is present', () => {
    expect(detectDelimiter('abc')).toBe(';')
  })
})

describe('parseCsvLine', () => {
  it('splits on the delimiter and trims cells', () => {
    expect(parseCsvLine(' a ; b ;c', ';')).toEqual(['a', 'b', 'c'])
  })

  it('keeps delimiters inside quoted values', () => {
    expect(parseCsvLine('"a;b";c', ';')).toEqual(['a;b', 'c'])
  })

  it('unescapes doubled quotes', () => {
    expect(parseCsvLine('"say ""hi""";x', ';')).toEqual(['say "hi"', 'x'])
  })
})

describe('parseCsvTable', () => {
  it('strips BOM and detects the header row', () => {
    const table = parseCsvTable('﻿sku;cena zakupu\nA-1;10')
    expect(table.delimiter).toBe(';')
    expect(table.headerRow).toBe(0)
    expect(table.headers).toEqual(['sku', 'cena zakupu'])
    expect(table.rows).toEqual([['A-1', '10']])
    expect(table.skippedRows).toEqual([])
  })

  it('skips preamble rows before the header', () => {
    const table = parseCsvTable('notatka wstępna\nsku;cena zakupu\nA-1;10')
    expect(table.headerRow).toBe(1)
    expect(table.skippedRows).toEqual([['notatka wstępna']])
    expect(table.rows).toEqual([['A-1', '10']])
  })

  it('handles empty input', () => {
    const table = parseCsvTable('')
    expect(table.headers).toEqual([])
    expect(table.rows).toEqual([])
    expect(table.headerRow).toBe(-1)
  })
})

describe('guessCostImportMapping', () => {
  it('maps Polish and English header aliases', () => {
    expect(guessCostImportMapping(['SKU', 'Cena zakupu', 'Stawka VAT', 'Od', 'Do'])).toEqual({
      sku: 0,
      cost: 1,
      vat: 2,
      validFrom: 3,
      validTo: 4,
    })
    expect(guessCostImportMapping(['sku_key', 'purchase_cost', 'vat rate'])).toEqual({
      sku: 0,
      cost: 1,
      vat: 2,
      validFrom: '',
      validTo: '',
    })
  })

  it('returns empty string for missing columns', () => {
    expect(guessCostImportMapping(['sku', 'cost'])).toEqual({
      sku: 0,
      cost: 1,
      vat: '',
      validFrom: '',
      validTo: '',
    })
  })
})

describe('parseCostImportCsv — kwoty', () => {
  it('parses pl-PL comma decimals', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;12,34;;;`)
    expect(result.errors).toEqual([])
    expect(result.rows[0].cost).toBe('12.34')
  })

  it('strips currency markers and thousand-separator spaces', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;1 234,56 zł;;;\nA-2;PLN 99,90;;;`)
    expect(result.errors).toEqual([])
    expect(result.rows[0].cost).toBe('1234.56')
    expect(result.rows[1].cost).toBe('99.9')
  })

  it('keeps grosze precision up to 4 decimal places and strips trailing zeros', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;10,50;;;\nA-2;0,001;;;\nA-3;0;;;`)
    expect(result.rows.map(r => r.cost)).toEqual(['10.5', '0.001', '0'])
  })

  it('rounds beyond 4 decimal places', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;1,23456;;;`)
    expect(result.rows[0].cost).toBe('1.2346')
  })

  it('rejects negative amounts', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;-5;;;`)
    expect(result.rows).toEqual([])
    expect(result.errors).toEqual(['Wiersz 2: nieprawidłowa cena zakupu.'])
  })

  it('rejects non-numeric amounts', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;abc;;;`)
    expect(result.errors).toEqual(['Wiersz 2: nieprawidłowa cena zakupu.'])
  })

  it('reports rows with a missing SKU and skips fully empty rows', () => {
    const result = parseCostImportCsv(`${HEADER}\n;10;;;\n;;;\nA-1;5;;;`)
    expect(result.errors).toEqual(['Wiersz 2: brak SKU.'])
    expect(result.rows).toHaveLength(1)
    expect(result.rows[0].sourceRow).toBe(4)
  })
})

describe('parseCostImportCsv — stawki VAT', () => {
  const parseVat = (vat: string) => parseCostImportCsv(`${HEADER}\nA-1;10;${vat};;`).rows[0]?.vat

  it('accepts 23%, 8% and 0% (zwolniona)', () => {
    expect(parseVat('23')).toBe('23')
    expect(parseVat('8')).toBe('8')
    expect(parseVat('0')).toBe('0')
  })

  it('accepts percent sign and comma decimals', () => {
    expect(parseVat('23%')).toBe('23')
    expect(parseVat('7,5')).toBe('7.5')
  })

  it('accepts the upper bound of 25', () => {
    expect(parseVat('25')).toBe('25')
  })

  it('treats out-of-range or invalid rates as missing', () => {
    expect(parseVat('26')).toBeUndefined()
    expect(parseVat('-3')).toBeUndefined()
    expect(parseVat('zw')).toBeUndefined()
    expect(parseVat('')).toBeUndefined()
  })
})

describe('parseCostImportCsv — daty', () => {
  it('passes ISO dates through', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;10;;2026-02-01;2026-12-31`)
    expect(result.rows[0].validFrom).toBe('2026-02-01')
    expect(result.rows[0].validTo).toBe('2026-12-31')
  })

  it('converts Polish date formats to ISO', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;10;;1.2.2026;31/12/2026`)
    expect(result.rows[0].validFrom).toBe('2026-02-01')
    expect(result.rows[0].validTo).toBe('2026-12-31')
  })

  it('documents current behavior: ISO-shaped but impossible dates are not validated', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;10;;2026-13-99;`)
    expect(result.errors).toEqual([])
    expect(result.rows[0].validFrom).toBe('2026-13-99')
  })

  it('rejects unparseable dates with a row error', () => {
    const result = parseCostImportCsv(`${HEADER}\nA-1;10;;foo;`)
    expect(result.rows).toEqual([])
    expect(result.errors).toEqual(['Wiersz 2: nieprawidłowa data startu ceny zakupu.'])
  })
})

describe('parseCostImportCsv — struktura pliku', () => {
  it('errors on an empty file', () => {
    const result = parseCostImportCsv('')
    expect(result.errors).toEqual(['Plik CSV jest pusty albo nie ma wierszy danych.'])
  })

  it('warns about rows skipped before the header and numbers rows from the file', () => {
    const result = parseCostImportCsv(`notatka\n${HEADER}\nA-1;10;23;;`)
    expect(result.warnings).toEqual(['Pominięto 1 wiersz(e) przed nagłówkiem.'])
    expect(result.rows[0].sourceRow).toBe(3)
  })

  it('handles quoted values containing the delimiter', () => {
    const result = parseCostImportCsv(`${HEADER}\n"A;1";10;;;`)
    expect(result.errors).toEqual([])
    expect(result.rows[0].sku).toBe('A;1')
  })
})
