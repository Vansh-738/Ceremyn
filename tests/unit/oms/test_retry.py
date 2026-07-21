from ceremyn.oms import RetryPolicy
from ceremyn.oms.exceptions import OMSNonRetryableBrokerError, OMSRetryableError


def test_retry_policy_retries_only_retryable_errors() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.5)

    retryable = policy.decide(OMSRetryableError("temporary"), attempt=1)
    fatal = policy.decide(OMSNonRetryableBrokerError("bad request"), attempt=1)

    assert retryable.should_retry is True
    assert retryable.delay_seconds == 0.5
    assert fatal.should_retry is False
