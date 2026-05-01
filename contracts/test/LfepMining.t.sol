// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {LfepToken} from "../src/LfepToken.sol";
import {LfepMining} from "../src/LfepMining.sol";

/// @dev Minimal mock USDC with 6 decimals.
contract MockUSDC is ERC20 {
    constructor() ERC20("Mock USDC", "mUSDC") {}
    function decimals() public pure override returns (uint8) { return 6; }
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

contract LfepMiningTest is Test {
    LfepToken token;
    LfepMining mining;
    MockUSDC usdc;

    address owner = address(0xf35801D82787d81F2Bb69912E66Fe4f21ab872b6);
    address treasury = address(0xf35801D82787d81F2Bb69912E66Fe4f21ab872b6);
    uint256 signerPk = 0xA11CE;
    address signer;
    address agent = address(0xBEEF);

    uint256 constant CORRECT  = 20_000 ether;
    uint256 constant WRONG    = 10_000 ether;
    uint256 constant BONUS    = 5_000_000 ether;
    uint256 constant FEE      = 2_000_000; // 2 USDC

    function setUp() public {
        signer = vm.addr(signerPk);

        token = new LfepToken(owner);
        usdc = new MockUSDC();
        mining = new LfepMining(address(token), address(usdc), owner, signer, treasury);

        // Owner funds mining pool
        vm.prank(owner);
        token.transfer(address(mining), 200_000_000 ether);

        // Agent gets USDC + approves mining
        usdc.mint(agent, 1000 * 1e6);
        vm.prank(agent);
        usdc.approve(address(mining), type(uint256).max);
    }

    function _signTicket(
        address claimant,
        uint256 questionId,
        uint256 amount,
        uint256 nonce,
        uint256 expiry
    ) internal view returns (bytes memory) {
        bytes32 structHash = keccak256(abi.encode(
            mining.CLAIM_TYPEHASH(),
            claimant,
            questionId,
            amount,
            nonce,
            expiry
        ));
        bytes32 digest = keccak256(
            abi.encodePacked("\x19\x01", mining.DOMAIN_SEPARATOR(), structHash)
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerPk, digest);
        return abi.encodePacked(r, s, v);
    }

    function test_claim_correct_happy_path() public {
        uint256 expiry = block.timestamp + 300;
        bytes memory sig = _signTicket(agent, 42, CORRECT, 1, expiry);

        uint256 agentLfepBefore = token.balanceOf(agent);
        uint256 treasuryUsdcBefore = usdc.balanceOf(treasury);

        vm.prank(agent);
        mining.claim(42, CORRECT, 1, expiry, sig);

        assertEq(token.balanceOf(agent) - agentLfepBefore, CORRECT, "LFEP transferred");
        assertEq(usdc.balanceOf(treasury) - treasuryUsdcBefore, FEE, "USDC fee paid");
        assertEq(mining.totalDistributed(), CORRECT);
    }

    function test_claim_wrong_amount() public {
        uint256 expiry = block.timestamp + 300;
        bytes memory sig = _signTicket(agent, 7, WRONG, 1, expiry);

        vm.prank(agent);
        mining.claim(7, WRONG, 1, expiry, sig);

        assertEq(token.balanceOf(agent), WRONG);
    }

    function test_claim_streak_bonus() public {
        uint256 expiry = block.timestamp + 300;
        uint256 streakAmount = CORRECT + BONUS; // 10th correct in a row
        bytes memory sig = _signTicket(agent, 99, streakAmount, 10, expiry);

        vm.prank(agent);
        mining.claim(99, streakAmount, 10, expiry, sig);

        assertEq(token.balanceOf(agent), streakAmount);
        assertEq(token.balanceOf(agent), 5_020_000 ether);
    }

    function test_replay_reverts() public {
        uint256 expiry = block.timestamp + 300;
        bytes memory sig = _signTicket(agent, 42, CORRECT, 1, expiry);

        vm.prank(agent);
        mining.claim(42, CORRECT, 1, expiry, sig);

        vm.prank(agent);
        vm.expectRevert(bytes("ticket used"));
        mining.claim(42, CORRECT, 1, expiry, sig);
    }

    function test_expired_reverts() public {
        uint256 expiry = block.timestamp + 300;
        bytes memory sig = _signTicket(agent, 42, CORRECT, 1, expiry);

        vm.warp(expiry + 1);
        vm.prank(agent);
        vm.expectRevert(bytes("expired"));
        mining.claim(42, CORRECT, 1, expiry, sig);
    }

    function test_bad_signer_reverts() public {
        uint256 expiry = block.timestamp + 300;
        // Sign with wrong key
        uint256 wrongPk = 0xDEAD;
        bytes32 structHash = keccak256(abi.encode(
            mining.CLAIM_TYPEHASH(), agent, uint256(42), CORRECT, uint256(1), expiry
        ));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", mining.DOMAIN_SEPARATOR(), structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(wrongPk, digest);
        bytes memory badSig = abi.encodePacked(r, s, v);

        vm.prank(agent);
        vm.expectRevert(bytes("bad signature"));
        mining.claim(42, CORRECT, 1, expiry, badSig);
    }

    function test_wrong_sender_cannot_use_others_ticket() public {
        uint256 expiry = block.timestamp + 300;
        // Ticket signed for `agent`
        bytes memory sig = _signTicket(agent, 42, CORRECT, 1, expiry);

        // Some other address tries to use it
        address attacker = address(0xBAD);
        usdc.mint(attacker, 100 * 1e6);
        vm.prank(attacker);
        usdc.approve(address(mining), type(uint256).max);

        vm.prank(attacker);
        vm.expectRevert(bytes("bad signature"));
        mining.claim(42, CORRECT, 1, expiry, sig);
    }

    function test_owner_can_set_signer_and_treasury() public {
        address newSigner = address(0xCAFE);
        address newTreasury = address(0xC0FFEE);

        vm.prank(owner);
        mining.setSigner(newSigner);
        assertEq(mining.signer(), newSigner);

        vm.prank(owner);
        mining.setTreasury(newTreasury);
        assertEq(mining.treasury(), newTreasury);
    }

    function test_non_owner_cannot_set_signer() public {
        vm.prank(agent);
        vm.expectRevert();
        mining.setSigner(address(0xCAFE));
    }

    function test_recover_lfep() public {
        uint256 ownerBalBefore = token.balanceOf(owner);
        vm.prank(owner);
        mining.recoverLFEP(50_000_000 ether);
        assertEq(token.balanceOf(owner) - ownerBalBefore, 50_000_000 ether);
    }
}
