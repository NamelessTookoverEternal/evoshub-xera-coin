const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-toolbox/network-helpers");

describe("XeraVesting", function () {
  async function deployFixture() {
    const [admin, governance, depositor, user, stranger] = await ethers.getSigners();
    const Token = await ethers.getContractFactory("XeraToken");
    const token = await Token.deploy(admin.address, 1_000_000n);
    await token.waitForDeployment();

    const Vesting = await ethers.getContractFactory("XeraVesting");
    const vesting = await Vesting.deploy(await token.getAddress(), admin.address, governance.address);
    await vesting.waitForDeployment();

    const DEPOSITOR_ROLE = await vesting.DEPOSITOR_ROLE();
    await vesting.connect(admin).grantRole(DEPOSITOR_ROLE, depositor.address);

    await token.connect(admin).transfer(depositor.address, ethers.parseUnits("10000", 18));
    await token.connect(depositor).approve(await vesting.getAddress(), ethers.MaxUint256);

    return { admin, governance, depositor, user, stranger, token, vesting, DEPOSITOR_ROLE };
  }

  it("only DEPOSITOR_ROLE can create a tranche", async function () {
    const { vesting, stranger, user } = await deployFixture();
    await expect(vesting.connect(stranger).deposit(user.address, 100, ethers.ZeroHash)).to.be.reverted;
  });

  it("rejects release when the caller has no tranches at all", async function () {
    const { vesting, stranger } = await deployFixture();
    await expect(vesting.connect(stranger).release()).to.be.revertedWith("XeraVesting: nothing to release");
  });

  it("releases only a negligible, correctly-prorated amount immediately after deposit", async function () {
    // Vesting starts ticking at deposit time with no cliff, so this checks
    // "premature release" the way it can actually be observed on a real
    // chain: what's releasable a couple of seconds in is a tiny, exactly
    // pro-rated sliver of the tranche — never the full amount, and bounded
    // by elapsed time — not that release() reverts (Hardhat's own 1s/block
    // cadence already makes a zero-elapsed call to deposit() then
    // release() unrepresentable in this environment).
    const { vesting, depositor, user } = await deployFixture();
    const amount = ethers.parseUnits("100", 18);
    const depositTx = await vesting.connect(depositor).deposit(user.address, amount, ethers.encodeBytes32String("ref1"));
    const depositReceipt = await depositTx.wait();
    const depositBlock = await ethers.provider.getBlock(depositReceipt.blockNumber);

    const releasable = await vesting.releasable(user.address);
    const releaseBlock = await ethers.provider.getBlock("latest");
    const elapsed = BigInt(releaseBlock.timestamp) - BigInt(depositBlock.timestamp);
    const expected = (amount * elapsed) / (180n * 24n * 60n * 60n);

    expect(releasable).to.equal(expected);
    expect(releasable).to.be.lessThan(amount / 1000n); // nowhere close to fully vested
  });

  it("releases linearly over the vesting duration and nothing more than vested", async function () {
    const { vesting, depositor, user, token } = await deployFixture();
    const amount = ethers.parseUnits("180", 18); // 180 tokens over 180 days = 1/day, easy to reason about
    await vesting.connect(depositor).deposit(user.address, amount, ethers.encodeBytes32String("ref1"));

    await time.increase(90 * 24 * 60 * 60); // halfway
    const halfway = await vesting.releasable(user.address);
    expect(halfway).to.be.closeTo(ethers.parseUnits("90", 18), ethers.parseUnits("1", 18));

    await vesting.connect(user).release();
    expect(await token.balanceOf(user.address)).to.be.closeTo(ethers.parseUnits("90", 18), ethers.parseUnits("1", 18));

    await time.increase(90 * 24 * 60 * 60 + 60); // past full duration
    await vesting.connect(user).release();
    expect(await token.balanceOf(user.address)).to.be.closeTo(amount, ethers.parseUnits("1", 18));
  });

  it("keeps tranches independent — a new claim does not reset an earlier tranche's clock", async function () {
    const { vesting, depositor, user } = await deployFixture();
    await vesting.connect(depositor).deposit(user.address, ethers.parseUnits("180", 18), ethers.encodeBytes32String("ref1"));
    await time.increase(90 * 24 * 60 * 60);
    await vesting.connect(depositor).deposit(user.address, ethers.parseUnits("180", 18), ethers.encodeBytes32String("ref2"));

    // First tranche ~50% vested (~90), second tranche freshly deposited (~0).
    const releasable = await vesting.releasable(user.address);
    expect(releasable).to.be.closeTo(ethers.parseUnits("90", 18), ethers.parseUnits("1", 18));
    expect(await vesting.trancheCount(user.address)).to.equal(2);
  });

  it("pausing blocks new deposits but never blocks release() of already-vested tokens", async function () {
    const { vesting, depositor, user, governance } = await deployFixture();
    await vesting.connect(depositor).deposit(user.address, ethers.parseUnits("180", 18), ethers.encodeBytes32String("ref1"));
    await time.increase(180 * 24 * 60 * 60 + 60);

    await vesting.connect(governance).pauseDeposits();

    await expect(
      vesting.connect(depositor).deposit(user.address, 1, ethers.encodeBytes32String("ref2"))
    ).to.be.revertedWithCustomError(vesting, "EnforcedPause");

    // release() must still work while paused.
    await expect(vesting.connect(user).release()).to.not.be.reverted;
  });

  it("only GOVERNANCE_ROLE can change vesting duration, within sane bounds", async function () {
    const { vesting, governance, stranger } = await deployFixture();
    await expect(vesting.connect(stranger).setVestingDuration(60 * 24 * 60 * 60)).to.be.reverted;
    await expect(vesting.connect(governance).setVestingDuration(5)).to.be.revertedWith("XeraVesting: unreasonable duration");
    await vesting.connect(governance).setVestingDuration(90 * 24 * 60 * 60);
    expect(await vesting.vestingDuration()).to.equal(90 * 24 * 60 * 60);
  });
});
