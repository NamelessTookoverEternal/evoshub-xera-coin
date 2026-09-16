const hre = require("hardhat");

/**
 * Deployment order matters: XeraToken must exist before XeraVesting and
 * XeraMiningDistributor (both take its address in their constructors), and
 * XeraVesting must exist before XeraMiningDistributor (same reason). After
 * deployment, the vault multisig must fund the distributor with exactly
 * `XERA_MINING_ALLOCATION` tokens and grant DEPOSITOR_ROLE on XeraVesting to
 * the distributor address — this script prints the exact follow-up
 * transactions rather than sending them, since those should be executed by
 * the multisig, not this deployer key (see section 14 of the brief).
 */
async function main() {
  const {
    XERA_BNB_CHAIN_SUPPLY,
    XERA_VAULT_MULTISIG_ADDRESS,
    XERA_GOVERNANCE_MULTISIG_ADDRESS,
    XERA_TIMELOCK_ADDRESS,
    XERA_CLAIM_SIGNER_ADDRESS,
    XERA_MINING_ALLOCATION,
  } = process.env;

  const missing = Object.entries({
    XERA_BNB_CHAIN_SUPPLY,
    XERA_VAULT_MULTISIG_ADDRESS,
    XERA_GOVERNANCE_MULTISIG_ADDRESS,
    XERA_TIMELOCK_ADDRESS,
    XERA_CLAIM_SIGNER_ADDRESS,
    XERA_MINING_ALLOCATION,
  }).filter(([, v]) => !v);

  if (missing.length) {
    console.error("Missing required env vars:", missing.map(([k]) => k).join(", "));
    console.error("See .env.example. Refusing to deploy with placeholder/guessed values.");
    process.exit(1);
  }

  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying with:", deployer.address);
  console.log("Network:", hre.network.name);

  const XeraToken = await hre.ethers.getContractFactory("XeraToken");
  const token = await XeraToken.deploy(XERA_VAULT_MULTISIG_ADDRESS, XERA_BNB_CHAIN_SUPPLY);
  await token.waitForDeployment();
  console.log("XeraToken:", await token.getAddress());

  const XeraVesting = await hre.ethers.getContractFactory("XeraVesting");
  const vesting = await XeraVesting.deploy(await token.getAddress(), XERA_TIMELOCK_ADDRESS, XERA_GOVERNANCE_MULTISIG_ADDRESS);
  await vesting.waitForDeployment();
  console.log("XeraVesting:", await vesting.getAddress());

  const XeraMiningDistributor = await hre.ethers.getContractFactory("XeraMiningDistributor");
  const distributor = await XeraMiningDistributor.deploy(
    await token.getAddress(),
    await vesting.getAddress(),
    XERA_TIMELOCK_ADDRESS,
    XERA_GOVERNANCE_MULTISIG_ADDRESS,
    XERA_CLAIM_SIGNER_ADDRESS,
    hre.ethers.parseUnits(XERA_MINING_ALLOCATION, 18)
  );
  await distributor.waitForDeployment();
  console.log("XeraMiningDistributor:", await distributor.getAddress());

  console.log("\n=== REQUIRED FOLLOW-UP (execute from the multisigs, not the deployer key) ===");
  console.log(`1. Vault multisig (${XERA_VAULT_MULTISIG_ADDRESS}) transfers ${XERA_MINING_ALLOCATION} XERA to distributor ${await distributor.getAddress()}`);
  console.log(`2. Governance multisig (${XERA_GOVERNANCE_MULTISIG_ADDRESS}) calls vesting.grantRole(DEPOSITOR_ROLE, ${await distributor.getAddress()})`);
  console.log("3. Confirm distributor.domainSeparator() output is wired into the backend's EIP-712 signer config");
  console.log("\nDeployment addresses (save to Supabase xera_chain_config / backend .env):");
  console.log(JSON.stringify({
    chain: "bnb",
    network: hre.network.name,
    xeraToken: await token.getAddress(),
    xeraVesting: await vesting.getAddress(),
    xeraMiningDistributor: await distributor.getAddress(),
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
