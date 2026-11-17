import datetime

import time


class CustodianProcess:

    def __init__(self,
                 name: str,
                 restart_every: datetime.timedelta):
        self.restart_every = restart_every or datetime.timedelta(hours=12)
        self.name = name
        self.kill_requested = False

    def unit_of_work(self, time_remaining: datetime.timedelta) -> datetime.timedelta:
        pass

    def initialize(self):
        pass

    def dispose(self):
        pass

    def kill(self):
        self.kill_requested = True

    def run(self) -> None:
        started = datetime.datetime.now()
        self.initialize()
        while not self.kill_requested and datetime.datetime.now() - started < self.restart_every:
            time_remaining = datetime.datetime.now() - started
            remaining_sleep = self.unit_of_work(time_remaining=time_remaining)
            while not self.kill_requested and remaining_sleep.total_seconds() > 0:
                """sleep in short bits so we can be interrupted and terminated"""
                nap = min(1, remaining_sleep.total_seconds())
                time.sleep(nap)
                remaining_sleep -= datetime.timedelta(seconds=nap)

            """If it looks like you didn't do anything """
        self.dispose()

    def install(self):
        """Register this as a system service, to be called by a user on install
        using self.name as the default for the service name
        """
        pass
