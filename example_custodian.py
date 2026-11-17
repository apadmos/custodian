"""Minimal custodian: logs a heartbeat every 10 seconds.

    python example_custodian.py            # run in the foreground, Ctrl+C to stop
    python example_custodian.py unit       # see the systemd unit it would install
    python example_custodian.py install --user
"""
import datetime

from custodian_process import CustodianProcess


class Heartbeat(CustodianProcess):

    def __init__(self):
        super().__init__(name="heartbeat-example", restart_every=datetime.timedelta(hours=1))
        self.beats = 0

    def initialize(self):
        print(f"{self.name} starting, will restart in {self.restart_every}")

    def unit_of_work(self, time_remaining: datetime.timedelta) -> datetime.timedelta:
        self.beats += 1
        print(f"beat {self.beats}, {time_remaining} until restart")
        return datetime.timedelta(seconds=10)

    def dispose(self):
        print(f"{self.name} stopping after {self.beats} beats")


if __name__ == "__main__":
    Heartbeat().cli()
