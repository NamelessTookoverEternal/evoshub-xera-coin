# EVOS Data: paid orders no longer wait on "awaiting payment"

No migration. Copy the files over the same paths, redeploy Render (backend), then the frontend.

Backend (python/services/evosdata/core.py)
- /orders/sync (called by the success page) now asks Paystack itself and settles the order at once if it is paid.
- /orders/me and /orders/track also settle paid-but-pending orders in the background when someone opens them.
- Only one of webhook / success page / background job can dispatch an order (atomic claim), so no double delivery.
- The background recovery job now starts after 1 minute instead of 5.
- Orders bought while signed out (guest orders with your account's email) now also show on My Orders.
- A payment made on an older Paystack reference of a re-opened pending order is matched to its order.

Frontend: statuses read "Confirming your payment" -> "Order is being queued" -> "Processing" -> "Delivered".
My Orders is a grid, newest first.
