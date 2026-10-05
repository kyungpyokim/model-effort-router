"""The former L1-L5 workflow runner was removed; never dispatch old paid evaluations."""
import sys

MESSAGE = ("evaluation.live_runner's automatic plan/gate/escalation/review protocol was removed. "
           "Use role/effort evaluation with explicitly labeled cases and invoke providers only when separately authorized.")

def main(argv=None):
    print(MESSAGE, file=sys.stderr)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
