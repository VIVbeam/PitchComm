# Host application model

These declarations are only for `run_application_tests.ps1`. They are not Zephyr headers and must never be selected by a firmware build. The test supplies host mutex and queue implementations and a panel that can stall or fail; it includes the actual application source.

The test verifies ordering, copied snapshots, bounded console input and continued engine servicing while the mock panel blocks. It does not reproduce Zephyr priority scheduling, real driver timing, I2C transactions or hardware behavior. Kernel thread creation is not simulated; the test uses host threads to exercise the relevant application paths.
