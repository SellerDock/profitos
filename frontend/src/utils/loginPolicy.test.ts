import { expect, it } from 'vitest'
import { rejectOperatorOnUserLogin } from './loginPolicy'

it('rejects operators on the normal hosted login only', () => {
  expect(rejectOperatorOnUserLogin('hosted', false, true)).toBe(true)
  expect(rejectOperatorOnUserLogin('selfhosted', false, true)).toBe(false)
  expect(rejectOperatorOnUserLogin('hosted', true, true)).toBe(false)
  expect(rejectOperatorOnUserLogin('hosted', false, false)).toBe(false)
})
