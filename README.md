# custodian

Run a Python process "forever" under systemd. Your process runs for a set time (`restart_every`, default 12h),
exits cleanly, and systemd restarts it. Crashes are restarted the same way.

## Usage

```python
import datetime
from custodian import CustodianProcess


class Cleaner(CustodianProcess):
    def __init__(self):
        super().__init__(name="cleaner", restart_every=datetime.timedelta(hours=6))

    def initialize(self):        # once per run
        ...

    def unit_of_work(self, time_remaining):
        ...                      # do one chunk of work
        return datetime.timedelta(minutes=5)   # sleep before the next one

    def dispose(self):           # once per run, also after SIGTERM or an exception
        ...


if __name__ == "__main__":
    Cleaner().cli()
```

## Commands

```
python cleaner.py                    # run in the foreground (same as `run`, what systemd calls)
python cleaner.py unit [--user]      # print the unit file without installing it
sudo python cleaner.py install       # system service, runs as you ($SUDO_USER), starts on boot
python cleaner.py install --user     # user service, no root needed
python cleaner.py status [--user]
python cleaner.py uninstall [--user]
```

The service is named after `name` (lowercased, unsafe characters replaced by `-`). It runs the same
interpreter and script you ran `install` with, so install from inside your virtualenv and don't move the script afterwards.

User services only run while you're logged in unless you enable lingering: `loginctl enable-linger $USER`.

## Stopping

SIGTERM/SIGINT (or calling `kill()`) cut the sleep short; the current `unit_of_work` finishes, then `dispose()` runs.
systemd waits up to 60s for this before force-killing.
