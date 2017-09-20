__all__ = [
    "Action"
      , "FSAction"
          , "RemoveDirectory"
          , "ProvideDirectory"
      , "GitAction"
          , "InitRepo"
          , "RemoteAction"
              , "AddRemote"
              , "RemoveRemote"
              , "FetchRemote"
          , "CheckoutCloned"
          , "CheckoutOrphan"
          , "MergeCloned"
          , "SubtreeMerge"
          , "CherryPick"
          , "CreateHead"
          , "DeleteHead"
          , "CreateTag"
          , "CollectGarbage"
  , "ActionContext"
  , "switch_context"
]

from shutil import rmtree
from os import (
    walk,
    environ,
    unlink,
    listdir,
    getcwd,
    chdir,
    makedirs
)
from os.path import (
    isdir,
    isfile,
    join,
    exists
)
from subprocess import (
    PIPE,
    Popen
)
from time import (
    gmtime,
    strftime
)

current_context = None

def switch_context(ctx):
    global current_context

    if current_context is ctx:
        raise RuntimeError("Same action context")

    ret = current_context
    current_context = ctx
    return ret

class ActionContext(object):
    __slots__ = ["actions"]

    def __init__(self):
        self.actions = []

def dt(ts, off):
    dt = gmtime(ts - off)
    ret = strftime("%Y-%m-%d %H:%M:%S", dt)
    if off <= 0:
        ret = ret + ("+%02d%02d" % (off / -3600, (off / -60) % 60))
    else:
        ret = ret + ("-%02d%02d" % (off / 3600, (off / 60) % 60))
    return ret

class Action(object):
    def __init__(self, **kw):
        for klass in type(self).__mro__:
            try:
                slots = klass.__slots__
            except AttributeError:
                continue

            for attr in slots:
                setattr(self, attr, kw[attr])

    def __call__(self):
        raise NotImplementedError()

    def __str__(self):
        return type(self).__name__

class FSAction(Action):
    __slots__ = ["path"]

class RemoveDirectory(FSAction):
    def __call__(self):
        if exists(self.path):
            rmtree(self.path)

class ProvideDirectory(FSAction):
    def __call__(self):
        makedirs(self.path)

class GitAction(Action):
    __slots__ = ["path"]

    def git(self, *cmd_args):
        cwd = getcwd()

        if cwd != self.path:
            chdir(self.path)

        command = ["git"]
        command.extend(cmd_args)

        p = Popen(command)
        p.wait()

        if p.returncode != 0:
            raise RuntimeError("Command failed: %s" % command)

        return p

    def git2(self, *cmd_args):
        cwd = getcwd()

        if cwd != self.path:
            chdir(self.path)

        command = ["git"]
        command.extend(cmd_args)

        p = Popen(command, stdout = PIPE, stderr = PIPE)
        p.wait()

        self.stdout, self.stderr = p.communicate()

        if p.returncode != 0:
            raise RuntimeError("Command failed: %s" % command)

        return p

class InitRepo(GitAction):
    def __call__(self):
        self.git("init")

class RemoteAction(GitAction):
    __slots__ = ["name"]

class AddRemote(RemoteAction):
    __slots__ = ["address"]

    def __call__(self):
        self.git("remote", "add", self.name, self.address)

class RemoveRemote(RemoteAction):
    def __call__(self):
        self.git("remote", "remove", self.name)

class FetchRemote(RemoteAction):
    def __call__(self):
        self.git("fetch", "--tags", self.name)

class CheckoutCloned(GitAction):
    __slots__ = ["commit"]

    def __call__(self):
        self.git("checkout", "-f", self.commit.cloned_sha)

class CheckoutOrphan(GitAction):
    __slots__ = [ "name" ]

    def __call__(self):
        self.git("checkout", "--orphan", self.name)

        self.git("reset")

        # clear the git
        for the_file in listdir(self.path):
            if the_file == ".git":
                continue

            file_path = join(self.path, the_file)

            if isfile(file_path):
                unlink(file_path)
            elif isdir(file_path):
                rmtree(file_path)

class MergeCloned(GitAction):
    __slots__ = ["commit", "author", "committer", "committed_date",
                 "authored_date", "message", "extra_parents",
                 "committer_tz_offset", "author_tz_offset"]

    def __call__(self):
        environ["GIT_COMMITTER_NAME"] = self.committer.name.encode("utf-8")
        environ["GIT_COMMITTER_EMAIL"] = self.committer.email
        environ["GIT_COMMITTER_DATE"] = dt(self.committed_date,
            self.committer_tz_offset
        )
        environ["GIT_AUTHOR_NAME"] = self.author.name.encode("utf-8")
        environ["GIT_AUTHOR_EMAIL"] = self.author.email
        environ["GIT_AUTHOR_DATE"] = dt(self.authored_date,
            self.author_tz_offset
        )

        commit = self.commit
        message = self.message

        try:
            self.git("merge",
                "--no-ff",
                "-m", message,
                *[ p.cloned_sha for p in self.extra_parents ]
            )
        except RuntimeError as e:
            # conflicts?
            self.git2("diff", "--name-only", "--diff-filter=U")
            conflicts = self.stdout.strip().split("\n")

            if not conflicts:
                # there is something else...
                raise e

            # get accepted changes from original history
            for c in conflicts:
                self.git("checkout", commit.sha, c)

            self.git("commit", "-m", message)

        del environ["GIT_COMMITTER_NAME"]
        del environ["GIT_COMMITTER_EMAIL"]
        del environ["GIT_COMMITTER_DATE"]
        del environ["GIT_AUTHOR_NAME"]
        del environ["GIT_AUTHOR_EMAIL"]
        del environ["GIT_AUTHOR_DATE"]

        self.git2("rev-parse", "HEAD")
        commit.cloned_sha = self.stdout.split("\n")[0]

class SubtreeMerge(GitAction):
    __slots__ = ["commit", "author", "committer", "committed_date",
                 "authored_date", "message", "parent", "prefix",
                 "committer_tz_offset", "author_tz_offset"]

    def __call__(self):
        environ["GIT_COMMITTER_NAME"] = self.committer.name.encode("utf-8")
        environ["GIT_COMMITTER_EMAIL"] = self.committer.email
        environ["GIT_COMMITTER_DATE"] = dt(
            self.committed_date,
            self.committer_tz_offset
        )
        environ["GIT_AUTHOR_NAME"] = self.author.name.encode("utf-8")
        environ["GIT_AUTHOR_EMAIL"] = self.author.email
        environ["GIT_AUTHOR_DATE"] = dt(
            self.authored_date,
            self.author_tz_offset
        )

        commit = self.commit
        message = self.message
        prefix = self.prefix

        # TODO --allow-unrelated-histories for Git >= 2.9
        self.git("merge", "-s", "ours", "--no-commit",
            self.parent.cloned_sha
        )

        if exists(".gic"):
            rmtree(".gic")
        makedirs(".gic")

        self.git("read-tree",
            "--prefix", ".gic/",
            "-u",
            self.parent.cloned_sha
        )

        if exists(prefix):
            rmtree(prefix)

        makedirs(prefix)

        for root, dirs, files in walk(".gic"):
            for d in dirs:
                target_dir = join(prefix + root[5:], d)

                if not exists(target_dir):
                    makedirs(target_dir)

            for f in files:
                self.git("mv", "-f",
                    join(root, f),
                    join(prefix + root[5:], f)
                )

        rmtree(".gic")

        self.git("commit", "-m", message)

        del environ["GIT_COMMITTER_NAME"]
        del environ["GIT_COMMITTER_EMAIL"]
        del environ["GIT_COMMITTER_DATE"]
        del environ["GIT_AUTHOR_NAME"]
        del environ["GIT_AUTHOR_EMAIL"]
        del environ["GIT_AUTHOR_DATE"]

        self.git2("rev-parse", "HEAD")
        commit.cloned_sha = self.stdout.split("\n")[0]

class CherryPick(GitAction):
    __slots__ = ["commit", "committer", "message", "committed_date",
                 "committer_tz_offset"]

    def __call__(self):
        c = self.commit

        # Note that author is set by cherry-pick
        environ["GIT_COMMITTER_DATE"] = dt(
            self.committed_date,
            self.committer_tz_offset
        )
        environ["GIT_COMMITTER_NAME"] = self.committer.name.encode("utf-8")
        environ["GIT_COMMITTER_EMAIL"] = self.committer.email

        try:
            self.git2("cherry-pick", c.sha)
        except RuntimeError as e:
            if "--allow-empty" not in self.stderr:
                raise e

            self.git("commit", "--allow-empty", "-m", self.message)

        del environ["GIT_COMMITTER_DATE"]
        del environ["GIT_COMMITTER_NAME"]
        del environ["GIT_COMMITTER_EMAIL"]

        self.git2("rev-parse", "HEAD")
        c.cloned_sha = self.stdout.split("\n")[0]

class CreateHead(GitAction):
    __slots__ = ["name"]

    def __call__(self):
        self.git("branch", "-f", self.name)

class DeleteHead(GitAction):
    __slots__ = ["name"]

    def __call__(self):
        self.git("branch", "-f", "-d", self.name)

class CreateTag(GitAction):
    __slots__ = ["name"]

    def __call__(self):
        self.git("tag", "-f", self.name)

class CollectGarbage(GitAction):
    def __call__(self):
        self.git("gc", "--aggressive", "--prune=all")
