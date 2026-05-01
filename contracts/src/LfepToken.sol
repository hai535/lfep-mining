// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title LFep Token
/// @notice Fixed supply of 1,000,000,000 LFEP minted to the deployer-specified owner.
///         No further minting. After deploy the owner is expected to transfer
///         200,000,000 (20%) to LfepMining as the mining pool, and earmark
///         800,000,000 (80%) for liquidity injection at TGE.
contract LfepToken is ERC20, Ownable {
    constructor(address owner_) ERC20("LFep", "LFEP") Ownable(owner_) {
        _mint(owner_, 1_000_000_000 ether);
    }
}
