#!/bin/bash
MYDIR="$(dirname "$0")"
QEMU="$1"
OUTFILE="$2"
shift;shift

DONEFILE="$(mktemp)"
PIDFILE="$(mktemp)"

( "$QEMU" -serial "file:$OUTFILE" \
  -kernel "$MYDIR/../../cpuid_test_kernel/cpuid_dump_kernel.bin" "$@" &
  echo $! > "$PIDFILE"
  wait
  echo DONE > "$DONEFILE";
) &
pid="$!"
for n in $(seq 1 40);do
    grep -q "==END TEST==" "$OUTFILE" && break
    grep -q DONE "$DONEFILE" && break
    sleep 0.25
done
kill "$pid"
kill "$(cat "$PIDFILE")"
wait
exit 0
