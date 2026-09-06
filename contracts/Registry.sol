// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Registry {
    struct Record {
        address submitter;
        uint64 timestamp;
        string uri;
    }

    mapping(bytes32 => Record) public records;

    event Anchored(
        bytes32 indexed fingerprint,
        address indexed submitter,
        uint64 timestamp,
        string uri
    );

    function anchor(bytes32 fingerprint, string calldata uri) external {
        require(records[fingerprint].timestamp == 0, "already anchored");

        uint64 timestamp = uint64(block.timestamp);
        records[fingerprint] = Record(msg.sender, timestamp, uri);
        emit Anchored(fingerprint, msg.sender, timestamp, uri);
    }

    function verify(bytes32 fingerprint)
        external
        view
        returns (
            bool exists,
            address submitter,
            uint64 timestamp,
            string memory uri
        )
    {
        Record memory record = records[fingerprint];
        return (
            record.timestamp != 0,
            record.submitter,
            record.timestamp,
            record.uri
        );
    }
}
