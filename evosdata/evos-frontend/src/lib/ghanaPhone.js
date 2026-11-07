// EVOS Data is available in Ghana only. This is the single place the browser
// decides whether a number is a Ghana mobile number. The backend repeats the
// same rule (python/services/evosdata/core.py -> ghana_phone), so this is a
// convenience for the customer, not the security boundary.

export const GHANA_ONLY_MSG =
  "EVOS Data is currently available in Ghana only. Enter a valid Ghana number, e.g. 0551234567.";

// MTN, Telecel (Vodafone) and AirtelTigo mobile prefixes — keep in sync with
// GHANA_MOBILE_PREFIXES in the backend.
const PREFIXES = new Set([
  "024", "025", "053", "054", "055", "059", // MTN
  "020", "050",                             // Telecel
  "026", "027", "056", "057",               // AirtelTigo
]);

// Returns the canonical 10-digit local number (0XXXXXXXXX), or null if the
// input is not a Ghana mobile number. Accepts 0551234567, 551234567,
// 233551234567, +233551234567 and 00233551234567, with spaces/dashes/brackets.
export function toGhanaPhone(raw) {
  let s = String(raw ?? "").replace(/[\s\-().]/g, "");
  if (s.startsWith("+")) s = s.slice(1);
  if (s.startsWith("00233")) s = s.slice(2);
  if (!/^[0-9]+$/.test(s)) return null;
  let local;
  if (s.length === 12 && s.startsWith("233")) local = "0" + s.slice(3);
  else if (s.length === 10 && s.startsWith("0")) local = s;
  else if (s.length === 9 && !s.startsWith("0")) local = "0" + s;
  else return null;
  return PREFIXES.has(local.slice(0, 3)) ? local : null;
}

export const isGhanaPhone = (raw) => toGhanaPhone(raw) !== null;
