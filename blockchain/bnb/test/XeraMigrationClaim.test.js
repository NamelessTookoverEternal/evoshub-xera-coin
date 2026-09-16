const { expect } = require("chai");
const { ethers } = require("hardhat");
const { buildTree } = require("./helpers/merkle");

describe("XeraMigrationClaim", function () {
  async function deployFixture() {
    const [admin, governance, alice, bob, stranger] = await ethers.getSigners();

    const entries = [
      { leafIndex: 0n, account: alice.address, amount: ethers.parseUnits("500", 18) },
      { leafIndex: 1n, account: bob.address, amount: ethers.parseUnits("1500", 18) },
    ];
    const total = entries.reduce((sum, e) => sum + e.amount, 0n);
    const tree = buildTree(entries);

    const Token = await ethers.getContractFactory("XeraToken");
    const token = await Token.deploy(admin.address, 1_000_000n);
    await token.waitForDeployment();

    const Migration = await ethers.getContractFactory("XeraMigrationClaim");
    const migration = await Migration.deploy(await token.getAddress(), tree.root, total, admin.address, governance.address);
    await migration.waitForDeployment();

    await token.connect(admin).transfer(await migration.getAddress(), total);

    return { admin, governance, alice, bob, stranger, token, migration, entries, tree };
  }

  it("lets a user claim their exact snapshotted legacy balance with a valid proof", async function () {
    const f = await deployFixture();
    const entry = f.entries[0];
    const proof = f.tree.getProof(0);

    await expect(f.migration.connect(f.alice).claim(entry.leafIndex, entry.account, entry.amount, proof))
      .to.emit(f.migration, "LegacyClaimed")
      .withArgs(entry.leafIndex, entry.account, entry.amount);

    expect(await f.token.balanceOf(f.alice.address)).to.equal(entry.amount);
  });

  it("rejects a second claim of the same leaf", async function () {
    const f = await deployFixture();
    const entry = f.entries[0];
    const proof = f.tree.getProof(0);
    await f.migration.connect(f.alice).claim(entry.leafIndex, entry.account, entry.amount, proof);

    await expect(f.migration.connect(f.alice).claim(entry.leafIndex, entry.account, entry.amount, proof))
      .to.be.revertedWith("Migration: already claimed");
  });

  it("rejects a tampered amount against a valid proof", async function () {
    const f = await deployFixture();
    const entry = f.entries[0];
    const proof = f.tree.getProof(0);

    await expect(
      f.migration.connect(f.alice).claim(entry.leafIndex, entry.account, entry.amount + 1n, proof)
    ).to.be.revertedWith("Migration: invalid proof");
  });

  it("rejects a proof used for the wrong account", async function () {
    const f = await deployFixture();
    const entry = f.entries[0];
    const proof = f.tree.getProof(0);

    await expect(
      f.migration.connect(f.stranger).claim(entry.leafIndex, f.stranger.address, entry.amount, proof)
    ).to.be.revertedWith("Migration: invalid proof");
  });

  it("pause blocks legacy claims", async function () {
    const f = await deployFixture();
    await f.migration.connect(f.governance).pause();
    const entry = f.entries[0];
    const proof = f.tree.getProof(0);

    await expect(
      f.migration.connect(f.alice).claim(entry.leafIndex, entry.account, entry.amount, proof)
    ).to.be.revertedWithCustomError(f.migration, "EnforcedPause");
  });

  it("has no mechanism to add leaves after deployment (root is immutable)", async function () {
    const Migration = await ethers.getContractFactory("XeraMigrationClaim");
    const hasSetRoot = Migration.interface.fragments.some((f) => f.type === "function" && f.name.toLowerCase().includes("setroot"));
    expect(hasSetRoot).to.equal(false);
  });
});
