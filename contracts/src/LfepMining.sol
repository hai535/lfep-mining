// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title LfepMining
/// @notice Q&A mining contract. Off-chain backend signs EIP-712 Claim tickets
///         after verifying an agent's answer. Agent then submits the ticket
///         on-chain, paying 2 USDC and receiving the signed reward amount.
contract LfepMining is EIP712, Ownable {
    using SafeERC20 for IERC20;

    IERC20 public immutable LFEP;
    IERC20 public immutable USDC;

    /// @dev EOA whose signature authorizes claim tickets. Settable by owner.
    address public signer;
    /// @dev Recipient of the per-claim USDC fee. Settable by owner.
    address public treasury;

    /// @dev Submission fee in USDC (6 decimals). 2 USDC.
    uint256 public constant SUBMIT_FEE = 2_000_000;

    /// @dev EIP-712 type hash for Claim. Must match server-side signer.py.
    bytes32 public constant CLAIM_TYPEHASH = keccak256(
        "Claim(address agent,uint256 questionId,uint256 amount,uint256 nonce,uint256 expiry)"
    );

    mapping(bytes32 => bool) public usedTickets;
    uint256 public totalDistributed;

    event Claimed(
        address indexed agent,
        uint256 indexed questionId,
        uint256 amount,
        uint256 nonce
    );
    event SignerUpdated(address indexed newSigner);
    event TreasuryUpdated(address indexed newTreasury);

    constructor(
        address lfep_,
        address usdc_,
        address owner_,
        address signer_,
        address treasury_
    ) EIP712("LfepMining", "1") Ownable(owner_) {
        require(lfep_ != address(0) && usdc_ != address(0), "zero token");
        require(signer_ != address(0) && treasury_ != address(0), "zero addr");
        LFEP = IERC20(lfep_);
        USDC = IERC20(usdc_);
        signer = signer_;
        treasury = treasury_;
    }

    /// @notice Pay 2 USDC and claim the off-chain-signed reward amount.
    /// @dev `msg.sender` is bound into the digest, so a leaked ticket cannot
    ///      be redeemed by a different address. `usedTickets[digest]` blocks
    ///      replay even on the original sender.
    function claim(
        uint256 questionId,
        uint256 amount,
        uint256 nonce,
        uint256 expiry,
        bytes calldata sig
    ) external {
        require(block.timestamp <= expiry, "expired");
        bytes32 structHash = keccak256(
            abi.encode(CLAIM_TYPEHASH, msg.sender, questionId, amount, nonce, expiry)
        );
        bytes32 digest = _hashTypedDataV4(structHash);
        require(!usedTickets[digest], "ticket used");
        require(ECDSA.recover(digest, sig) == signer, "bad signature");
        usedTickets[digest] = true;

        USDC.safeTransferFrom(msg.sender, treasury, SUBMIT_FEE);
        LFEP.safeTransfer(msg.sender, amount);
        totalDistributed += amount;

        emit Claimed(msg.sender, questionId, amount, nonce);
    }

    function setSigner(address s) external onlyOwner {
        require(s != address(0), "zero signer");
        signer = s;
        emit SignerUpdated(s);
    }

    function setTreasury(address t) external onlyOwner {
        require(t != address(0), "zero treasury");
        treasury = t;
        emit TreasuryUpdated(t);
    }

    /// @notice Owner can recover unused LFEP from the mining pool (e.g. after
    ///         pool is exhausted or for migration).
    function recoverLFEP(uint256 amount) external onlyOwner {
        LFEP.safeTransfer(owner(), amount);
    }

    /// @notice Owner can sweep accumulated USDC even if treasury was set
    ///         to this contract by accident. Normally treasury receives USDC
    ///         on every claim and this function is a no-op.
    function sweepUSDC() external onlyOwner {
        uint256 bal = USDC.balanceOf(address(this));
        if (bal > 0) USDC.safeTransfer(treasury, bal);
    }

    function DOMAIN_SEPARATOR() external view returns (bytes32) {
        return _domainSeparatorV4();
    }
}
