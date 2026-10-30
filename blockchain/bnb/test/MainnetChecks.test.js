const { expect } = require("chai");
const { ethers } = require("hardhat");
const { checkConfig } = require("../scripts/lib/mainnet-checks");

describe("mainnet pre-flight checks", function () {
  const a = (n) => ethers.getAddress("0x" + n.toString(16).padStart(40, "0"));
  const base = () => ({
    XERA_BNB_CHAIN_SUPPLY: "500000000", XERA_MINING_ALLOCATION: "75000000",
    XERA_VAULT_MULTISIG_ADDRESS: a(1), XERA_GOVERNANCE_MULTISIG_ADDRESS: a(2),
    XERA_TIMELOCK_ADDRESS: a(3), XERA_CLAIM_SIGNER_ADDRESS: a(4),
  });
  const contractCode = { vault: "0x6000", governance: "0x6000", timelock: "0x6000" };
  const run = (env, over = {}) => checkConfig({ ethers, env, deployer: a(9), chainId: 56, code: contractCode, ...over });

  it("accepts a correct mainnet configuration", () => expect(run(base())).to.deep.equal([]));
  it("rejects missing values", () => { const e = base(); delete e.XERA_CLAIM_SIGNER_ADDRESS; expect(run(e).join()).to.contain("XERA_CLAIM_SIGNER_ADDRESS"); });
  it("rejects supply above 500,000,000", () => expect(run({ ...base(), XERA_BNB_CHAIN_SUPPLY: "500000001" }).join()).to.contain("hard maximum"));
  it("rejects mining allocation above 75,000,000", () => expect(run({ ...base(), XERA_MINING_ALLOCATION: "75000001" }).join()).to.contain("75000000"));
  it("rejects the deployer holding a role", () => expect(run({ ...base(), XERA_GOVERNANCE_MULTISIG_ADDRESS: a(9) }).join()).to.contain("must not be the deployer"));
  it("rejects a claim signer that doubles as an admin address", () => expect(run({ ...base(), XERA_CLAIM_SIGNER_ADDRESS: a(1) }).join()).to.contain("dedicated key"));
  it("rejects plain wallets as vault/governance/timelock unless explicitly allowed", () => {
    const eoa = { vault: "0x", governance: "0x", timelock: "0x" };
    expect(run(base(), { code: eoa }).join()).to.contain("no contract code");
    expect(run({ ...base(), XERA_ALLOW_EOA_ADMIN: "true" }, { code: eoa })).to.deep.equal([]);
  });
  it("refuses a non-mainnet chain unless rehearsing", () => {
    expect(run(base(), { chainId: 97 }).join()).to.contain("not BNB mainnet");
    expect(run({ ...base(), XERA_REHEARSAL: "true" }, { chainId: 31337 })).to.deep.equal([]);
  });
});
