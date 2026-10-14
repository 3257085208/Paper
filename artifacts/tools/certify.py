#!/usr/bin/env python3
"""Certification budget calculator: Clopper-Pearson one-sided bounds for
zero-failure campaigns, and the trials needed for a target bound.

Usage:
  python3 certify.py --passes 24 28 90
  python3 certify.py --target-eps 0.01 0.03 0.10
"""
import argparse
import math


def bound_zero_failure(n, alpha=0.05):
    return 1 - alpha ** (1.0 / n)


def trials_needed(eps, alpha=0.05):
    return math.ceil(math.log(alpha) / math.log(1 - eps))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, nargs="*", default=[])
    ap.add_argument("--target-eps", type=float, nargs="*", default=[])
    ap.add_argument("--alpha", type=float, default=0.05)
    a = ap.parse_args()
    for n in a.passes:
        print("n=%3d passes -> 95%% upper bound on failure rate: %.1f%%" % (n, 100 * bound_zero_failure(n, a.alpha)))
    for eps in a.target_eps:
        print("target <=%.1f%% -> need >= %d zero-failure trials" % (100 * eps, trials_needed(eps, a.alpha)))


if __name__ == "__main__":
    main()
