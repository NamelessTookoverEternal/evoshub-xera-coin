const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("XeraToken", function () {
  it("mints the exact fixed supply to the vault, once, at deployment", async function () {
    const [vault] = await ethers.getSigners();
    const Token = await ethers.getContractFactory("XeraToken");
    const supply = 425_000_000n; // example public-side figure for this chain, deployment-configured
    const token = await Token.deploy(vault.address, supply);
    await token.waitForDeployment();

    expect(await token.totalSupply()).to.equal(ethers.parseUnits(supply.toString(), 18));
    expect(await token.balanceOf(vault.address)).to.equal(ethers.parseUnits(supply.toString(), 18));
  });

  it("exposes no mint function — supply cannot grow after deployment", async function () {
    const Token = await ethers.getContractFactory("XeraToken");
    const iface = Token.interface;
    const hasMint = iface.fragments.some((f) => f.type === "function" && f.name === "mint");
    expect(hasMint).to.equal(false);
  });

  it("behaves as a standard transferable token with no restrictions", async function () {
    const [vault, alice, bob] = await ethers.getSigners();
    const Token = await ethers.getContractFactory("XeraToken");
    const token = await Token.deploy(vault.address, 1_000_000n);
    await token.waitForDeployment();

    await token.transfer(alice.address, ethers.parseUnits("100", 18));
    await token.connect(alice).transfer(bob.address, ethers.parseUnits("40", 18));

    expect(await token.balanceOf(bob.address)).to.equal(ethers.parseUnits("40", 18));
    expect(await token.balanceOf(alice.address)).to.equal(ethers.parseUnits("60", 18));
  });

  it("rejects a zero initial holder or zero supply", async function () {
    const Token = await ethers.getContractFactory("XeraToken");
    await expect(Token.deploy(ethers.ZeroAddress, 1000n)).to.be.revertedWith("XeraToken: zero holder");
    const [vault] = await ethers.getSigners();
    await expect(Token.deploy(vault.address, 0n)).to.be.revertedWith("XeraToken: zero supply");
  });
});
