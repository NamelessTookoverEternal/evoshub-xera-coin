/**
 * Pre-flight rules for the XERA (EVOXERA) BNB mainnet deployment. Pure functions so they can be
 * unit-tested without a network. Every rule here exists because a mistake is permanent on mainnet
 * (token name/symbol, supply, role holders cannot be undone by redeploying "the same" token).
 */
const MAX_TOTAL_SUPPLY = 500_000_000n;       // XERA tokenomics: hard maximum across all chains
const MAX_MINING_ALLOCATION = 75_000_000n;   // XERA tokenomics: mining allocation

function isAddress(ethers, v) {
  return typeof v === "string" && ethers.isAddress(v) && v.toLowerCase() !== ethers.ZeroAddress;
}

/** Returns a list of human-readable problems; empty list means the configuration is acceptable. */
function checkConfig({ ethers, env, deployer, chainId, code }) {
  const problems = [];
  const required = ["XERA_BNB_CHAIN_SUPPLY", "XERA_MINING_ALLOCATION", "XERA_VAULT_MULTISIG_ADDRESS",
    "XERA_GOVERNANCE_MULTISIG_ADDRESS", "XERA_TIMELOCK_ADDRESS", "XERA_CLAIM_SIGNER_ADDRESS"];
  for (const k of required) if (!env[k]) problems.push(`${k} is not set`);
  if (problems.length) return problems;

  const addrKeys = required.filter((k) => k.endsWith("_ADDRESS"));
  for (const k of addrKeys) if (!isAddress(ethers, env[k])) problems.push(`${k} is not a valid non-zero address`);

  let supply, mining;
  try { supply = BigInt(env.XERA_BNB_CHAIN_SUPPLY); } catch { problems.push("XERA_BNB_CHAIN_SUPPLY must be a whole number of tokens"); }
  try { mining = BigInt(env.XERA_MINING_ALLOCATION); } catch { problems.push("XERA_MINING_ALLOCATION must be a whole number of tokens"); }
  if (supply !== undefined) {
    if (supply <= 0n) problems.push("supply must be > 0");
    if (supply > MAX_TOTAL_SUPPLY) problems.push(`supply ${supply} exceeds the ${MAX_TOTAL_SUPPLY} hard maximum`);
  }
  if (mining !== undefined) {
    if (mining <= 0n) problems.push("mining allocation must be > 0");
    if (mining > MAX_MINING_ALLOCATION) problems.push(`mining allocation ${mining} exceeds the ${MAX_MINING_ALLOCATION} tokenomics allocation`);
    if (supply !== undefined && mining > supply) problems.push("mining allocation exceeds total supply");
  }
  if (problems.length) return problems;

  // Separation of duties: the key that deploys must not also hold any power afterwards.
  const roles = {
    vault: env.XERA_VAULT_MULTISIG_ADDRESS, governance: env.XERA_GOVERNANCE_MULTISIG_ADDRESS,
    timelock: env.XERA_TIMELOCK_ADDRESS, claimSigner: env.XERA_CLAIM_SIGNER_ADDRESS,
  };
  const lower = Object.fromEntries(Object.entries(roles).map(([k, v]) => [k, v.toLowerCase()]));
  const dep = deployer.toLowerCase();
  for (const [k, v] of Object.entries(lower)) if (v === dep) problems.push(`${k} must not be the deployer wallet`);
  if (lower.claimSigner === lower.vault || lower.claimSigner === lower.governance || lower.claimSigner === lower.timelock)
    problems.push("claim signer must be a dedicated key, not the vault/governance/timelock address");
  if (lower.vault === lower.governance) problems.push("vault and governance should be separate multisigs");

  // The vault receives the ENTIRE supply. A plain wallet (EOA) there is a single point of failure.
  const allowEoa = String(env.XERA_ALLOW_EOA_ADMIN || "").toLowerCase() === "true";
  for (const k of ["vault", "governance", "timelock"]) {
    const c = code[k];
    if ((!c || c === "0x") && !allowEoa) problems.push(`${k} address has no contract code (a plain wallet). Use a multisig/timelock, or set XERA_ALLOW_EOA_ADMIN=true to accept the risk`);
  }

  if (chainId !== 56 && String(env.XERA_REHEARSAL || "").toLowerCase() !== "true")
    problems.push(`connected to chain ${chainId}, not BNB mainnet (56). Use --network bscMainnet (or XERA_REHEARSAL=true on a local network)`);
  return problems;
}

module.exports = { checkConfig, MAX_TOTAL_SUPPLY, MAX_MINING_ALLOCATION };
