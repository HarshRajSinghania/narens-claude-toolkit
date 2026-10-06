import unittest

import support  # noqa: F401
from mcp_fixer import bench_stats as st


class WilsonTests(unittest.TestCase):
    def test_known_values(self):
        low, high = st.wilson(5, 10)
        self.assertAlmostEqual(low, 0.2366, places=3)
        self.assertAlmostEqual(high, 0.7634, places=3)
        low, high = st.wilson(0, 10)
        self.assertAlmostEqual(low, 0.0, places=3)
        self.assertAlmostEqual(high, 0.2775, places=3)
        low, high = st.wilson(10, 10)
        self.assertAlmostEqual(low, 0.7225, places=3)
        self.assertAlmostEqual(high, 1.0, places=3)

    def test_no_data_means_no_information(self):
        self.assertEqual(st.wilson(0, 0), (0.0, 1.0))

    def test_always_within_zero_and_one(self):
        for total in (1, 2, 7, 50):
            for correct in range(total + 1):
                low, high = st.wilson(correct, total)
                self.assertTrue(0.0 <= low <= high <= 1.0)


class BootstrapTests(unittest.TestCase):
    def test_the_same_seed_gives_the_same_answer(self):
        diffs = [0.0, 1.0, -1.0, 0.5, 0.0, -0.5, 0.25]
        self.assertEqual(st.paired_bootstrap(diffs, seed=3), st.paired_bootstrap(diffs, seed=3))

    def test_different_seeds_can_differ(self):
        diffs = [0.0, 1.0, -1.0, 0.5, 0.0, -0.5, 0.25, 0.1, -0.2]
        self.assertNotEqual(st.paired_bootstrap(diffs, seed=1), st.paired_bootstrap(diffs, seed=2))

    def test_constant_differences_have_a_point_interval(self):
        self.assertEqual(st.paired_bootstrap([0.0] * 10), (0.0, 0.0, 0.0))
        self.assertEqual(st.paired_bootstrap([-1.0] * 10), (-1.0, -1.0, -1.0))

    def test_no_tasks_means_no_information(self):
        self.assertEqual(st.paired_bootstrap([]), (0.0, -1.0, 1.0))

    def test_a_hand_computed_case(self):
        # Means of resamples of [1, -1] are -1, 0 or 1 (25%, 50%, 25%): the 2.5th percentile is -1
        # and the 97.5th is 1.
        self.assertEqual(st.paired_bootstrap([1.0, -1.0]), (0.0, -1.0, 1.0))

    def test_the_interval_contains_the_mean_for_a_typical_sample(self):
        diffs = [0.1, -0.1, 0.0, 0.2, -0.2, 0.05, 0.0, 0.0] * 5
        mean, low, high = st.paired_bootstrap(diffs)
        self.assertTrue(low <= mean <= high)


class VerdictTests(unittest.TestCase):
    def test_29_tasks_are_not_enough_but_30_are(self):
        short = st.verdict(29, 0.0, 0.0, 0.0, 0.05)
        self.assertEqual(short["verdict"], "inconclusive")
        self.assertIn("29", short["reason"])
        self.assertIn("30", short["reason"])
        self.assertEqual(st.verdict(30, 0.0, 0.0, 0.0, 0.05)["verdict"], "no drop detected")

    def test_the_tolerance_edge_is_exclusive(self):
        self.assertEqual(st.verdict(30, -0.01, -0.05, 0.02, 0.05)["verdict"], "inconclusive")
        self.assertEqual(st.verdict(30, -0.01, -0.049, 0.02, 0.05)["verdict"], "no drop detected")

    def test_worse_needs_only_an_upper_bound_below_zero(self):
        self.assertEqual(st.verdict(3, -1.0, -1.0, -0.2, 0.05)["verdict"], "worse")
        self.assertEqual(st.verdict(100, -0.1, -0.2, -0.001, 0.05)["verdict"], "worse")
        self.assertNotEqual(st.verdict(100, -0.1, -0.2, 0.0, 0.05)["verdict"], "worse")

    def test_a_wide_interval_says_how_many_tasks_would_help(self):
        result = st.verdict(40, -0.01, -0.1, 0.08, 0.05)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["tasksNeeded"], 203)
        self.assertIn("203", result["reason"])

    def test_a_difference_beyond_the_tolerance_promises_nothing(self):
        result = st.verdict(40, -0.08, -0.15, 0.01, 0.05)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIsNone(result["tasksNeeded"])
        self.assertIn("beyond", result["reason"])

    def test_no_tasks_is_inconclusive(self):
        result = st.verdict(0, 0.0, -1.0, 1.0, 0.05)
        self.assertEqual(result["verdict"], "inconclusive")

    def test_tasks_needed_is_always_more_than_now(self):
        self.assertEqual(st.tasks_needed(40, 0.0, -0.05, 0.05, 0.05), 41)


if __name__ == "__main__":
    unittest.main()
