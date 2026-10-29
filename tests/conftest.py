import os

# Tests never touch the network: anything not provided as a fixture fails fast instead of retrying.
os.environ.setdefault("WELLSCOPE_OFFLINE", "1")
