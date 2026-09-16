// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title XeraVesting — the 75% locked leg of every mining claim (BNB side)
/// @notice XeraMiningDistributor deposits the locked 75% of each claim here
///         as an independent per-claim "tranche" for the user. XeraVesting
///         never mints, burns, or moves tokens it wasn't handed — it only
///         escrows deposited tokens and releases them on a schedule
///         (section 4/15 of the brief).
/// @dev Deliberately a separate contract from XeraToken (section 3): the
///      token itself has no concept of "locked" — this contract holding a
///      normal token balance and deciding when a user may withdraw it is
///      the entire locking mechanism.
///
///      Each mining claim creates its own tranche rather than merging into
///      one running position. This avoids ever having to re-derive or
///      "re-base" an in-flight vesting clock when a new claim arrives (a
///      source of subtle accounting bugs) — every tranche vests
///      independently, linearly, from its own deposit time.
///
///      Pause semantics (section 15 — "be very careful with vesting"):
///      pausing this contract only blocks *new* deposits from the
///      distributor. `release()` for already-deposited tranches is NEVER
///      gated by the pause flag — an admin cannot freeze money a user has
///      already earned and is progressively vesting into.
contract XeraVesting is AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant DEPOSITOR_ROLE = keccak256("DEPOSITOR_ROLE");   // XeraMiningDistributor only
    bytes32 public constant GOVERNANCE_ROLE = keccak256("GOVERNANCE_ROLE"); // multisig/timelock

    IERC20 public immutable xera;

    /// @notice Default lock/vesting length applied to newly created
    ///         tranches — matches the 6-month launch/mining phase
    ///         (section 2). Changing this NEVER affects tranches already
    ///         created; each tranche snapshots its own duration at
    ///         deposit time.
    uint256 public vestingDuration = 180 days;

    struct Tranche {
        uint128 amount;
        uint128 released;
        uint64 start;
        uint64 duration;
    }

    mapping(address => Tranche[]) public tranches;

    event Deposited(address indexed user, uint256 amount, uint256 start, uint256 duration, bytes32 indexed referenceId, uint256 trancheIndex);
    event Released(address indexed user, uint256 amount);
    event VestingDurationUpdated(uint256 oldDuration, uint256 newDuration);

    constructor(address xeraToken, address admin, address governance) {
        require(xeraToken != address(0) && admin != address(0) && governance != address(0), "XeraVesting: zero address");
        xera = IERC20(xeraToken);
        _grantRole(DEFAULT_ADMIN_ROLE, admin); // admin = timelock/multisig, controls role assignment only
        _grantRole(GOVERNANCE_ROLE, governance);
    }

    /// @notice Called only by XeraMiningDistributor when it settles a claim.
    ///         `referenceId` is the same off-chain mining reference_id the
    ///         distributor consumes, threaded through purely for indexing
    ///         and auditability on this contract's own event log.
    function deposit(address user, uint256 amount, bytes32 referenceId) external whenNotPaused onlyRole(DEPOSITOR_ROLE) {
        require(user != address(0), "XeraVesting: zero user");
        require(amount > 0 && amount <= type(uint128).max, "XeraVesting: bad amount");

        tranches[user].push(Tranche({
            amount: uint128(amount),
            released: 0,
            start: uint64(block.timestamp),
            duration: uint64(vestingDuration)
        }));

        xera.safeTransferFrom(msg.sender, address(this), amount);
        emit Deposited(user, amount, block.timestamp, vestingDuration, referenceId, tranches[user].length - 1);
    }

    function _releasableOf(Tranche storage t) internal view returns (uint256) {
        if (t.amount == 0) return 0;
        uint256 elapsed = block.timestamp - t.start;
        uint256 vested = elapsed >= t.duration ? t.amount : (uint256(t.amount) * elapsed) / t.duration;
        if (vested <= t.released) return 0;
        return vested - t.released;
    }

    /// @notice Total amount currently withdrawable for `user` across all tranches.
    function releasable(address user) public view returns (uint256 total) {
        Tranche[] storage list = tranches[user];
        for (uint256 i = 0; i < list.length; i++) {
            total += _releasableOf(list[i]);
        }
    }

    /// @notice Total ever locked, minus total already released — what remains
    ///         escrowed for `user` (vested-but-unclaimed + not-yet-vested).
    function lockedRemaining(address user) external view returns (uint256 total) {
        Tranche[] storage list = tranches[user];
        for (uint256 i = 0; i < list.length; i++) {
            total += (list[i].amount - list[i].released);
        }
    }

    function trancheCount(address user) external view returns (uint256) {
        return tranches[user].length;
    }

    /// @notice Withdraw everything vested so far across all tranches.
    ///         NOT gated by `whenNotPaused` — see contract-level NatSpec.
    ///         Always callable regardless of admin pause state.
    function release() external nonReentrant {
        Tranche[] storage list = tranches[msg.sender];
        uint256 total;
        for (uint256 i = 0; i < list.length; i++) {
            uint256 amt = _releasableOf(list[i]);
            if (amt > 0) {
                list[i].released += uint128(amt);
                total += amt;
            }
        }
        require(total > 0, "XeraVesting: nothing to release");
        xera.safeTransfer(msg.sender, total);
        emit Released(msg.sender, total);
    }

    // --- Governance-only admin surface (new deposits only; never touches release) ---

    function setVestingDuration(uint256 newDuration) external onlyRole(GOVERNANCE_ROLE) {
        require(newDuration >= 30 days && newDuration <= 730 days, "XeraVesting: unreasonable duration");
        emit VestingDurationUpdated(vestingDuration, newDuration);
        vestingDuration = newDuration;
    }

    /// @notice Pauses new deposits only. Does NOT affect release().
    function pauseDeposits() external onlyRole(GOVERNANCE_ROLE) {
        _pause();
    }

    function unpauseDeposits() external onlyRole(GOVERNANCE_ROLE) {
        _unpause();
    }
}
