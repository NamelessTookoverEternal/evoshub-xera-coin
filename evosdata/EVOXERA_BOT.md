# EVOXERA TECHNOLOGY WhatsApp bot

Files added: `evoxera_bot.py`, `supabase/migrations/20261012_evoxera_whatsapp_bot.sql`,
`test_evoxera_bot.py`. `main.py` gets one 11-line mount block at the very bottom.
The Paystack webhook, provider dispatch and retry jobs are untouched.

## Setup
1. Run the SQL migration in the Supabase SQL editor (adds 3 columns to `orders`, plus `wa_sessions` and `wa_alerts`).
2. Fly secrets (never commit them):

       fly secrets set WA_TOKEN=... WA_PHONE_NUMBER_ID=... WA_VERIFY_TOKEN=any-string \
           WA_APP_SECRET=... WA_OWNER_NUMBER=233537314125

3. Meta: callback URL `https://api.evosdata.xyz/whatsapp/cloud`, verify token = WA_VERIFY_TOKEN, subscribe to `messages`.
4. Deploy, then message the bot's number.

**Use a separate Meta app for this number, or at least keep it apart from the Nana Osompa bot's app.**
A Meta app has one webhook URL, so two numbers on one app would send both bots' messages to the same place.
(The Evoxera bot ignores messages addressed to a different phone number id, but the other bot would not.)

## Owner usage (from WA_OWNER_NUMBER)
- **Swipe-reply** to any alert (human requests, feedback, project requests) and the reply goes to that customer. The bot then stays quiet for 4 hours.
- Or write `@233XXXXXXXXX your message`.
- `bot` as a swipe-reply, or `/bot 233XXXXXXXXX`, hands the customer back to the bot.
- Send `hi` to the bot number now and then: WhatsApp stops delivering alerts after 24 hours of owner silence. The bot nudges you at 10, 15 and 18 hours.

## Things to know
- Free-form messages only reach people who messaged the bot in the last 24 hours. "Payment received" and "Data delivered" are free-form, so a customer who last wrote more than 24 hours before delivery will not get them. Approved message templates are the fix if that happens in practice.
- Prices always come from the live `prices` table; WhatsApp customers pay the normal customer price.
- Wording lives at the top of `evoxera_bot.py` (ABOUT_TEXT, HUB_TEXT, EVOSGPT_TEXT, XERA_TEXT, SOFTWARE_TEXT). It follows the company profile: nothing is claimed as live unless confirmed, and XERA never gets price or listing claims.
- `OTHER_PRODUCTS` is empty, which hides the "Other products" row. Add confirmed products there later.
- Run `python test_evoxera_bot.py` from the repo root (fake database, no network).
