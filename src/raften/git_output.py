"""Bounded concurrent draining of a Git child's binary output pipes."""

import io
import os
import selectors
import time
from typing import BinaryIO

from raften import resource_limits as limits


def collect_output(stdout: BinaryIO, stderr: BinaryIO, *, operation: str,
                   deadline: float, max_bytes: int, records: bool) -> bytes:
    output = io.BytesIO()
    totals = {"stdout": 0, "stderr": 0}
    count = 0
    record_bytes = 0
    with selectors.DefaultSelector() as selector:
        selector.register(stdout, selectors.EVENT_READ, "stdout")
        selector.register(stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Git output deadline exceeded")
            for key, _events in selector.select(remaining):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                stream = key.data
                totals[stream] += len(chunk)
                ceiling = max_bytes if stream == "stdout" else limits.MAX_GIT_STDERR_BYTES
                limits.require_resource(f"{stream}_bytes", totals[stream], ceiling,
                                        operation=operation)
                if stream == "stderr":
                    continue
                if records:
                    count += chunk.count(b"\0")
                    limits.require_resource("records", count, limits.MAX_GIT_RECORDS,
                                            operation=operation)
                    start = 0
                    while start < len(chunk):
                        end = chunk.find(b"\0", start)
                        stop = len(chunk) if end < 0 else end
                        record_bytes += stop - start
                        limits.require_resource("record_bytes", record_bytes,
                                                limits.MAX_GIT_PATH_BYTES + 128,
                                                operation=operation)
                        if end < 0:
                            break
                        record_bytes = 0
                        start = end + 1
                output.write(chunk)
    return output.getvalue()
