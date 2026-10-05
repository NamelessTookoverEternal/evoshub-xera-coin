// BNB wallet picker (Reown AppKit / WalletConnect).
//
// Gives the BNB card the same experience TonConnect gives TON: one button opens
// a modal listing wallets (MetaMask, Trust, Binance, …) with deep links on
// mobile and a QR code on desktop. Installed browser wallets show up in it too.
//
// This module only OBTAINS an EIP-1193 provider. Ownership is still proven by
// the existing nonce + personal_sign flow in xera-chain.js — nothing about the
// backend or the verification rules changes. No seed phrase / private key is
// ever requested.
//
// Loaded lazily (dynamic import) so the large AppKit bundle is not part of the
// initial page weight. If VITE_REOWN_PROJECT_ID is unset or AppKit fails to
// load, xera-chain.js falls back to the browser-injected wallet flow.

const PROJECT_ID = (import.meta.env && import.meta.env.VITE_REOWN_PROJECT_ID) || '';

let modalPromise = null;
let modalRef = null;

export function appKitConfigured() { return Boolean(PROJECT_ID); }

// `expectedChainId` is the chain id the backend expects (56 mainnet / 97 testnet).
async function getModal(expectedChainId) {
    if (modalPromise) return modalPromise;
    modalPromise = (async () => {
        const [{ createAppKit }, { EthersAdapter }, networks] = await Promise.all([
            import('@reown/appkit'),
            import('@reown/appkit-adapter-ethers'),
            import('@reown/appkit/networks'),
        ]);
        const { bsc, bscTestnet } = networks;
        const ordered = Number(expectedChainId) === 56 ? [bsc, bscTestnet] : [bscTestnet, bsc];
        const modal = createAppKit({
            adapters: [new EthersAdapter()],
            networks: ordered,
            defaultNetwork: ordered[0],
            projectId: PROJECT_ID,
            metadata: {
                name: 'XERA',
                description: 'XERA by EVOXERA Technology',
                url: location.origin,
                icons: [`${location.origin}/assets/icons/xera-icon-192.png`],
            },
            // Wallet connection only — no email/social login, on-ramp, swaps or analytics.
            features: { analytics: false, email: false, socials: false, onramp: false, swaps: false, send: false, receive: false, history: false },
            themeMode: 'dark',
            allWallets: 'SHOW',
        });
        modalRef = modal;
        return modal;
    })();
    modalPromise.catch(() => { modalPromise = null; });
    return modalPromise;
}

// Opens the picker and resolves once the user has connected a wallet.
// Resolves { provider, address, chainId } or throws if they close it without connecting.
export async function connectWithAppKit(expectedChainId) {
    const modal = await getModal(expectedChainId);

    // Start from a clean session so the address we sign for is the one the user
    // picks NOW, not a leftover session from an earlier visit.
    try { if (modal.getIsConnectedState()) await modal.disconnect(); } catch (_e) { /* nothing to disconnect */ }

    return new Promise((resolve, reject) => {
        let settled = false;
        const finish = (fn, value) => {
            if (settled) return;
            settled = true;
            try { unsubAccount(); } catch (_e) { /* ignore */ }
            try { unsubState(); } catch (_e) { /* ignore */ }
            fn(value);
        };
        const unsubAccount = modal.subscribeAccount((acct) => {
            if (acct && acct.isConnected && acct.address) {
                const provider = modal.getWalletProvider();
                if (!provider) return;
                const cid = Number(modal.getChainId());
                // Give the modal a beat to close itself, then hand control back.
                setTimeout(() => { try { modal.close(); } catch (_e) { /* already closed */ } }, 150);
                finish(resolve, { provider, address: acct.address, chainId: Number.isFinite(cid) ? cid : null });
            }
        });
        const unsubState = modal.subscribeState((s) => {
            // Closed without a connection -> stop showing "Working…".
            if (s && s.open === false) {
                setTimeout(() => {
                    if (!settled && !modal.getIsConnectedState()) finish(reject, Object.assign(new Error('Wallet connection was cancelled.'), { cancelled: true }));
                }, 400);
            }
        });
        modal.open({ view: 'Connect', namespace: 'eip155' }).catch((e) => finish(reject, e));
    });
}

// A WalletConnect session from an earlier visit (AppKit persists it). Used by
// claim settlement after a page reload so the user isn't forced to reconnect.
export async function restoredAppKitProvider(expectedChainId) {
    if (!PROJECT_ID) return null;
    try {
        const modal = await getModal(expectedChainId);
        // Session restore is async — wait briefly for it.
        for (let i = 0; i < 10; i++) {
            if (modal.getIsConnectedState() && modal.getWalletProvider()) break;
            await new Promise((r) => setTimeout(r, 200));
        }
        if (!modal.getIsConnectedState()) return null;
        const provider = modal.getWalletProvider();
        const address = modal.getAddress('eip155');
        if (!provider || !address) return null;
        const cid = Number(modal.getChainId());
        return { provider, address, chainId: Number.isFinite(cid) ? cid : null };
    } catch (_e) { return null; }
}

export async function disconnectAppKit() {
    if (!modalRef) return;
    try { await modalRef.disconnect(); } catch (_e) { /* already gone */ }
}

// Ask the wallet to move to the expected BNB network via AppKit (works for WalletConnect sessions).
export async function switchAppKitNetwork(chainId) {
    if (!modalRef) return false;
    const networks = await import('@reown/appkit/networks');
    const target = Number(chainId) === 56 ? networks.bsc : networks.bscTestnet;
    await modalRef.switchNetwork(target);
    return true;
}
