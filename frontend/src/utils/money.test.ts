import { describe, it, expect } from 'vitest'
import {
  formatNumber, f, num, pct, sumMoney,
  grossToNet23, grossToNetByRate, vatMultiplier, visibleUnitCost, netCostFromVisible,
  money, pln, fCurrency, neg, pos, profitMoney, costMoney, costPln,
  vatMoney, signedVatMoney,
} from './money'

// pl-PL groups thousands with a non-breaking space.
const NBSP = ' '

describe('formatNumber', () => {
  it('formats pl-PL with fixed decimals', () => {
    expect(formatNumber(1234.5)).toBe('1234,50')
    expect(formatNumber(12345.5)).toBe(`12${NBSP}345,50`)
    expect(formatNumber(12.5, 1)).toBe('12,5')
    expect(formatNumber(12, 0)).toBe('12')
  })
  it('passes NaN through (no guard, as in Products/Stock usage)', () => {
    expect(formatNumber(NaN)).toBe('NaN')
  })
})

describe('f', () => {
  it('renders null/undefined/NaN as dash', () => {
    expect(f(null)).toBe('—')
    expect(f(undefined)).toBe('—')
    expect(f('abc')).toBe('—')
  })
  it('formats numbers and numeric strings', () => {
    expect(f('12.5')).toBe('12,50')
    expect(f(12345.5)).toBe(`12${NBSP}345,50`)
    expect(f(0)).toBe('0,00')
    expect(f('0.005', 1)).toBe('0,0')
    expect(f(-5)).toBe('-5,00')
  })
})

describe('num / sumMoney', () => {
  it('coerces nullish to 0', () => {
    expect(num(null)).toBe(0)
    expect(num(undefined)).toBe(0)
    expect(num('3.5')).toBe(3.5)
  })
  it('sums mixed values', () => {
    expect(sumMoney('1.5', null, '2.5', undefined)).toBe(4)
    expect(sumMoney()).toBe(0)
  })
})

describe('pct', () => {
  it('renders falsy input as dash', () => {
    expect(pct(null)).toBe('—')
    expect(pct(undefined)).toBe('—')
    expect(pct(0)).toBe('—')
    expect(pct('')).toBe('—')
  })
  it('keeps the truthy-string quirk: "0" renders as 0,00%', () => {
    expect(pct('0')).toBe('0,00%')
  })
  it('formats values', () => {
    expect(pct('12.5')).toBe('12,50%')
  })
})

describe('VAT math', () => {
  it('grossToNet23 handles zero, null and negatives', () => {
    expect(grossToNet23(0)).toBe(0)
    expect(grossToNet23('0')).toBe(0)
    expect(grossToNet23(null)).toBe(0)
    expect(grossToNet23('123')).toBeCloseTo(100, 10)
    expect(grossToNet23('-123')).toBeCloseTo(-100, 10)
  })
  it('grossToNetByRate supports 23/8/0 rates', () => {
    expect(grossToNetByRate('123', 23)).toBeCloseTo(100, 10)
    expect(grossToNetByRate('108', 8)).toBeCloseTo(100, 10)
    expect(grossToNetByRate('100', 0)).toBe(100)
    expect(grossToNetByRate('0', 23)).toBe(0)
    expect(grossToNetByRate(null, 23)).toBe(0)
  })
  it('round-trips netto ↔ brutto', () => {
    for (const rate of [23, 8, 0]) {
      const net = grossToNetByRate('1234.56', rate)
      expect(net * vatMultiplier(rate)).toBeCloseTo(1234.56, 10)
    }
  })
  it('vatMultiplier defaults to 1 for nullish/non-finite rates', () => {
    expect(vatMultiplier(23)).toBeCloseTo(1.23, 10)
    expect(vatMultiplier(8)).toBeCloseTo(1.08, 10)
    expect(vatMultiplier(0)).toBe(1)
    expect(vatMultiplier(null)).toBe(1)
    expect(vatMultiplier('abc')).toBe(1)
  })
  it('visibleUnitCost respects the net/gross display mode', () => {
    expect(visibleUnitCost(100, 23, true)).toBe(100)
    expect(visibleUnitCost(100, 23, false)).toBeCloseTo(123, 10)
    expect(visibleUnitCost(100, 0, false)).toBe(100)
  })
  it('netCostFromVisible parses comma input and rejects non-finite', () => {
    expect(netCostFromVisible('12,34', 23, true)).toBe(12.34)
    expect(netCostFromVisible('12,34', 23, false)).toBeCloseTo(10.03, 2)
    expect(netCostFromVisible('abc', 23, true)).toBeNull()
    // empty string coerces via Number('') → 0 (unchanged behavior)
    expect(netCostFromVisible('', 23, true)).toBe(0)
  })
})

describe('money core and wrappers', () => {
  it('renders zero as dash by default (Dashboard) or 0,00 zł on demand (Orders)', () => {
    expect(pln('0')).toBe('—')
    expect(pln(null)).toBe('—')
    expect(pln('0', 'zero')).toBe('0,00 zł')
    expect(pln(null, 'zero')).toBe('0,00 zł')
    expect(money(0, { zero: 'zero', suffix: 'EUR' })).toBe('0,00 EUR')
  })
  it('formats plain / signed / suffixed values', () => {
    expect(pln('12.3')).toBe('12,30 zł')
    expect(fCurrency('12.3', 'EUR')).toBe('12,30 EUR')
    expect(fCurrency('', 'EUR')).toBe('—')
    expect(neg('7')).toBe('-7,00 zł')
    expect(neg(0)).toBe('—')
    expect(pos('12.5')).toBe('+12,50 zł')
    expect(pos('0')).toBe('—')
    expect(profitMoney('5', 'EUR')).toBe('5,00 EUR')
    expect(profitMoney(0)).toBe('—')
    expect(costMoney('5')).toBe('-5,00 zł')
    expect(costMoney('5', 'EUR')).toBe('-5,00 EUR')
  })
  it('costPln uses the Unicode minus (U+2212) and dash for zero', () => {
    expect(costPln('12.3')).toBe('−12,30 zł')
    expect(costPln(0)).toBe('—')
    expect(costPln(null)).toBe('—')
    // negative input keeps its own sign after the Unicode minus (unchanged behavior)
    expect(costPln('-5')).toBe('−-5,00 zł')
  })
  it('keeps the NaN-string quirk: body falls back to the f() dash', () => {
    expect(pln('abc')).toBe('— zł')
    expect(costMoney('abc')).toBe('-— zł')
  })
})

describe('vatMoney', () => {
  it('renders zero as dash by default (Dashboard variant)', () => {
    expect(vatMoney(0)).toEqual({ text: '—', title: undefined, value: 0 })
    expect(vatMoney(null)).toEqual({ text: '—', title: undefined, value: 0 })
  })
  it('renders zero as 0,00 zł in the Orders variant (zero: "zero")', () => {
    expect(vatMoney(0, { zero: 'zero' }).text).toBe('0,00 zł')
    expect(vatMoney(0, { zero: 'zero', suffix: 'EUR' }).text).toBe('0,00 EUR')
  })
  it('uses net for VAT payers and gross otherwise', () => {
    expect(vatMoney('123', { isVatPayer: true, net: '100' })).toEqual({
      text: '100,00 zł', title: 'Brutto: 123,00 zł', value: 100,
    })
    expect(vatMoney('123', { isVatPayer: false }).text).toBe('123,00 zł')
    expect(vatMoney('123', { isVatPayer: false }).title).toBeUndefined()
  })
  it('shows refund and rebate amounts net for VAT payers and gross for others', () => {
    expect(vatMoney('69.99', { net: '64.81', isVatPayer: true, sign: 'minus' })).toEqual({
      text: '-64,81 zł', title: 'Brutto: 69,99 zł', value: 64.81,
    })
    expect(vatMoney('69.99', { net: '64.81', isVatPayer: false, sign: 'minus' }).text).toBe('-69,99 zł')
    expect(vatMoney('9.05', { net: '7.36', isVatPayer: true, sign: 'plus' })).toEqual({
      text: '+7,36 zł', title: 'Brutto: 9,05 zł', value: 7.36,
    })
    expect(vatMoney('9.05', { net: '7.36', isVatPayer: false, sign: 'plus' }).text).toBe('+9,05 zł')
  })
  it('falls back to grossToNet23 when net is not given', () => {
    const r = vatMoney('246', { isVatPayer: true })
    expect(r.text).toBe('200,00 zł')
    expect(r.title).toBe('Brutto: 246,00 zł')
    expect(r.value).toBeCloseTo(200, 10)
  })
  it('applies sign and currency suffix', () => {
    expect(vatMoney('10', { sign: 'plus' }).text).toBe('+10,00 zł')
    expect(vatMoney('10', { sign: 'minus' }).text).toBe('-10,00 zł')
    expect(vatMoney('10', { suffix: 'EUR' }).text).toBe('10,00 EUR')
    expect(vatMoney('10', { isVatPayer: true, net: '8.13', suffix: 'EUR' }).title).toBe('Brutto: 10,00 EUR')
  })
  it('handles negative amounts (refunds)', () => {
    expect(vatMoney('-50').text).toBe('-50,00 zł')
    expect(vatMoney('-50', { sign: 'minus' }).text).toBe('--50,00 zł')
    expect(vatMoney('-123', { isVatPayer: true }).value).toBeCloseTo(-100, 10)
    expect(vatMoney('-123', { isVatPayer: true }).title).toBe('Brutto: -123,00 zł')
  })
})

describe('signedVatMoney', () => {
  it('renders negative values with plus (refund corrections)', () => {
    expect(signedVatMoney('-50').text).toBe('+50,00 zł')
    expect(signedVatMoney('-123', { isVatPayer: true }).text).toBe('+100,00 zł')
  })
  it('renders zero/positive values with minus', () => {
    expect(signedVatMoney('50').text).toBe('-50,00 zł')
    expect(signedVatMoney(0).text).toBe('—')
    expect(signedVatMoney(null).text).toBe('—')
  })
  it('respects the currency suffix', () => {
    expect(signedVatMoney('-50', { suffix: 'EUR' }).text).toBe('+50,00 EUR')
  })
})
