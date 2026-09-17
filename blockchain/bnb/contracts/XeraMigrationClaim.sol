// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

/// @title XeraMigrationClaim — ONE-TIME legacy pre-blockchain balance migration
/// @notice Section 10 of the brief. A single frozen snapshot of
///         `user_id -> legacy_balance` is taken off-chain at a chosen
///         cutoff, a Merkle tree is built over it, and only the root is
///         anchored here. Each leaf can be claimed exactly once, ever.
///         This contract is entirely separate from XeraMiningDistributor —
///         a legacy balance and a post-cutoff mining entitlement can never
///         collide because they are claimed through different contracts
///         with different identifier namespaces (leaf index here vs
///         reference_id there).
/// @dev Deliberately has no "add more leaves later" mechanism — the root is
///      set once at deployment and is immutable. A second migration
///      snapshot, if ever needed, is a new contract deployment with a new
///      root, not a mutation of this one.
contract XeraMigrationClaim is AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant GOVERNANCE_ROLE = keccak256("GOVERNANCE_ROLE");

    IERC20 public immutable xera;
    /// @notice Root of the frozen legacy-balance snapshot. Immutable —
    ///         set once at deployment, never updatable.
    bytes32 public immutable merkleRoot;
    /// @notice Sum of every leaf amount in the snapshot — the hard cap on
    ///         what this contract can ever pay out, independent of
    ///         `maxAllocation`-style checks elsewhere.
    uint256 public immutable totalSnapshotAmount;

    mapping(uint256 => bool) private _claimedBitmap; // leafIndex => claimed
    uint256 public totalClaimed;

    event LegacyClaimed(uint256 indexed leafIndex, address indexed account, uint256 amount);

    constructor(address xeraToken, bytes32 merkleRoot_, uint256 totalSnapshotAmount_, address admin, address governance) {
        require(xeraToken != address(0), "Migration: zero token");
        require(merkleRoot_ != bytes32(0), "Migration: zero root");
        require(admin != address(0) && governance != address(0), "Migration: zero address");
        xera = IERC20(xeraToken);
        merkleRoot = merkleRoot_;
        totalSnapshotAmount = totalSnapshotAmount_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(GOVERNANCE_ROLE, governance);
    }

    function isClaimed(uint256 leafIndex) public view returns (bool) {
        return _claimedBitmap[leafIndex];
    }

    /// @notice Claim a legacy balance. Leaf = keccak256(abi.encodePacked(leafIndex, account, amount)),
    ///         double-hashed per OpenZeppelin's standard "sorted pair" Merkle
    ///         convention to match the off-chain tree builder used to
    ///         generate `merkleRoot` (see migration_snapshot/build_tree.py).
    function claim(uint256 leafIndex, address account, uint256 amount, bytes32[] calldata proof)
        external
        whenNotPaused
        nonReentrant
    {
        require(!_claimedBitmap[leafIndex], "Migration: already claimed");

        bytes32 leaf = keccak256(bytes.concat(keccak256(abi.encode(leafIndex, account, amount))));
        require(MerkleProof.verify(proof, merkleRoot, leaf), "Migration: invalid proof");

        _claimedBitmap[leafIndex] = true;
        totalClaimed += amount;
        require(totalClaimed <= totalSnapshotAmount, "Migration: snapshot cap exceeded");

        xera.safeTransfer(account, amount);
        emit LegacyClaimed(leafIndex, account, amount);
    }

    function pause() external onlyRole(GOVERNANCE_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(GOVERNANCE_ROLE) {
        _unpause();
    }
}
