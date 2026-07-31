#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Exercise the proof-of-work-change plumbing on regtest.

Uses the regtest-only -powchangetime option to schedule a PoW-algorithm change
and verifies that:
  * blocks before the change time hash with SHA256d,
  * blocks at/after the change time hash with BLAKE2b,
  * a later block whose timestamp reaches back before the change (so it would be
    hashed with the previous algorithm) is rejected as 'pow-reversed'.
"""

from test_framework.blocktools import create_block, create_coinbase
from test_framework.messages import CBlockHeader, blake2b, hash256, powhash, set_pow_change
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, assert_raises_rpc_error

CHANGE_TIME = 1_500_000_000  # PoW change activates at this block time
CHANGE_ALGO = blake2b
CHANGE_ALGO_STR = 'blake2b'
STEP = 600                   # ten-minute spacing between mocked block times


class PowChangeTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 1
        self.extra_args = [[f"-powchangetime={CHANGE_TIME}:{CHANGE_ALGO_STR}"]]

    def header_bytes(self, blockhash):
        return bytes.fromhex(self.nodes[0].getblock(blockhash, 0)[:160])

    def run_test(self):
        node = self.nodes[0]
        addr = node.get_deterministic_priv_key().address
        # Mirror the node's schedule so framework-constructed blocks hash the same.
        set_pow_change(CHANGE_TIME, CHANGE_ALGO)

        self.log.info("Blocks before the change time use SHA256d")
        t = CHANGE_TIME - 20 * STEP
        pre_hash = None
        for _ in range(20):
            node.setmocktime(t)
            pre_hash = self.generatetoaddress(node, 1, addr)[0]
            t += STEP
        pre_header = self.header_bytes(pre_hash)
        pre_time = int.from_bytes(pre_header[68:72], "little")
        assert pre_time < CHANGE_TIME
        assert_equal(pre_hash, hash256(pre_header)[::-1].hex())
        assert_equal(pre_hash, powhash(pre_header, pre_time)[::-1].hex())

        self.log.info("Blocks at/after the change time use BLAKE2b")
        node.setmocktime(CHANGE_TIME)
        self.generatetoaddress(node, 1, addr)
        node.setmocktime(CHANGE_TIME + STEP)
        post_hash = self.generatetoaddress(node, 1, addr)[0]
        post_header = self.header_bytes(post_hash)
        post_time = int.from_bytes(post_header[68:72], "little")
        assert post_time >= CHANGE_TIME
        # The framework's algorithm-aware hash matches the node's block hash...
        assert_equal(post_hash, powhash(post_header, post_time)[::-1].hex())

        self.log.info("A block reaching back before the change is rejected (pow-reversed)")
        tip = node.getbestblockhash()
        reversed_block = create_block(int(tip, 16), create_coinbase(node.getblockcount() + 1), CHANGE_TIME - 1)
        reversed_block.solve()
        assert_raises_rpc_error(
            -25, "pow-reversed",
            lambda: node.submitheader(hexdata=CBlockHeader(reversed_block).serialize().hex()),
        )


if __name__ == "__main__":
    PowChangeTest(__file__).main()
