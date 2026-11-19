# QR code for the XERA ID + "My transfers"

No database migration. Copy the files over the same paths, redeploy Render (backend) then the frontend.

p2p.py, xera-transfer.js and xera-transfer.html here ALSO contain the auto-lock changes from xera-autolock.zip,
so use these copies (they are the newest). Apply xera-autolock.zip's other files and its SQL as before.

netlify.toml / vercel.json (root and hub-frontend): the Permissions-Policy header changed camera=() to camera=(self)
so the in-app QR scanner can ask for the camera. Without that change the browser blocks the camera and only
"Choose a photo" works.
