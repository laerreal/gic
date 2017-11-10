__all__ = [
    "outbytes",
    "errbytes",
    "launch",
    "LaunchFailed"
]

from subprocess import (
    Popen,
    PIPE
)

import sys

if sys.version_info[0] == 3:
    def outbytes(*args):
        sys.stdout.buffer.write(*args)
        sys.stdout.flush()

    def errbytes(*args):
        sys.stderr.buffer.write(*args)
        sys.stderr.flush()
else:
    def outbytes(*args):
        sys.stdout.write(*args)
        sys.stdout.flush()

    def errbytes(*args):
        sys.stderr.write(*args)
        sys.stderr.flush()

class LaunchFailed(Exception):
    def __init__(self, returncode, _stdout, _stderr, *args, **kw):
        super(LaunchFailed, self).__init__(*args, **kw)

        self.returncode = returncode
        self._stdout = _stdout
        self._stderr = _stderr

def launch(cmd, epfx = None, flush = False):
    p = Popen(cmd, stdout = PIPE, stderr = PIPE)

    _stdout, _stderr = p.communicate()
    returncode = p.returncode

    if returncode:
        if epfx is None:
            error_prefix = "Launch of command %s has failed" % " ".join(cmd)
        else:
            error_prefix = epfx

        if flush:
            outbytes(_stdout)
            errbytes(_stderr)

        raise LaunchFailed(returncode, _stdout, _stderr,
            error_prefix + "\n  stdout:\\\n%sEoF\n  stderr:\\\n%sEoF\n" % (
                _stdout.decode(sys.stdout.encoding),
                _stderr.decode(sys.stderr.encoding)
            )
        )

    if flush:
        outbytes(_stdout)
        errbytes(_stderr)

    return (_stdout, _stderr)
