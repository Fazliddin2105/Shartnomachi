// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title LexLab document anchor
/// @notice Stores Merkle roots of document-integrity batches. No personal data ever reaches
///         the chain: each root commits to off-chain leaves (SHA-256 of contract versions,
///         salted signer commitments, timestamps) kept encrypted in Uzbekistan.
/// @dev    Users never hold crypto: the platform's relayer pays gas ("gasless" UX).
contract LexLabAnchor {
    /// @notice Account allowed to anchor (the platform backend).
    address public immutable relayer;

    /// @notice Merkle root => block timestamp when it was anchored (0 = never).
    mapping(bytes32 => uint256) public anchoredAt;

    /// @notice Number of roots anchored so far.
    uint256 public totalBatches;

    event Anchored(bytes32 indexed root, uint32 leafCount, uint256 timestamp, uint256 batchNo);

    error NotRelayer();
    error AlreadyAnchored();
    error EmptyRoot();

    constructor() {
        relayer = msg.sender;
    }

    /// @notice Anchor one batch root.
    function anchor(bytes32 root, uint32 leafCount) external {
        if (msg.sender != relayer) revert NotRelayer();
        if (root == bytes32(0)) revert EmptyRoot();
        if (anchoredAt[root] != 0) revert AlreadyAnchored();
        anchoredAt[root] = block.timestamp;
        unchecked {
            totalBatches += 1;
        }
        emit Anchored(root, leafCount, block.timestamp, totalBatches);
    }
}
