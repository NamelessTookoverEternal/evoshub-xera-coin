# Vaults tab: apply

No database migration. Copy these files over the same paths in your repo:

- python/main.py                                   (2 lines added: import + router)
- python/xera/routes_admin_vaults.py               (new)
- hub-frontend/src/js/admin-console.js             (Vaults entry replaces "Discount vault"; old loadVault removed)
- hub-frontend/src/js/admin-console-vaults.js      (new)
- hub-frontend/src/pages/admin-website-chat.html   (sec-vault panel replaced by sec-vaults)

Then redeploy backend (Render) and frontend. Old "#vault" links open the discount vault inside Vaults.
On-chain claim/withdraw code is not touched.
