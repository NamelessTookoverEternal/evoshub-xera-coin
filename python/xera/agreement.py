"""
XERA Miner Agreement - the one authoritative copy of the text.

The frontend renders exactly what GET /api/xera/launch/agreement returns and
sends back the version and SHA-256 it was shown. The server only records an
acceptance when BOTH match what it computes here, so a user can never "accept"
a different text from the one that is stored and hashed.

Changing ANY wording here changes AGREEMENT_SHA256. If the change is material
you must also:
  1. bump AGREEMENT_VERSION below, and
  2. set xera_launch_config.agreement_version to the same string
     (supabase/operations/xera_official_launch_final_update.sql does this for
     the launch version; later versions need a one-line UPDATE).
Users who accepted an older version are then asked to accept the new one,
because the database checks acceptance against the current version only.

If this module's version and the database's version ever disagree, the
backend refuses to take acceptances (see launch.py) rather than guessing.

Numbers in the text (reward tiers, 100 early miners, 100 XERA, 2 XERA daily)
must match the database. tests/test_launch.py checks the tiers against the
migration SQL so they cannot drift silently.
"""

import hashlib

AGREEMENT_VERSION = "xera-miner-agreement-2026-10-v1"
AGREEMENT_TITLE = "XERA Miner Agreement and Rules"
SUPPORT_EMAIL = "support@evoshub.xyz"

# (max active miners inclusive or None, base reward per 24-hour session).
# Mirrors xera_base_reward_for_active_miners() in
# supabase/migrations/20261021_xera_official_launch_v1.sql - verified by a test.
REWARD_TIERS = [
    (100, "10"),
    (200, "8"),
    (500, "5"),
    (1000, "3"),
    (1500, "2.5"),
    (2000, "2"),
    (3000, "1.5"),
    (None, "1"),
]


def _tier_lines() -> list[str]:
    lines = []
    low = 1
    for high, reward in REWARD_TIERS:
        if high is None:
            lines.append(f"More than {low - 1:,} active miners: {reward} XERA per 24-hour session")
        else:
            lines.append(f"{low:,} to {high:,} active miners: {reward} XERA per 24-hour session")
            low = high + 1
    return lines


SECTIONS: list[dict] = [
    {
        "title": "1. Introduction and scope",
        "paragraphs": [
            "XERA is a product within the EVOXERA TECHNOLOGY EVOS ecosystem. This agreement sets out the rules for taking part in XERA mining on the EVOS Hub. It applies to every account that starts a mining session.",
            "Please read it fully. You must accept the current version before you can start mining.",
        ],
    },
    {
        "title": "2. Mining participation and session duration",
        "paragraphs": [
            "One account may hold one active mining session at a time. A session runs for a fixed period set by the platform (currently 24 hours). When it ends you claim the reward for that session from within XERA.",
            "The reward for a session is fixed by the rules in section 3 when the session starts. Closing the app or leaving the page does not stop a session that has already started.",
            "Mining may be paused, limited or closed by the platform, for example when the mining allocation is nearly or fully distributed.",
        ],
    },
    {
        "title": "3. Base mining reward tiers",
        "paragraphs": [
            "The base reward for a session depends on how many mining sessions are active and unexpired at the moment your session starts, counting yours. Registered accounts without an active session are not counted.",
            *_tier_lines(),
            "The base reward is never below 1 XERA while the mining allocation lasts. The reward shown in the app is calculated by the platform; the app does not estimate it on its own. Paid hashrate or boosts, where offered, are separate from this base schedule.",
            "If less of the mining allocation remains than the scheduled reward, you receive only what remains.",
        ],
    },
    {
        "title": "4. Daily claims",
        "paragraphs": [
            "A separate daily claim is available once per calendar day (UTC) and is currently 2 XERA. It does not depend on your mining session. A daily claim cannot be repeated on the same day, and it counts against the same mining allocation as mining rewards.",
        ],
    },
    {
        "title": "5. Early-miner bonus eligibility and limits",
        "paragraphs": [
            "The first 100 eligible miners to start a mining session after you accept this agreement may receive a one-time bonus of 100 XERA, credited to the account once. The bonus is limited to 10,000 XERA in total and is taken from the existing mining allocation; it does not increase the planned supply.",
            "Eligibility is decided by the platform when your session is successfully created. Visiting the page, logging in, accepting this agreement, or restarting a session does not by itself earn a bonus, and a bonus cannot be received twice. If a session cannot be created, no bonus slot is used.",
            "The platform may decline or reverse a bonus where it finds duplicate accounts, automation or other abuse (see sections 7 and 12). Remaining bonus slots are shown in the app.",
        ],
    },
    {
        "title": "6. Account security",
        "paragraphs": [
            "You are responsible for keeping your EVOS account credentials private and for activity under your account. Tell us promptly if you think your account has been accessed without your permission. We will never ask for your password.",
        ],
    },
    {
        "title": "7. Prohibited automation, exploitation, duplicate accounts and reward manipulation",
        "paragraphs": [
            "You must not: use bots, scripts or other automation to start sessions or claims; create or control more than one account to receive rewards or bonuses; use someone else's account; exploit errors in the platform; interfere with the service; or try to obtain rewards in any way the platform did not intend.",
            "If you find a bug that gives rewards unintentionally, please report it to support instead of using it.",
        ],
    },
    {
        "title": "8. Test-data reset and future announced changes",
        "paragraphs": [
            "Balances, sessions, transactions and daily-claim progress from before the official launch were test data. They have been reset and do not carry over. Your account itself was kept.",
            "Rules, rewards, limits and features may change in the future. Material changes will be announced in the app, and where required you will be asked to accept an updated version of this agreement.",
        ],
    },
    {
        "title": "9. In-platform balances and on-chain tokens",
        "paragraphs": [
            "Your XERA mining balance is an in-platform balance recorded in the EVOS Hub. It is not a token on a blockchain. Showing a balance in the app does not mean tokens have been issued to a blockchain address.",
        ],
    },
    {
        "title": "10. Future on-chain claiming and eligibility",
        "paragraphs": [
            "On-chain claiming has not launched. If it launches, it will be governed by separate rules, requirements and timelines that will be announced beforehand, which may include checks on eligibility, wallet details and account good standing.",
            "Accepting this agreement or holding an in-platform balance does not by itself make you eligible to claim anything on-chain, and does not guarantee that you will be able to.",
        ],
    },
    {
        "title": "11. No guaranteed financial return, value, listing or liquidity",
        "paragraphs": [
            "XERA is not offered as an investment. We make no promise of profit, of any monetary value, of an exchange listing, or of liquidity or the ability to sell or transfer XERA. You take part in mining at your own discretion and should not rely on any future value.",
        ],
    },
    {
        "title": "12. Account restrictions, abuse investigations and review",
        "paragraphs": [
            "If we suspect a breach of this agreement, we may investigate, and may temporarily limit mining, claims or the wallet while we do. If we conclude that rewards were obtained in breach of section 7, we may remove those rewards and restrict or close the account.",
            "We will tell you the outcome and the main reason where we reasonably can. You can ask for a review by contacting support with your account details and any information you want us to consider, and we will have the decision looked at again. Nothing here limits any rights you have under applicable law.",
        ],
    },
    {
        "title": "13. Changes to this agreement",
        "paragraphs": [
            "We may update this agreement. Each version has an identifier, and your acceptance is recorded against the exact version and text you were shown. If a new version is materially different, you must accept it before you start another mining session.",
        ],
    },
    {
        "title": "14. Privacy and data handling",
        "paragraphs": [
            "When you accept, we record your account, the agreement version, a fingerprint (hash) of the text, the time, and technical details such as your IP address and browser type, to prove what was accepted and to protect the service against abuse. Mining and wallet activity is stored to run the service and keep accurate records. We do not publish private account information; public figures such as remaining bonus slots are aggregate only.",
        ],
    },
    {
        "title": "15. Support and contact details",
        "paragraphs": [
            f"For questions, security reports or review requests, contact {SUPPORT_EMAIL}.",
        ],
    },
    {
        "title": "16. Explicit acceptance",
        "paragraphs": [
            "To start mining you must scroll to the end of this agreement, tick the confirmation box and press the agree button. Scrolling alone is not acceptance, and closing this window does not start mining.",
            "By ticking the box you confirm that you have read and agree to this version of the XERA Miner Agreement and Rules.",
        ],
    },
]


def agreement_text() -> str:
    """Canonical plain text that is hashed. Stable for a given wording."""
    parts = [AGREEMENT_TITLE, f"Version: {AGREEMENT_VERSION}"]
    for section in SECTIONS:
        parts.append(section["title"])
        parts.extend(section["paragraphs"])
    return "\n\n".join(parts)


AGREEMENT_SHA256 = hashlib.sha256(agreement_text().encode("utf-8")).hexdigest()


def agreement_document() -> dict:
    return {
        "version": AGREEMENT_VERSION,
        "title": AGREEMENT_TITLE,
        "sha256": AGREEMENT_SHA256,
        "sections": SECTIONS,
        "contact": SUPPORT_EMAIL,
    }
