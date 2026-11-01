"""Linux subprocess wall-clock budget including DNS, headers and body reads."""

from contextlib import contextmanager
import signal
import time
from validation import Failure


@contextmanager
def operation_deadline(seconds):
    """Interrupt blocking I/O and restore the caller's timer and alarm handler."""
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_delay, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def expired(signum, frame):
        raise Failure("timeout", "Operation wall-clock deadline exceeded.")

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(
            signal.ITIMER_REAL, min(seconds, previous_delay) if previous_delay > 0 else seconds
        )
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_delay > 0:
            remaining = max(0.000001, previous_delay - (time.monotonic() - started))
            signal.setitimer(signal.ITIMER_REAL, remaining, previous_interval)
