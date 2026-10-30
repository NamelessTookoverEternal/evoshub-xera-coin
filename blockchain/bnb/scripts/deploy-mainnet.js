const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const { checkConfig } = require("./lib/mainnet-checks");

/**
 * EVOXERA (XERA) — BNB Smart Chain MAINNET deployment.
 *
 *   Default is a DRY RUN: validates everything, estimates gas, sends nothing.
 *   To broadcast: XERA_MAINNET_BROADCAST=YES_DEPLOY_PERMANENTLY
 *
 * Guards (each exists because mainnet mistakes are permanent):
 *   - refuses unless connected to chain 56 (or XERA_REHEARSAL=true on a local network)
 *   - refuses if deployments/<network>.json already exists  -> never mints a second supply by accident
 *   - supply <= 500,000,000 and mining allocation <= 75,000,000, enforced here too
 *   - vault/governance/timelock must be contracts (multisig/timelock) unless XERA_ALLOW_EOA_ADMIN=true
 *   - deployer must not hold any role; claim signer must be its own dedicated key
 *   - after deploying, reads the chain back and checks name/symbol/supply/roles; fails loudly on any mismatch
 * The script never sends the follow-up multisig transactions; it prints them.
 * The deployer key is read by Hardhat from DEPLOYER_PRIVATE_KEY at run time; it is never printed or stored.
 */
async function main() {
  const { ethers, network } = hre;
  const env = process.env;
  const [deployer] = await ethers.getSigners();
  if (!deployer) throw new Error("No deployer account. Set DEPLOYER_PRIVATE_KEY in your shell (never commit it).");
  const chainId = Number((await ethers.provider.getNetwork()).chainId);

  const code = {};
  for (const [k, v] of Object.entries({ vault: env.XERA_VAULT_MULTISIG_ADDRESS, governance: env.XERA_GOVERNANCE_MULTISIG_ADDRESS, timelock: env.XERA_TIMELOCK_ADDRESS })) {
    code[k] = v && ethers.isAddress(v) ? await ethers.provider.getCode(v) : "0x";
  }
  const problems = checkConfig({ ethers, env, deployer: deployer.address, chainId, code });

  const outFile = path.join(__dirname, "..", "deployments", `${network.name}.json`);
  if (fs.existsSync(outFile)) problems.push(`${path.relative(process.cwd(), outFile)} already exists — a deployment was already recorded. Refusing to deploy a second token.`);

  if (problems.length) {
    console.error("\nPRE-FLIGHT FAILED — nothing was sent:");
    problems.forEach((p) => console.error("  x " + p));
    process.exit(1);
  }

  const supply = BigInt(env.XERA_BNB_CHAIN_SUPPLY);
  const miningAlloc = BigInt(env.XERA_MINING_ALLOCATION);
  const balance = await ethers.provider.getBalance(deployer.address);
  console.log(`Network: ${network.name} (chain ${chainId})`);
  console.log(`Deployer: ${deployer.address}  balance: ${ethers.formatEther(balance)} BNB`);
  console.log(`Token: EVOXERA / XERA   supply: ${supply} (to vault ${env.XERA_VAULT_MULTISIG_ADDRESS})`);
  console.log(`Mining allocation: ${miningAlloc}   claim signer: ${env.XERA_CLAIM_SIGNER_ADDRESS}`);
  console.log(`Governance: ${env.XERA_GOVERNANCE_MULTISIG_ADDRESS}   Timelock/admin: ${env.XERA_TIMELOCK_ADDRESS}`);

  const broadcast = env.XERA_MAINNET_BROADCAST === "YES_DEPLOY_PERMANENTLY";
  const Token = await ethers.getContractFactory("XeraToken");
  const Vesting = await ethers.getContractFactory("XeraVesting");
  const Dist = await ethers.getContractFactory("XeraMiningDistributor");

  if (!broadcast) {
    const est = await deployer.estimateGas(await Token.getDeployTransaction(env.XERA_VAULT_MULTISIG_ADDRESS, supply));
    const fee = (await ethers.provider.getFeeData()).gasPrice || 0n;
    console.log(`\nDRY RUN OK. Token deploy gas ≈ ${est} (≈ ${ethers.formatEther(est * fee)} BNB at current gas price); vesting + distributor cost similar or less.`);
    console.log("Nothing was sent. To broadcast: XERA_MAINNET_BROADCAST=YES_DEPLOY_PERMANENTLY");
    return;
  }

  const token = await Token.deploy(env.XERA_VAULT_MULTISIG_ADDRESS, supply);
  await token.waitForDeployment();
  const tokenAddr = await token.getAddress();
  console.log("XeraToken:", tokenAddr);

  const vesting = await Vesting.deploy(tokenAddr, env.XERA_TIMELOCK_ADDRESS, env.XERA_GOVERNANCE_MULTISIG_ADDRESS);
  await vesting.waitForDeployment();
  const vestingAddr = await vesting.getAddress();
  console.log("XeraVesting:", vestingAddr);

  const dist = await Dist.deploy(tokenAddr, vestingAddr, env.XERA_TIMELOCK_ADDRESS, env.XERA_GOVERNANCE_MULTISIG_ADDRESS,
    env.XERA_CLAIM_SIGNER_ADDRESS, ethers.parseUnits(miningAlloc.toString(), 18));
  await dist.waitForDeployment();
  const distAddr = await dist.getAddress();
  console.log("XeraMiningDistributor:", distAddr);

  // ---- read everything back from the chain; do not trust our own inputs ----
  const fail = [];
  const eq = (label, a, b) => { if (String(a).toLowerCase() !== String(b).toLowerCase()) fail.push(`${label}: expected ${b}, got ${a}`); };
  eq("token name", await token.name(), "EVOXERA");
  eq("token symbol", await token.symbol(), "XERA");
  eq("token decimals", await token.decimals(), 18);
  eq("total supply", await token.totalSupply(), ethers.parseUnits(supply.toString(), 18));
  eq("vault balance", await token.balanceOf(env.XERA_VAULT_MULTISIG_ADDRESS), ethers.parseUnits(supply.toString(), 18));
  eq("distributor maxAllocation", await dist.maxAllocation(), ethers.parseUnits(miningAlloc.toString(), 18));
  const ADMIN = ethers.ZeroHash;
  const GOV = await dist.GOVERNANCE_ROLE();
  const SIGNER = await dist.CLAIM_SIGNER_ROLE();
  const ok = async (c, role, who, want, label) => { if ((await c.hasRole(role, who)) !== want) fail.push(`${label}: hasRole=${!want}, expected ${want}`); };
  await ok(dist, ADMIN, env.XERA_TIMELOCK_ADDRESS, true, "distributor admin = timelock");
  await ok(dist, GOV, env.XERA_GOVERNANCE_MULTISIG_ADDRESS, true, "distributor governance = multisig");
  await ok(dist, SIGNER, env.XERA_CLAIM_SIGNER_ADDRESS, true, "distributor claim signer");
  await ok(dist, ADMIN, deployer.address, false, "deployer has NO distributor admin");
  await ok(dist, GOV, deployer.address, false, "deployer has NO distributor governance");
  await ok(dist, SIGNER, deployer.address, false, "deployer has NO claim-signer role");
  await ok(vesting, ADMIN, env.XERA_TIMELOCK_ADDRESS, true, "vesting admin = timelock");
  await ok(vesting, ADMIN, deployer.address, false, "deployer has NO vesting admin");

  const record = {
    chain: "bnb", network: network.name, chainId, token: { name: "EVOXERA", symbol: "XERA" },
    xeraToken: tokenAddr, xeraVesting: vestingAddr, xeraMiningDistributor: distAddr,
    supply: supply.toString(), miningAllocation: miningAlloc.toString(),
    deployer: deployer.address, deployedAt: new Date().toISOString(),
  };
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(record, null, 2) + "\n");
  console.log(`\nRecorded ${path.relative(process.cwd(), outFile)} (public addresses only).`);

  if (fail.length) {
    console.error("\nPOST-DEPLOY CHECKS FAILED — DO NOT OPEN CLAIMS:");
    fail.forEach((f) => console.error("  x " + f));
    process.exitCode = 1;
    return;
  }
  console.log("\nPost-deploy checks: all passed (name, symbol, supply, vault balance, maxAllocation, roles).");

  console.log("\n=== VERIFY ON BSCSCAN (run these) ===");
  console.log(`npx hardhat verify --network ${network.name} ${tokenAddr} ${env.XERA_VAULT_MULTISIG_ADDRESS} ${supply}`);
  console.log(`npx hardhat verify --network ${network.name} ${vestingAddr} ${tokenAddr} ${env.XERA_TIMELOCK_ADDRESS} ${env.XERA_GOVERNANCE_MULTISIG_ADDRESS}`);
  console.log(`npx hardhat verify --network ${network.name} ${distAddr} ${tokenAddr} ${vestingAddr} ${env.XERA_TIMELOCK_ADDRESS} ${env.XERA_GOVERNANCE_MULTISIG_ADDRESS} ${env.XERA_CLAIM_SIGNER_ADDRESS} ${ethers.parseUnits(miningAlloc.toString(), 18)}`);
  console.log("\n=== FOLLOW-UPS (from the multisigs, NOT the deployer key) ===");
  console.log(`1. Vault multisig transfers ${miningAlloc} XERA to the distributor ${distAddr}`);
  console.log(`2. Governance multisig calls vesting.grantRole(DEPOSITOR_ROLE, ${distAddr})`);
  console.log("3. Put the three addresses in Supabase xera_chain_config (BNB row) and set XERA_BNB_CHAIN_ID=56; keep onchain_enabled=false until the canary passes.");
}

main().catch((e) => { console.error(e); process.exitCode = 1; });
