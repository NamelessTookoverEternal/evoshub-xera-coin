const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-toolbox/network-helpers");

async function signClaim(signer, verifyingContract, chainId, claim) {
  const domain = { name: "XeraMiningDistributor", version: "1", chainId, verifyingContract };
  const types = {
    Claim: [
      { name: "user", type: "address" },
      { name: "amount", type: "uint256" },
      { name: "referenceId", type: "bytes32" },
      { name: "deadline", type: "uint256" },
    ],
  };
  return signer.signTypedData(domain, types, claim);
}

describe("XeraMiningDistributor", function () {
  async function deployFixture() {
    const [admin, governance, signer, otherSigner, user, stranger] = await ethers.getSigners();

    const Token = await ethers.getContractFactory("XeraToken");
    const token = await Token.deploy(admin.address, 1_000_000n);
    await token.waitForDeployment();

    const Vesting = await ethers.getContractFactory("XeraVesting");
    const vesting = await Vesting.deploy(await token.getAddress(), admin.address, governance.address);
    await vesting.waitForDeployment();

    const maxAllocation = ethers.parseUnits("75000000", 18);
    const Distributor = await ethers.getContractFactory("XeraMiningDistributor");
    const distributor = await Distributor.deploy(
      await token.getAddress(),
      await vesting.getAddress(),
      admin.address,
      governance.address,
      signer.address,
      maxAllocation
    );
    await distributor.waitForDeployment();

    const DEPOSITOR_ROLE = await vesting.DEPOSITOR_ROLE();
    await vesting.connect(admin).grantRole(DEPOSITOR_ROLE, await distributor.getAddress());

    // Fund distributor with its full mining allocation, as the vault multisig would.
    await token.connect(admin).transfer(await distributor.getAddress(), ethers.parseUnits("1000000", 18));

    const chainId = (await ethers.provider.getNetwork()).chainId;

    return { admin, governance, signer, otherSigner, user, stranger, token, vesting, distributor, chainId };
  }

  async function buildClaim({ distributor, chainId, user, amount, referenceId, deadline, signer }) {
    const claim = { user: user.address, amount, referenceId, deadline };
    const signature = await signClaim(signer, await distributor.getAddress(), chainId, claim);
    return { claim, signature };
  }

  it("settles a valid signed claim with an exact 25/75 split", async function () {
    const f = await deployFixture();
    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-1");
    const { signature } = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.signer });

    await expect(f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, signature))
      .to.emit(f.distributor, "ClaimSettled")
      .withArgs(f.user.address, referenceId, amount, ethers.parseUnits("250", 18), ethers.parseUnits("750", 18));

    expect(await f.token.balanceOf(f.user.address)).to.equal(ethers.parseUnits("250", 18));
    expect(await f.vesting.lockedRemaining(f.user.address)).to.equal(ethers.parseUnits("750", 18));
  });

  it("rejects an invalid signature (wrong signer)", async function () {
    const f = await deployFixture();
    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-2");
    const { signature } = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.otherSigner });

    await expect(
      f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, signature)
    ).to.be.revertedWith("Distributor: invalid signature");
  });

  it("rejects a modified amount (signature no longer matches)", async function () {
    const f = await deployFixture();
    const signedAmount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-3");
    const { signature } = await buildClaim({ ...f, amount: signedAmount, referenceId, deadline, signer: f.signer });

    await expect(
      f.distributor.connect(f.user).claim(f.user.address, ethers.parseUnits("2000", 18), referenceId, deadline, signature)
    ).to.be.revertedWith("Distributor: invalid signature");
  });

  it("rejects a modified user (signature no longer matches)", async function () {
    const f = await deployFixture();
    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-4");
    const { signature } = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.signer });

    await expect(
      f.distributor.connect(f.stranger).claim(f.stranger.address, amount, referenceId, deadline, signature)
    ).to.be.revertedWith("Distributor: invalid signature");
  });

  it("rejects a modified reference_id (signature no longer matches)", async function () {
    const f = await deployFixture();
    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-5");
    const otherRef = ethers.encodeBytes32String("session-5-tampered");
    const { signature } = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.signer });

    await expect(
      f.distributor.connect(f.user).claim(f.user.address, amount, otherRef, deadline, signature)
    ).to.be.revertedWith("Distributor: invalid signature");
  });

  it("rejects an expired claim", async function () {
    const f = await deployFixture();
    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 10;
    const referenceId = ethers.encodeBytes32String("session-6");
    const { signature } = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.signer });

    await time.increase(20);

    await expect(
      f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, signature)
    ).to.be.revertedWith("Distributor: claim expired");
  });

  it("rejects a replayed / duplicate reference_id claim", async function () {
    const f = await deployFixture();
    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-7");
    const { signature } = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.signer });

    await f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, signature);
    await expect(
      f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, signature)
    ).to.be.revertedWith("Distributor: reference already consumed");
  });

  it("enforces the mining allocation cap independently on-chain", async function () {
    const f = await deployFixture();
    const amount = ethers.parseUnits("75000001", 18); // 1 token over the 75,000,000 cap
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-8");
    const { signature } = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.signer });

    await expect(
      f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, signature)
    ).to.be.revertedWith("Distributor: mining cap exceeded");
  });

  it("pause blocks new claims; unpause restores them", async function () {
    const f = await deployFixture();
    await f.distributor.connect(f.governance).pause();

    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-9");
    const { signature } = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.signer });

    await expect(
      f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, signature)
    ).to.be.revertedWithCustomError(f.distributor, "EnforcedPause");

    await f.distributor.connect(f.governance).unpause();
    await expect(f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, signature)).to.not.be.reverted;
  });

  it("only GOVERNANCE_ROLE can pause, unpause, or rotate signer", async function () {
    const f = await deployFixture();
    await expect(f.distributor.connect(f.stranger).pause()).to.be.reverted;
    await expect(f.distributor.connect(f.stranger).rotateSigner(f.signer.address, f.otherSigner.address)).to.be.reverted;
  });

  it("signer rotation revokes the old signer and activates the new one atomically", async function () {
    const f = await deployFixture();
    await f.distributor.connect(f.governance).rotateSigner(f.signer.address, f.otherSigner.address);

    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-10");

    // Old signer no longer authorized.
    const oldSig = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.signer });
    await expect(
      f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, oldSig.signature)
    ).to.be.revertedWith("Distributor: invalid signature");

    // New signer works.
    const newSig = await buildClaim({ ...f, amount, referenceId, deadline, signer: f.otherSigner });
    await expect(f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, newSig.signature)).to.not.be.reverted;
  });

  it("a signature is bound to this contract's address (contract confusion protection)", async function () {
    const f = await deployFixture();
    const amount = ethers.parseUnits("1000", 18);
    const deadline = (await time.latest()) + 3600;
    const referenceId = ethers.encodeBytes32String("session-11");

    // Sign against a different (wrong) verifying contract address.
    const wrongDomainSig = await signClaim(f.signer, f.stranger.address, f.chainId, {
      user: f.user.address, amount, referenceId, deadline,
    });

    await expect(
      f.distributor.connect(f.user).claim(f.user.address, amount, referenceId, deadline, wrongDomainSig)
    ).to.be.revertedWith("Distributor: invalid signature");
  });

  it("admin cannot arbitrarily withdraw XERA via the foreign-token rescue path", async function () {
    const f = await deployFixture();
    await expect(
      f.distributor.connect(f.governance).rescueForeignToken(await f.token.getAddress(), f.governance.address, 1)
    ).to.be.revertedWith("Distributor: cannot rescue XERA");
  });
});
