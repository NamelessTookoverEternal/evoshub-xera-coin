# DashXera: check the payment before calling an order "not delivered"

No migration. Copy the files over the same paths, redeploy Render, then the frontend.
(Independent of evosdata-orders-fix.zip; both can be applied.)

- A failed order with no provider reference is only counted/flagged as "paid, not dispatched" if Paystack confirms the payment
  (wallet-paid orders count as paid). If Paystack says the money never arrived it is a failed order ("Failed, never paid"),
  not a missed dispatch, cannot be reprocessed, and is no longer counted as a sale.
- If Paystack cannot be reached, nothing is guessed: the order shows "Payment not checked yet" and the Attention feed asks for a check.
- A paid order younger than 10 minutes is just being queued and is not flagged.
- Results are cached (paid for a day, others 5 minutes); at most 40 Paystack look-ups per request, run in parallel.
