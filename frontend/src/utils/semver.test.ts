import { describe, it, expect } from 'vitest'
import { compareSemver, isNewerVersion } from './semver'

describe('compareSemver', () => {
  it('returns positive when a > b', () => {
    expect(compareSemver('0.2.0', '0.1.9')).toBeGreaterThan(0)
    expect(compareSemver('1.0.0', '0.9.9')).toBeGreaterThan(0)
    expect(compareSemver('0.1.1', '0.1.0')).toBeGreaterThan(0)
  })

  it('returns negative when a < b', () => {
    expect(compareSemver('0.1.9', '0.2.0')).toBeLessThan(0)
    expect(compareSemver('0.9.9', '1.0.0')).toBeLessThan(0)
  })

  it('returns 0 for equal versions', () => {
    expect(compareSemver('1.2.3', '1.2.3')).toBe(0)
  })

  it('pads shorter versions with zeros ("0.1" == "0.1.0")', () => {
    expect(compareSemver('0.1', '0.1.0')).toBe(0)
    expect(compareSemver('1', '1.0.0')).toBe(0)
    expect(compareSemver('0.2', '0.1.9')).toBeGreaterThan(0)
  })

  it('compares numerically, not lexicographically', () => {
    expect(compareSemver('10.0.0', '2.0.0')).toBeGreaterThan(0)
    expect(compareSemver('2.0.0', '10.0.0')).toBeLessThan(0)
  })

  it('ignores pre-release and build suffixes', () => {
    expect(compareSemver('0.2.0-beta', '0.2.0')).toBe(0)
    expect(compareSemver('1.0.0+build5', '1.0.0')).toBe(0)
    expect(compareSemver('0.2.0-beta', '0.1.9')).toBeGreaterThan(0)
  })

  it('trims surrounding whitespace', () => {
    expect(compareSemver(' 1.2.3 ', '1.2.3')).toBe(0)
  })

  it('returns null when either version cannot be parsed', () => {
    expect(compareSemver('abc', '1.0.0')).toBeNull()
    expect(compareSemver('1.0.0', 'xyz')).toBeNull()
    expect(compareSemver('', '1.0.0')).toBeNull()
  })

  it('rejects versions with 4+ numeric components', () => {
    expect(compareSemver('1.0.0.1', '1.0.0')).toBeNull()
  })
})

describe('isNewerVersion', () => {
  it('is true when latest is ahead of current', () => {
    expect(isNewerVersion('0.2.0', '0.1.9')).toBe(true)
    expect(isNewerVersion('1.0.0', '0.9.9')).toBe(true)
  })

  it('is false when latest equals current', () => {
    expect(isNewerVersion('0.2.0', '0.2.0')).toBe(false)
    expect(isNewerVersion('0.2', '0.2.0')).toBe(false)
  })

  it('is false when latest is behind current', () => {
    expect(isNewerVersion('0.1.9', '0.2.0')).toBe(false)
  })

  it('is false when a version cannot be parsed (fail silent)', () => {
    expect(isNewerVersion('1.0.0.1', '1.0.0')).toBe(false)
    expect(isNewerVersion('not-a-version', '1.0.0')).toBe(false)
  })
})
