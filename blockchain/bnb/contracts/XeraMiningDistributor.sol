// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

interface IXeraVestingDeposit {
    function deposit(address user, uint256 amount, bytes32 referenceId) external;
}

/// @title XeraMiningDistributor — BNB settlement layer for Supabase-finalized mining entitlements
/// @notice Section 4/5 of the brief: this contract NEVER calculates mining
///         rates, active miners, remaining allocation, or reward amounts.
///         Supabase finalizes an entitlement and the backend's ClaimSigner
///         key signs an EIP-712 typed message authorizing exactly one
///         on-chain settlement of it. This contract's only job is to
///         verify that signature, enforce the fixed on-chain mining cap,
///         split 25/75, and pay out.
/// @dev Cross-chain double-claim protection (section 17): this contract can
///      only ever see BNB-side state. It cannot know whether `referenceId`
///      was already consumed on TON. That guarantee is enforced by the
///      backend (an atomic Supabase reservation — see
///      xera_reserve_onchain_claim in the migration — that marks a
///      reference_id "reserved" for exactly one chain before the signer
///      will ever sign for it). This contract's `consumed` mapping is the
///      second, independent layer: even a leaked/replayed signature for an
///      already-settled reference_id can never be submitted twice *on this
///      chain*.
contract XeraMiningDistributor is AccessControl, Pausable, ReentrancyGuard, EIP712 {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;

    bytes32 public constant CLAIM_SIGNER_ROLE = keccak256("CLAIM_SIGNER_ROLE"); // backend signer key only
    bytes32 public constant GOVERNANCE_ROLE = keccak256("GOVERNANCE_ROLE");     // multisig/timelock

    // 25% immediately transferable / 75% locked — section 2/3 of the brief.
    // Expressed as basis points so the split itself is auditable on-chain,
    // not a magic literal buried in arithmetic.
    uint16 public constant TRANSFERABLE_BPS = 2500;
    uint16 public constant LOCKED_BPS = 7500;
    uint16 private constant BPS_DENOMINATOR = 10000;

    bytes32 private constant CLAIM_TYPEHASH = keccak256(
        "Claim(address user,uint256 amount,bytes32 referenceId,uint256 deadline)"
    );

    IERC20 public immutable xera;
    IXeraVestingDeposit public immutable vesting;

    /// @notice Hard on-chain cap for everything this distributor may ever
    ///         pay out — independent enforcement of the 75,000,000 XERA
    ///         mining allocation (section 12), on top of (not instead of)
    ///         Supabase's own allocation accounting.
    uint256 public immutable maxAllocation;
    uint256 public totalDistributed;

    /// @dev referenceId => consumed. A reference_id consumed here can never
    ///      be submitted again, on this chain, under any signature.
    mapping(bytes32 => bool) public consumed;

    event ClaimSettled(address indexed user, bytes32 indexed referenceId, uint256 totalAmount, uint256 transferable, uint256 locked);
    event SignerRotated(address indexed oldSigner, address indexed newSigner);

    constructor(
        address xeraToken,
        address vestingContract,
        address admin,
        address governance,
        address initialSigner,
        uint256 maxAllocation_
    ) EIP712("XeraMiningDistributor", "1") {
        require(xeraToken != address(0) && vestingContract != address(0), "Distributor: zero address");
        require(admin != address(0) && governance != address(0) && initialSigner != address(0), "Distributor: zero address");
        require(maxAllocation_ > 0, "Distributor: zero allocation");

        xera = IERC20(xeraToken);
        vesting = IXeraVestingDeposit(vestingContract);
        maxAllocation = maxAllocation_;

        _grantRole(DEFAULT_ADMIN_ROLE, admin);   // admin = timelock/multisig — role management only
        _grantRole(GOVERNANCE_ROLE, governance);
        _grantRole(CLAIM_SIGNER_ROLE, initialSigner);
    }

    /// @notice Settle a finalized mining entitlement. Anyone can submit the
    ///         transaction (typically the user's own wallet, gas paid by
    ///         them), but only a signature from an address holding
    ///         CLAIM_SIGNER_ROLE authorizes the amount — this contract
    ///         trusts the signature, never the caller.
    function claim(address user, uint256 amount, bytes32 referenceId, uint256 deadline, bytes calldata signature)
        external
        whenNotPaused
        nonReentrant
    {
        require(block.timestamp <= deadline, "Distributor: claim expired");
        require(!consumed[referenceId], "Distributor: reference already consumed");
        require(amount > 0, "Distributor: zero amount");

        bytes32 structHash = keccak256(abi.encode(CLAIM_TYPEHASH, user, amount, referenceId, deadline));
        address recovered = _hashTypedDataV4(structHash).recover(signature);
        require(hasRole(CLAIM_SIGNER_ROLE, recovered), "Distributor: invalid signature");

        require(totalDistributed + amount <= maxAllocation, "Distributor: mining cap exceeded");

        // Effects before interactions.
        consumed[referenceId] = true;
        totalDistributed += amount;

        uint256 transferable = (amount * TRANSFERABLE_BPS) / BPS_DENOMINATOR;
        uint256 locked = amount - transferable; // remainder, avoids rounding leaving dust unaccounted

        xera.safeTransfer(user, transferable);

        xera.forceApprove(address(vesting), locked);
        IXeraVestingDeposit(address(vesting)).deposit(user, locked, referenceId);

        emit ClaimSettled(user, referenceId, amount, transferable, locked);
    }

    /// @notice EIP-712 domain separator, exposed for the backend/frontend to
    ///         construct signatures against without guessing chain/contract
    ///         details.
    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    // --- Governance-only admin surface ---

    /// @notice Rotate the backend signing key. Governance (multisig/timelock)
    ///         only — the old key is revoked in the same call so there is
    ///         never a window with two simultaneously-valid signers unless
    ///         governance explicitly grants a second one.
    function rotateSigner(address oldSigner, address newSigner) external onlyRole(GOVERNANCE_ROLE) {
        require(newSigner != address(0), "Distributor: zero signer");
        _revokeRole(CLAIM_SIGNER_ROLE, oldSigner);
        _grantRole(CLAIM_SIGNER_ROLE, newSigner);
        emit SignerRotated(oldSigner, newSigner);
    }

    function pause() external onlyRole(GOVERNANCE_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(GOVERNANCE_ROLE) {
        _unpause();
    }

    /// @notice Recover tokens sent here by mistake (NOT the XERA this
    ///         contract is funded with for payouts — governance cannot use
    ///         this to drain claim funds; it can only be used pre-funding
    ///         or for unrelated tokens accidentally sent to this address).
    ///         Explicitly excluded: `xera` itself, to avoid this becoming a
    ///         disguised withdrawal path for funds earmarked for claims.
    function rescueForeignToken(address token, address to, uint256 amount) external onlyRole(GOVERNANCE_ROLE) {
        require(token != address(xera), "Distributor: cannot rescue XERA");
        IERC20(token).safeTransfer(to, amount);
    }
}
