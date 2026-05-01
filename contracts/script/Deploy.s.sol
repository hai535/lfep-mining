// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {LfepToken} from "../src/LfepToken.sol";
import {LfepMining} from "../src/LfepMining.sol";

/// @notice One-shot deploy: LfepToken + LfepMining, then transfer 200M LFEP
///         from owner to mining contract.
/// Required env vars:
///   OWNER_ADDR    — receives 1B LFEP, becomes owner of both contracts
///   SIGNER_ADDR   — server EOA that signs claim tickets
///   TREASURY_ADDR — receives USDC fees (typically same as OWNER_ADDR)
///   USDC_ADDR     — Base mainnet: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
contract Deploy is Script {
    function run() external {
        address owner    = vm.envAddress("OWNER_ADDR");
        address signer   = vm.envAddress("SIGNER_ADDR");
        address treasury = vm.envAddress("TREASURY_ADDR");
        address usdc     = vm.envAddress("USDC_ADDR");

        vm.startBroadcast();

        LfepToken token = new LfepToken(owner);
        LfepMining mining = new LfepMining(
            address(token),
            usdc,
            owner,
            signer,
            treasury
        );

        // Owner is the deployer (msg.sender during broadcast must equal owner
        // for this transfer to work — caller should run with owner's key).
        token.transfer(address(mining), 200_000_000 ether);

        vm.stopBroadcast();

        console2.log("LfepToken:  ", address(token));
        console2.log("LfepMining: ", address(mining));
        console2.log("Owner:      ", owner);
        console2.log("Signer:     ", signer);
        console2.log("Treasury:   ", treasury);
        console2.log("Mining pool funded: 200,000,000 LFEP");
    }
}
