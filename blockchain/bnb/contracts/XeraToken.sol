// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";

/// @title XeraToken (XERA) — BNB Smart Chain
/// @notice Standard fixed-supply BEP-20 token. Section 3 of the brief is explicit:
///         no locked balances inside balanceOf, no transfer restrictions, no
///         transfer taxes, no blacklist-based locking, no DEX-breaking logic.
///         The 25%/75% claim split and 6-month lock live entirely in
///         XeraMiningDistributor / XeraVesting — this contract has no idea
///         those concepts exist.
/// @dev Fixed supply minted once, in the constructor, to `initialHolder`
///      (the multisig-controlled vault). There is no mint() function
///      anywhere in this contract — supply cannot grow after deployment.
///      This is the entire supply-cap guarantee for the BNB side of XERA
///      (see PROJECT.md / XERA-smart-contract-architecture.md).
contract XeraToken is ERC20, ERC20Burnable, ERC20Permit {
    /// @param initialHolder Multisig vault address that receives the entire
    ///        BNB-side fixed supply at deployment (e.g. the Gnosis Safe
    ///        acting as XeraMasterVault). Allocation to Mining/Sale/
    ///        Community/Liquidity/Treasury buckets happens by that multisig
    ///        transferring out of its own balance — this contract does not
    ///        need to know about allocation buckets at all.
    /// @param bnbChainSupply The fixed BNB-side supply cap, in whole tokens
    ///        (18 decimals applied internally). This is deployment
    ///        configuration, NOT a hard-coded business assumption — see
    ///        README "BLOCKING DECISION" for why this is a constructor
    ///        argument rather than a constant.
    constructor(address initialHolder, uint256 bnbChainSupply)
        ERC20("Xera", "XERA")
        ERC20Permit("Xera")
    {
        require(initialHolder != address(0), "XeraToken: zero holder");
        require(bnbChainSupply > 0, "XeraToken: zero supply");
        _mint(initialHolder, bnbChainSupply * 10 ** decimals());
    }

    // Intentionally no overrides of _update/_beforeTokenTransfer — token
    // behaves as a plain ERC20/BEP-20 in every wallet, DEX, and CEX
    // integration. ERC20Permit gives gasless approvals (useful for the
    // claim UX) without touching transfer semantics.
}
