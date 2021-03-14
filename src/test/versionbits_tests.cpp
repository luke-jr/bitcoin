// Copyright (c) 2014-2020 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <chain.h>
#include <chainparams.h>
#include <consensus/params.h>
#include <test/util/setup_common.h>
#include <validation.h>
#include <versionbits.h>

#include <boost/test/unit_test.hpp>

/* Define a virtual block time, one block per 10 minutes after Nov 14 2014, 0:55:36am */
static int32_t TestTime(int nHeight) { return 1415926536 + 600 * nHeight; }

static const std::string StateName(ThresholdState state)
{
    switch (state) {
    case ThresholdState::DEFINED:   return "DEFINED";
    case ThresholdState::STARTED:   return "STARTED";
    case ThresholdState::LOCKED_IN: return "LOCKED_IN";
    case ThresholdState::ACTIVE:    return "ACTIVE";
    case ThresholdState::FAILED:    return "FAILED";
    } // no default case, so the compiler can warn about missing cases
    return "";
}

static const Consensus::Params paramsDummy = Consensus::Params();

class TestConditionChecker : public AbstractThresholdConditionChecker
{
private:
    mutable ThresholdConditionCache cache;

public:
    int64_t StartHeight(const Consensus::Params& params) const override { return 100; }
    int64_t TimeoutHeight(const Consensus::Params& params) const override { return 200; }
    int Period(const Consensus::Params& params) const override { return 10; }
    int Threshold(const Consensus::Params& params) const override { return 9; }
    bool Condition(const CBlockIndex* pindex, const Consensus::Params& params) const override { return (pindex->nVersion & 0x100); }

    ThresholdState GetStateFor(const CBlockIndex* pindexPrev) const { return AbstractThresholdConditionChecker::GetStateFor(pindexPrev, paramsDummy, cache); }
    int GetStateSinceHeightFor(const CBlockIndex* pindexPrev) const { return AbstractThresholdConditionChecker::GetStateSinceHeightFor(pindexPrev, paramsDummy, cache); }
};

class TestAlwaysActiveConditionChecker : public TestConditionChecker
{
public:
    int64_t StartHeight(const Consensus::Params& params) const override { return Consensus::BIP9Deployment::ALWAYS_ACTIVE; }
};

class TestNeverActiveConditionChecker : public TestConditionChecker
{
public:
    int64_t StartHeight(const Consensus::Params& params) const override { return Consensus::BIP9Deployment::NEVER_ACTIVE; }
    int64_t TimeoutHeight(const Consensus::Params& params) const override { return Consensus::BIP9Deployment::NEVER_ACTIVE; }
};

#define CHECKERS 6

class VersionBitsTester
{
    // A fake blockchain
    std::vector<CBlockIndex*> vpblock;

    // 6 independent checkers for the same bit.
    // The first one performs all checks, the second only 50%, the third only 25%, etc...
    // This is to test whether lack of cached information leads to the same results.
    TestConditionChecker checker[CHECKERS];
    // Another 6 that assume always active activation
    TestAlwaysActiveConditionChecker checker_always[CHECKERS];
    // Another 6 that assume never active activation
    TestNeverActiveConditionChecker checker_never[CHECKERS];

    // Test counter (to identify failures)
    int num;

public:
    VersionBitsTester() : num(0) {}

    VersionBitsTester& Reset() {
        for (unsigned int i = 0; i < vpblock.size(); i++) {
            delete vpblock[i];
        }
        for (unsigned int  i = 0; i < CHECKERS; i++) {
            checker[i] = TestConditionChecker();
            checker_always[i] = TestAlwaysActiveConditionChecker();
            checker_never[i] = TestNeverActiveConditionChecker();
        }
        vpblock.clear();
        return *this;
    }

    ~VersionBitsTester() {
         Reset();
    }

    VersionBitsTester& Mine(unsigned int height, int32_t nTime, int32_t nVersion) {
        while (vpblock.size() < height) {
            CBlockIndex* pindex = new CBlockIndex();
            pindex->nHeight = vpblock.size();
            pindex->pprev = vpblock.size() > 0 ? vpblock.back() : nullptr;
            pindex->nTime = nTime;
            pindex->nVersion = nVersion;
            pindex->BuildSkip();
            vpblock.push_back(pindex);
        }
        return *this;
    }

    VersionBitsTester& TestStateSinceHeight(int height) {
        for (int i = 0; i < CHECKERS; i++) {
            if (InsecureRandBits(i) == 0) {
                BOOST_CHECK_MESSAGE(checker[i].GetStateSinceHeightFor(vpblock.empty() ? nullptr : vpblock.back()) == height, strprintf("Test %i for StateSinceHeight", num));
                BOOST_CHECK_MESSAGE(checker_always[i].GetStateSinceHeightFor(vpblock.empty() ? nullptr : vpblock.back()) == 0, strprintf("Test %i for StateSinceHeight (always active)", num));

                // never active may go from DEFINED -> FAILED at the first period
                const auto never_height = checker_never[i].GetStateSinceHeightFor(vpblock.empty() ? nullptr : vpblock.back());
                BOOST_CHECK_MESSAGE(never_height == 0 || never_height == checker_never[i].Period(paramsDummy), strprintf("Test %i for StateSinceHeight (never active)", num));
            }
        }
        num++;
        return *this;
    }

    VersionBitsTester& TestState(ThresholdState exp) {
        for (int i = 0; i < CHECKERS; i++) {
            if (InsecureRandBits(i) == 0) {
                const CBlockIndex* pindex = vpblock.empty() ? nullptr : vpblock.back();
                ThresholdState got = checker[i].GetStateFor(pindex);
                ThresholdState got_always = checker_always[i].GetStateFor(pindex);
                ThresholdState got_never = checker_never[i].GetStateFor(pindex);
                // nHeight of the next block. If vpblock is empty, the next (ie first)
                // block should be the genesis block with nHeight == 0.
                int height = pindex == nullptr ? 0 : pindex->nHeight + 1;
                BOOST_CHECK_MESSAGE(got == exp, strprintf("Test %i for %s height %d (got %s)", num, StateName(exp), height, StateName(got)));
                BOOST_CHECK_MESSAGE(got_always == ThresholdState::ACTIVE, strprintf("Test %i for ACTIVE height %d (got %s; always active case)", num, height, StateName(got_always)));
                BOOST_CHECK_MESSAGE(got_never == ThresholdState::DEFINED|| got_never == ThresholdState::FAILED, strprintf("Test %i for DEFINED/FAILED height %d (got %s; never active case)", num, height, StateName(got_never)));
            }
        }
        num++;
        return *this;
    }

    VersionBitsTester& TestDefined() { return TestState(ThresholdState::DEFINED); }
    VersionBitsTester& TestStarted() { return TestState(ThresholdState::STARTED); }
    VersionBitsTester& TestLockedIn() { return TestState(ThresholdState::LOCKED_IN); }
    VersionBitsTester& TestActive() { return TestState(ThresholdState::ACTIVE); }
    VersionBitsTester& TestFailed() { return TestState(ThresholdState::FAILED); }

    CBlockIndex * Tip() { return vpblock.size() ? vpblock.back() : nullptr; }
};

BOOST_FIXTURE_TEST_SUITE(versionbits_tests, TestingSetup)

BOOST_AUTO_TEST_CASE(versionbits_test)
{
    for (int i = 0; i < 64; i++) {
        // DEFINED -> STARTED -> FAILED
        VersionBitsTester().TestDefined().TestStateSinceHeight(0)
                           .Mine(1, TestTime(1), 0).TestDefined().TestStateSinceHeight(0)
                           .Mine(99, TestTime(10000) - 1, 0x100).TestDefined().TestStateSinceHeight(0) // One block more and it would be defined
                           .Mine(100, TestTime(10000), 0x100).TestStarted().TestStateSinceHeight(100) // So that's what happens the next period
                           .Mine(101, TestTime(10010), 0).TestStarted().TestStateSinceHeight(100) // 1 old block
                           .Mine(109, TestTime(10020), 0x100).TestStarted().TestStateSinceHeight(100) // 8 new blocks
                           .Mine(110, TestTime(10020), 0).TestStarted().TestStateSinceHeight(100) // 1 old block (so 8 out of the past 10 are new)
                           .Mine(151, TestTime(10020), 0).TestStarted().TestStateSinceHeight(100)
                           .Mine(200, TestTime(20000), 0).TestFailed().TestStateSinceHeight(200)
                           .Mine(300, TestTime(20010), 0x100).TestFailed().TestStateSinceHeight(200)

        // DEFINED -> STARTED -> LOCKEDIN at the last minute -> ACTIVE
                           .Reset().TestDefined()
                           .Mine(1, TestTime(1), 0).TestDefined().TestStateSinceHeight(0)
                           .Mine(99, TestTime(10000) - 1, 0x101).TestDefined().TestStateSinceHeight(0) // One second more and it would be started
                           .Mine(100, TestTime(10000), 0x101).TestStarted().TestStateSinceHeight(100) // So that's what happens the next period
                           .Mine(109, TestTime(10020), 0x100).TestStarted().TestStateSinceHeight(100) // 9 new blocks
                           .Mine(110, TestTime(29999), 0x200).TestLockedIn().TestStateSinceHeight(110) // 1 old block (so 9 out of the past 10)
                           .Mine(119, TestTime(30001), 0).TestLockedIn().TestStateSinceHeight(110)
                           .Mine(120, TestTime(30002), 0).TestActive().TestStateSinceHeight(120)
                           .Mine(200, TestTime(30003), 0).TestActive().TestStateSinceHeight(120)
                           .Mine(300, TestTime(40000), 0).TestActive().TestStateSinceHeight(120)

        // DEFINED multiple periods -> STARTED multiple periods -> FAILED
                           .Reset().TestDefined().TestStateSinceHeight(0)
                           .Mine(9, TestTime(999), 0).TestDefined().TestStateSinceHeight(0)
                           .Mine(10, TestTime(1000), 0).TestDefined().TestStateSinceHeight(0)
                           .Mine(20, TestTime(2000), 0).TestDefined().TestStateSinceHeight(0)
                           .Mine(100, TestTime(10000), 0).TestStarted().TestStateSinceHeight(100)
                           .Mine(103, TestTime(10000), 0).TestStarted().TestStateSinceHeight(100)
                           .Mine(105, TestTime(10000), 0).TestStarted().TestStateSinceHeight(100)
                           .Mine(200, TestTime(20000), 0).TestFailed().TestStateSinceHeight(200)
                           .Mine(300, TestTime(20000), 0x100).TestFailed().TestStateSinceHeight(200);
    }

    // Sanity checks of version bit deployments
    const auto chainParams = CreateChainParams(*m_node.args, CBaseChainParams::MAIN);
    const Consensus::Params &mainnetParams = chainParams->GetConsensus();
    for (int i=0; i<(int) Consensus::MAX_VERSION_BITS_DEPLOYMENTS; i++) {
        uint32_t bitmask = VersionBitsMask(mainnetParams, static_cast<Consensus::DeploymentPos>(i));
        // Make sure that no deployment tries to set an invalid bit.
        BOOST_CHECK_EQUAL(bitmask & ~(uint32_t)VERSIONBITS_TOP_MASK, bitmask);

        // Verify that the deployment windows of different deployment using the
        // same bit are disjoint.
        // This test may need modification at such time as a new deployment
        // is proposed that reuses the bit of an activated soft fork, before the
        // end time of that soft fork.  (Alternatively, the end time of that
        // activated soft fork could be later changed to be earlier to avoid
        // overlap.)
        for (int j=i+1; j<(int) Consensus::MAX_VERSION_BITS_DEPLOYMENTS; j++) {
            if (VersionBitsMask(mainnetParams, static_cast<Consensus::DeploymentPos>(j)) == bitmask) {
                BOOST_CHECK(mainnetParams.vDeployments[j].startheight > mainnetParams.vDeployments[i].timeoutheight ||
                        mainnetParams.vDeployments[i].startheight > mainnetParams.vDeployments[j].timeoutheight);
            }
        }
    }
}

BOOST_AUTO_TEST_CASE(versionbits_computeblockversion)
{
    // Check that ComputeBlockVersion will set the appropriate bit correctly
    const auto period = CreateChainParams(*m_node.args, CBaseChainParams::REGTEST)->GetConsensus().nMinerConfirmationWindow;
    gArgs.ForceSetArg("-vbparams", strprintf("testdummy:@%s:@%s", period, period * 2));
    const auto chainParams = CreateChainParams(*m_node.args, CBaseChainParams::REGTEST);
    const Consensus::Params &mainnetParams = chainParams->GetConsensus();

    // Use the TESTDUMMY deployment for testing purposes.
    int64_t bit = mainnetParams.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit;
    int64_t startheight = mainnetParams.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].startheight;
    int64_t timeoutheight = mainnetParams.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].timeoutheight;
    const int64_t nTime = TestTime(startheight);

    assert(startheight < timeoutheight);

    // In the first chain, test that the bit is set by CBV until it has failed.
    // In the second chain, test the bit is set by CBV while STARTED and
    // LOCKED-IN, and then no longer set while ACTIVE.
    VersionBitsTester firstChain, secondChain;

    // Start generating blocks before startheight
    // Before the chain has reached startheight-1, the bit should not be set.
    CBlockIndex *lastBlock = nullptr;
    lastBlock = firstChain.Mine(startheight - 1, nTime, VERSIONBITS_LAST_OLD_BLOCK_VERSION).Tip();
    BOOST_CHECK_EQUAL(ComputeBlockVersion(lastBlock, mainnetParams) & (1<<bit), 0);

    // Advance to the next block and transition to STARTED,
    lastBlock = firstChain.Mine(startheight, nTime, VERSIONBITS_LAST_OLD_BLOCK_VERSION).Tip();
    // so ComputeBlockVersion should now set the bit,
    BOOST_CHECK((ComputeBlockVersion(lastBlock, mainnetParams) & (1<<bit)) != 0);
    // and should also be using the VERSIONBITS_TOP_BITS.
    BOOST_CHECK_EQUAL(ComputeBlockVersion(lastBlock, mainnetParams) & VERSIONBITS_TOP_MASK, VERSIONBITS_TOP_BITS);

    // Check that ComputeBlockVersion will set the bit until timeoutheight
    // These blocks are all before timeoutheight is reached.
    lastBlock = firstChain.Mine(timeoutheight - 1, nTime, VERSIONBITS_LAST_OLD_BLOCK_VERSION).Tip();
    BOOST_CHECK((ComputeBlockVersion(lastBlock, mainnetParams) & (1<<bit)) != 0);
    BOOST_CHECK_EQUAL(ComputeBlockVersion(lastBlock, mainnetParams) & VERSIONBITS_TOP_MASK, VERSIONBITS_TOP_BITS);

    // The next block should trigger no longer setting the bit.
    lastBlock = firstChain.Mine(timeoutheight, nTime, VERSIONBITS_LAST_OLD_BLOCK_VERSION).Tip();
    BOOST_CHECK_EQUAL(ComputeBlockVersion(lastBlock, mainnetParams) & (1<<bit), 0);

    // On a new chain:
    // verify that the bit will be set after lock-in, and then stop being set
    // after activation.

    // Mine up until startheight-1, and check that the bit will be on for the
    // next period.
    lastBlock = secondChain.Mine(startheight, nTime, VERSIONBITS_LAST_OLD_BLOCK_VERSION).Tip();
    BOOST_CHECK((ComputeBlockVersion(lastBlock, mainnetParams) & (1<<bit)) != 0);

    // Mine another block, signaling the new bit.
    lastBlock = secondChain.Mine(startheight + mainnetParams.nMinerConfirmationWindow, nTime, VERSIONBITS_TOP_BITS | (1<<bit)).Tip();
    // After one period of setting the bit on each block, it should have locked in.
    // We keep setting the bit for one more period though, until activation.
    BOOST_CHECK((ComputeBlockVersion(lastBlock, mainnetParams) & (1<<bit)) != 0);

    // Now check that we keep mining the block until the end of this period, and
    // then stop at the beginning of the next period.
    lastBlock = secondChain.Mine(startheight + (mainnetParams.nMinerConfirmationWindow * 2) - 1, nTime, VERSIONBITS_LAST_OLD_BLOCK_VERSION).Tip();
    BOOST_CHECK((ComputeBlockVersion(lastBlock, mainnetParams) & (1 << bit)) != 0);
    lastBlock = secondChain.Mine(startheight + (mainnetParams.nMinerConfirmationWindow * 2), nTime, VERSIONBITS_LAST_OLD_BLOCK_VERSION).Tip();
    BOOST_CHECK_EQUAL(ComputeBlockVersion(lastBlock, mainnetParams) & (1<<bit), 0);

    // Finally, verify that after a soft fork has activated, CBV no longer uses
    // VERSIONBITS_LAST_OLD_BLOCK_VERSION.
    //BOOST_CHECK_EQUAL(ComputeBlockVersion(lastBlock, mainnetParams) & VERSIONBITS_TOP_MASK, VERSIONBITS_TOP_BITS);
}


BOOST_AUTO_TEST_SUITE_END()
