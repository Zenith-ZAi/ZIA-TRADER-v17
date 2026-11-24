"""Pure validators shared by credential-vault startup and runtime code."""
from __future__ import annotations

import re


_AWS_KMS_KEY_ARN = re.compile(
    r"^arn:[a-z0-9-]+:kms:[a-z0-9-]+:[0-9]{12}:key/[A-Za-z0-9-]{1,128}$"
)
_AWS_REGION = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)+-[0-9]+$")


def valid_aws_kms_key_arn(value: object, *, region: str | None = None) -> bool:
    """Accept a full key ARN only; reject aliases and unscoped key identifiers."""
    if not isinstance(value, str) or _AWS_KMS_KEY_ARN.fullmatch(value) is None:
        return False
    return region is None or value.split(":")[3] == region


def valid_aws_region(value: object) -> bool:
    return isinstance(value, str) and _AWS_REGION.fullmatch(value) is not None


__all__ = ["valid_aws_kms_key_arn", "valid_aws_region"]
