/** Checks done in the browser before anything is sent, so the person is told what is wrong right at the field (the server still checks everything). */
export const isEmail = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v.trim())

type Rule = (value: string) => string | undefined

export const required = (label: string): Rule => (v) => (v.trim() ? undefined : `${label} is required.`)
export const emailRule: Rule = (v) => (!v.trim() ? 'Email is required.' : isEmail(v) ? undefined : 'Enter a valid email address, like name@company.com.')
export const optionalEmail: Rule = (v) => (!v.trim() || isEmail(v) ? undefined : 'Enter a valid email address, like name@company.com.')
export const minLength = (label: string, n: number): Rule => (v) => (v.length >= n ? undefined : v.length === 0 ? `${label} is required.` : `${label} must have at least ${n} characters.`)

/** Runs one rule per field; only fields that have a problem appear in the result. */
export function validate<T extends Record<string, string>>(values: T, rules: { [K in keyof T]?: Rule }): Partial<Record<keyof T, string>> {
  const out: Partial<Record<keyof T, string>> = {}
  for (const key of Object.keys(rules) as (keyof T)[]) {
    const problem = rules[key]?.(values[key])
    if (problem) out[key] = problem
  }
  return out
}

export const hasProblems = (errors: object) => Object.values(errors).some(Boolean)
