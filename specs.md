Custodian is a project that is both literally and conceptually inherited from by concrete implementations.

A custodian is just a process that runs "infinitely." It does this by using a Python script that runs for a configured
amount of time before closing and systemctl to monitor it and restart it when it closes.

To do this we need to register the process as a service on the machine.

This sub project makes that as easy as possilbe.