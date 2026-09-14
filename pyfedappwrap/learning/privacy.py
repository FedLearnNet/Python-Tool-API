"""Privacy-preserving count rounding for metrics that leave a clinic.

Apps must never publish exact patient counts. The platform already applies this policy to federated
*query* counts in the local-learning-api (``bio.cosy.feddb.local.api.privacy.PrivacyBO.modifyCount``);
this is the identical algorithm, ported so an app can round its own cohort sizes (n_train / n_val)
before emitting them as metrics. Keep this in sync with the Java implementation.
"""
from __future__ import annotations

import math
from typing import Optional

#: Hard floor below which a count is disclosed as 0 (k-anonymity-style suppression).
DEFAULT_MIN_COUNT = 100


def secure_count(count: Optional[int], min_count: int = DEFAULT_MIN_COUNT) -> int:
    """Round ``count`` up to a privacy-safe value, mirroring ``PrivacyBO.modifyCount``.

    Policy:
      * ``None`` or ``count < min_count`` -> ``0`` (too small to disclose).
      * otherwise ceil to one order of magnitude below the count's own magnitude, e.g.
        ``123 -> 200``, ``1234 -> 1300``, ``9526 -> 9600``.
    """
    if count is None:
        return 0
    count = int(count)
    if count < max(0, min_count):
        return 0
    # Round up to 10^(magnitude-1): for hundreds round to tens, for thousands to hundreds, ...
    magnitude_minus_one = math.floor(math.log10(count)) - 1
    divisor = 10 ** magnitude_minus_one
    return int(math.ceil(count / divisor) * divisor)
