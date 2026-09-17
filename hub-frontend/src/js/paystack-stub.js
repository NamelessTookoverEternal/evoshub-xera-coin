/**
 * EVOS Business Hub — Paystack scaffold (NOT wired up yet)
 * ─────────────────────────────────────────────────────────
 * This file is intentionally inert. It exists so that when we're
 * ready to accept online payment for Website Creation packages (or
 * any other paid tool on the Hub), the integration point is already
 * planned out and documented — nobody has to design it from scratch.
 *
 * Nothing in this file runs unless a page explicitly imports and
 * calls `payWithPaystack(...)`, and no page currently does.
 *
 * SETUP, WHEN WE'RE READY:
 * 1. Add the Paystack inline JS to the page:
 *      <script src="https://js.paystack.co/v1/inline.js"></script>
 * 2. Set VITE_PAYSTACK_PUBLIC_KEY in .env (see .env.example).
 * 3. Import and call payWithPaystack() from a click handler, e.g. a
 *    "Pay Now" button next to the package the user picked.
 * 4. Verify the transaction server-side (FastAPI) using the secret
 *    key before marking the order/request as paid — never trust the
 *    frontend callback alone.
 */

const PAYSTACK_PUBLIC_KEY = import.meta.env.VITE_PAYSTACK_PUBLIC_KEY || '';

/**
 * Opens the Paystack inline checkout popup.
 *
 * @param {Object} opts
 * @param {string} opts.email        Customer email (required by Paystack)
 * @param {number} opts.amountKobo   Amount in the smallest currency unit
 *                                   (pesewas for GHS — e.g. GH₵800 = 80000)
 * @param {string} [opts.currency]   Defaults to 'GHS'
 * @param {string} [opts.reference]  Unique transaction reference; generate
 *                                   one per request/order rather than reusing
 * @param {(response: any) => void} opts.onSuccess
 * @param {() => void} [opts.onClose]
 */
export function payWithPaystack({
  email,
  amountKobo,
  currency = 'GHS',
  reference,
  onSuccess,
  onClose,
}) {
  if (!PAYSTACK_PUBLIC_KEY) {
    console.warn(
      '[paystack-stub] No VITE_PAYSTACK_PUBLIC_KEY set — payment is not configured yet.'
    );
    return;
  }
  if (typeof window.PaystackPop === 'undefined') {
    console.warn(
      '[paystack-stub] Paystack inline.js has not been loaded on this page.'
    );
    return;
  }

  const handler = window.PaystackPop.setup({
    key: PAYSTACK_PUBLIC_KEY,
    email,
    amount: amountKobo,
    currency,
    ref: reference || `evoshub_${Date.now()}`,
    callback: (response) => onSuccess?.(response),
    onClose: () => onClose?.(),
  });

  handler.openIframe();
}
