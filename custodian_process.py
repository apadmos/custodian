import argparse
import datetime
import getpass
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Sequence

SYSTEM_UNIT_DIR = Path("/etc/systemd/system")
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"


class CustodianProcess:
    """A process that runs "forever".

    Subclass it, implement ``unit_of_work`` (and optionally ``initialize`` / ``dispose``),
    then call ``cli()`` from your script's ``__main__`` block.

    ``run`` loops over ``unit_of_work`` until ``restart_every`` has elapsed, then exits cleanly.
    systemd (``Restart=always``) starts it again, which keeps leaks and stale state from piling up.
    An exception in ``unit_of_work`` also ends the process (after ``dispose``), and systemd restarts it.
    """

    def __init__(self,
                 name: str,
                 restart_every: Optional[datetime.timedelta] = None,
                 description: Optional[str] = None):
        self.name = name
        self.restart_every = restart_every or datetime.timedelta(hours=12)
        self.description = description or f"Custodian process {name}"
        self._kill_event = threading.Event()

    # ------------------------------------------------------------------ #
    # Hooks for subclasses
    # ------------------------------------------------------------------ #

    def unit_of_work(self, time_remaining: datetime.timedelta) -> datetime.timedelta:
        """Do one chunk of work.

        :param time_remaining: how long until this run ends and systemd restarts the process.
        :return: how long to sleep before the next call.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement unit_of_work")

    def initialize(self) -> None:
        """Called once at the start of each run, before the first unit of work."""

    def dispose(self) -> None:
        """Called once at the end of each run, also after a kill or an exception."""

    # ------------------------------------------------------------------ #
    # Running
    # ------------------------------------------------------------------ #

    @property
    def kill_requested(self) -> bool:
        return self._kill_event.is_set()

    def kill(self, *_signal_args) -> None:
        """Ask the loop to stop after the current unit of work. Safe from signal handlers and other threads."""
        self._kill_event.set()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.kill)
        signal.signal(signal.SIGINT, self.kill)

        started = datetime.datetime.now()
        self.initialize()
        try:
            while not self.kill_requested:
                time_remaining = self.restart_every - (datetime.datetime.now() - started)
                if time_remaining <= datetime.timedelta(0):
                    break
                sleep_for = self.unit_of_work(time_remaining=time_remaining)
                # never sleep past the restart deadline; wakes immediately on kill()
                time_remaining = self.restart_every - (datetime.datetime.now() - started)
                wait_seconds = min(sleep_for, time_remaining).total_seconds()
                if wait_seconds > 0:
                    self._kill_event.wait(wait_seconds)
        finally:
            self.dispose()

    # ------------------------------------------------------------------ #
    # systemd service management
    # ------------------------------------------------------------------ #

    @property
    def service_name(self) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.name.strip()).strip("-").lower()
        if not slug:
            raise ValueError(f"Cannot build a service name from {self.name!r}")
        return slug

    @staticmethod
    def unit_dir(user: bool) -> Path:
        return USER_UNIT_DIR if user else SYSTEM_UNIT_DIR

    def unit_path(self, user: bool) -> Path:
        return self.unit_dir(user) / f"{self.service_name}.service"

    def exec_start(self, script_path: Optional[str] = None) -> str:
        """The command systemd runs: this interpreter, this script, ``run``."""
        script = Path(script_path or sys.argv[0]).resolve()
        return shlex.join([sys.executable, str(script), "run"])

    def unit_file_contents(self,
                           user: bool = False,
                           script_path: Optional[str] = None,
                           run_as: Optional[str] = None,
                           restart_sec: int = 5) -> str:
        script = Path(script_path or sys.argv[0]).resolve()
        lines = [
            "[Unit]",
            f"Description={self.description}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={self.exec_start(str(script))}",
            f"WorkingDirectory={script.parent}",
            "Environment=PYTHONUNBUFFERED=1",
            "Restart=always",
            f"RestartSec={restart_sec}",
            # run() needs a moment after SIGTERM to finish its unit of work and dispose()
            "TimeoutStopSec=60",
        ]
        if not user:
            lines.append(f"User={run_as or os.environ.get('SUDO_USER') or getpass.getuser()}")
        lines += [
            "",
            "[Install]",
            f"WantedBy={'default.target' if user else 'multi-user.target'}",
            "",
        ]
        return "\n".join(lines)

    def _systemctl(self, user: bool, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["systemctl"] + (["--user"] if user else []) + list(args)
        return subprocess.run(cmd, check=check)

    def install(self,
                user: bool = False,
                start: bool = True,
                script_path: Optional[str] = None,
                run_as: Optional[str] = None) -> Path:
        """Register this as a systemd service named after ``self.name`` and enable it.

        System services (default) need root: ``sudo python my_script.py install``.
        The service runs as the invoking user (``$SUDO_USER``) unless ``run_as`` is given.
        ``user=True`` installs a user service instead and needs no root; it only runs while
        you're logged in unless lingering is on (``loginctl enable-linger``).
        """
        path = self.unit_path(user)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.unit_file_contents(user=user, script_path=script_path, run_as=run_as))
        self._systemctl(user, "daemon-reload")
        self._systemctl(user, "enable", *(["--now"] if start else []), self.service_name)
        return path

    def uninstall(self, user: bool = False) -> None:
        self._systemctl(user, "disable", "--now", self.service_name)
        self.unit_path(user).unlink()
        self._systemctl(user, "daemon-reload")

    def status(self, user: bool = False) -> int:
        return self._systemctl(user, "status", "--no-pager", self.service_name, check=False).returncode

    # ------------------------------------------------------------------ #
    # Command line
    # ------------------------------------------------------------------ #

    def cli(self, argv: Optional[Sequence[str]] = None) -> None:
        """Entry point for a custodian script.

            python my_script.py [run]            run in the foreground (what systemd calls)
            python my_script.py install [--user] [--no-start] [--run-as USER]
            python my_script.py uninstall [--user]
            python my_script.py status [--user]
            python my_script.py unit [--user]    print the unit file without installing
        """
        parser = argparse.ArgumentParser(prog=Path(sys.argv[0]).name, description=self.description)
        sub = parser.add_subparsers(dest="command")
        sub.add_parser("run", help="run in the foreground (default)")
        for cmd, help_text in (("install", "register and enable as a systemd service"),
                               ("uninstall", "stop, disable and remove the systemd service"),
                               ("status", "show systemctl status"),
                               ("unit", "print the unit file that install would write")):
            p = sub.add_parser(cmd, help=help_text)
            p.add_argument("--user", action="store_true", help="use a systemd user service instead of a system one")
            if cmd in ("install", "unit"):
                p.add_argument("--run-as", help="user the system service runs as (default: $SUDO_USER or current user)")
            if cmd == "install":
                p.add_argument("--no-start", action="store_true", help="enable but don't start now")

        args = parser.parse_args(argv)
        command = args.command or "run"
        if command == "run":
            self.run()
        elif command == "install":
            path = self.install(user=args.user, start=not args.no_start, run_as=args.run_as)
            print(f"Installed {path}")
        elif command == "uninstall":
            self.uninstall(user=args.user)
        elif command == "status":
            sys.exit(self.status(user=args.user))
        elif command == "unit":
            print(self.unit_file_contents(user=args.user, run_as=args.run_as), end="")
