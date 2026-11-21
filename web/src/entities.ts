// How each kind of value is named and which highlighter colour it gets.

type Family = 'person' | 'number' | 'contact' | 'place' | 'custom'

const FAMILY: Record<string, Family> = {
  PERSON: 'person',
  ADDRESS: 'place',
  LOCATION: 'place',
  EMAIL: 'contact',
  PHONE: 'contact',
  UPI: 'contact',
  IP: 'contact',
  CARD: 'number',
  IBAN: 'number',
  ACCOUNT: 'number',
  AADHAAR: 'number',
  PAN: 'number',
  IFSC: 'number',
  CUSTOM: 'custom',
}

const NAMES: Record<string, [string, string]> = {
  PERSON: ['person', 'people'],
  ADDRESS: ['address', 'addresses'],
  LOCATION: ['place', 'places'],
  EMAIL: ['email', 'emails'],
  PHONE: ['phone number', 'phone numbers'],
  UPI: ['UPI ID', 'UPI IDs'],
  IP: ['IP address', 'IP addresses'],
  CARD: ['card number', 'card numbers'],
  IBAN: ['IBAN', 'IBANs'],
  ACCOUNT: ['account number', 'account numbers'],
  AADHAAR: ['Aadhaar number', 'Aadhaar numbers'],
  PAN: ['PAN', 'PANs'],
  IFSC: ['IFSC code', 'IFSC codes'],
  CUSTOM: ['other value', 'other values'],
}

export function swatch(type: string): string {
  return `var(--hl-${FAMILY[type] ?? 'custom'})`
}

export function typeName(type: string, count = 1): string {
  const [one, many] = NAMES[type] ?? [type.toLowerCase(), type.toLowerCase()]
  return count === 1 ? one : many
}

export function tokenType(token: string): string {
  return token.split('_')[0].toUpperCase()
}

/** "3 people, 1 card number and 1 email" */
export function describeCounts(counts: Record<string, number>): string {
  const parts = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([type, n]) => `${n} ${typeName(type, n)}`)
  if (parts.length <= 1) return parts.join('')
  return `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}`
}

export const TOKEN_PATTERN = /\b([A-Za-z]+_[0-9a-fA-F]{6,64}(?:_\d{1,3})?)\b/g

/** Types a person can add by hand in the "always hide" list. */
export const KNOWN_TYPES = [
  ['PERSON', 'Name'],
  ['ADDRESS', 'Address'],
  ['ACCOUNT', 'Account number'],
  ['EMAIL', 'Email'],
  ['PHONE', 'Phone'],
  ['CUSTOM', 'Other'],
] as const
