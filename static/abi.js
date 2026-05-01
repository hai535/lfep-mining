// LfepMining contract ABI (subset needed by the frontend)
// Filled in after Foundry deploy. Until then, addresses are empty strings
// and the UI gracefully shows a "not deployed yet" banner.
window.LFEP_CONFIG = {
  chainId: 8453,
  chainName: "Base",
  rpc: "https://mainnet.base.org",
  blockExplorer: "https://basescan.org",
  // These three are populated dynamically from /api/contracts at boot.
  lfepToken: "",
  lfepMining: "",
  usdc: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
};

window.MINING_ABI = [
  "function claim(uint256 questionId,uint256 amount,uint256 nonce,uint256 expiry,bytes sig) external",
  "function totalDistributed() external view returns (uint256)",
  "function signer() external view returns (address)",
  "function SUBMIT_FEE() external view returns (uint256)",
  "event Claimed(address indexed agent,uint256 indexed questionId,uint256 amount,uint256 nonce)",
];

window.ERC20_ABI = [
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address,address) view returns (uint256)",
  "function approve(address,uint256) returns (bool)",
  "function decimals() view returns (uint8)",
  "function symbol() view returns (string)",
];
