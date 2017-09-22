__all__ = [
    "Action"
      , "FSAction"
          , "RemoveDirectory"
          , "ProvideDirectory"
      , "SetCommitter"
      , "ResetCommitter"
      , "SetAuthor"
      , "ResetAuthor"
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
      , "GitContext"
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
from traceback import print_exc
from sys import stdout
from common import sloted

current_context = None

def switch_context(ctx):
    global current_context

    if current_context is ctx:
        raise RuntimeError("Same action context")

    ret = current_context
    current_context = ctx
    return ret

class ActionContext(sloted):
    __slots__ = ["_actions", "current_action"]

    def __init__(self, current_action = -1, **kw):
        super(ActionContext, self).__init__(
            current_action = current_action,
            **kw
        )

        self._actions = []

    def do(self, limit = None):
        ca = self.current_action
        if ca < 0: # start
            if limit is None:
                i = enumerate(self._actions)
            else:
                i = enumerate(self._actions[:limit])
        elif ca >= len(self._actions): # all actions were done
            print("Nothing to do")
            return
        # continue the work
        elif limit is None:
            i = enumerate(self._actions[ca:], ca)
        else:
            i = enumerate(self._actions[ca:ca + limit], ca)

        for idx, a in i:
            try:
                a()
            except:
                print("Failed on %s" % a)
                print_exc(file = stdout)
                break

        self.current_action = idx + 1

    @property
    def finished(self):
        return self.current_action >= len(self._actions)

    def __dfs_children__(self):
        return list(self._actions)

    def __gen_code__(self, g):
        self.gen_by_slots(g)

        g.line("switch_context(" + g.nameof(self) + ")")
        g.line()
        g.write("actions = ")
        g.pprint(self._actions)
        g.line()
        g.line()
        g.line("for a in actions:")
        g.line("    a.q()")

class GitContext(ActionContext):
    __slots__ = ["_sha2commit", "src_repo_path", "_origin2cloned"]

    def __init__(self, **kw):
        super(GitContext, self).__init__(**kw)

        self._sha2commit = {}
        self._origin2cloned = {}

    def __backup_cloned(self):
        origin2cloned = {}

        for sha, c in self._sha2commit.items():
            cloned_sha = c.cloned_sha

            if cloned_sha is None:
                continue

            origin2cloned[sha] = cloned_sha

        self._origin2cloned = origin2cloned

    def restore_cloned(self):
        sha2commit = self._sha2commit

        for sha, cloned_sha in self._origin2cloned.items():
            sha2commit[sha].cloned_sha = cloned_sha

    def __gen_code__(self, g):
        ActionContext.__gen_code__(self, g)
        g.line()

        self.__backup_cloned()

        g.write(g.nameof(self) + "._origin2cloned = ")
        g.pprint(self._origin2cloned)
        g.line()

def dt(ts, off):
    dt = gmtime(ts - off)
    ret = strftime("%Y-%m-%d %H:%M:%S", dt)
    if off <= 0:
        ret = ret + ("+%02d%02d" % (off / -3600, (off / -60) % 60))
    else:
        ret = ret + ("-%02d%02d" % (off / 3600, (off / 60) % 60))
    return ret

class Action(sloted):
    __slots__ = ["_ctx"]

    def __init__(self, queue = True, ** kw):
        """
        @queue: auto add the action to queue of the current action context
        """
        super(Action, self).__init__(**kw)

        self._ctx = None
        if queue:
            self.q()

    def queue(self):
        if self._ctx is not None:
            raise RuntimeError("Already in the action context")

        global current_context

        if current_context is None:
            raise RuntimeError("No action context set")

        current_context._actions.append(self)
        self._ctx = current_context

    q = queue

    def __call__(self):
        raise NotImplementedError()

    def __str__(self):
        return type(self).__name__

    def __dfs_children__(self):
        return []

    def __gen_code__(self, g):
        self.gen_by_slots(g, queue = False)

class FSAction(Action):
    __slots__ = ["path"]

class RemoveDirectory(FSAction):
    def __call__(self):
        if exists(self.path):
            rmtree(self.path)

class ProvideDirectory(FSAction):
    def __call__(self):
        makedirs(self.path)

class SetCommitter(Action):
    __slots__ = ["committer_name", "committer_email", "committed_date",
                 "committer_tz_offset"]

    def __call__(self):
        environ["GIT_COMMITTER_NAME"] = self.committer_name
        environ["GIT_COMMITTER_EMAIL"] = self.committer_email
        environ["GIT_COMMITTER_DATE"] = dt(self.committed_date,
            self.committer_tz_offset
        )

class ResetCommitter(Action):
    def __call__(self):
        try:
            del environ["GIT_COMMITTER_NAME"]
            del environ["GIT_COMMITTER_EMAIL"]
            del environ["GIT_COMMITTER_DATE"]
        except KeyError:
            # If process was interrupted the env. var. values are lost.
            pass

class SetAuthor(Action):
    __slots__ = ["author_name", "author_email", "authored_date",
                 "author_tz_offset"]

    def __call__(self):
        environ["GIT_AUTHOR_NAME"] = self.author_name
        environ["GIT_AUTHOR_EMAIL"] = self.author_email
        environ["GIT_AUTHOR_DATE"] = dt(self.authored_date,
            self.author_tz_offset
        )

class ResetAuthor(Action):
    def __call__(self):
        try:
            del environ["GIT_AUTHOR_NAME"]
            del environ["GIT_AUTHOR_EMAIL"]
            del environ["GIT_AUTHOR_DATE"]
        except KeyError:
            pass

class GitAction(Action):
    __slots__ = ["path", "_stdout", "_stderr"]

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

        self._stdout, self._stderr = p.communicate()

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
    __slots__ = ["commit_sha"]

    def __call__(self):
        commit = self._ctx._sha2commit[self.commit_sha]

        self.git("checkout", "-f", commit.cloned_sha)

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
    __slots__ = ["commit_sha", "message", "extra_parents"]

    def __call__(self):
        sha2commit = self._ctx._sha2commit
        commit = sha2commit[self.commit_sha]
        message = self.message

        extra_parents = [
            sha2commit[p] for p in self.extra_parents
        ]

        try:
            self.git("merge",
                "--no-ff",
                "-m", message,
                *[ p.cloned_sha for p in extra_parents ]
            )
        except RuntimeError as e:
            # conflicts?
            self.git2("diff", "--name-only", "--diff-filter=U")
            conflicts = self._stdout.strip().split(b"\n")

            if not conflicts:
                # there is something else...
                raise e

            # get accepted changes from original history
            for c in conflicts:
                self.git("checkout", commit.sha, c.decode("utf-8"))

            self.git("commit", "-m", message)

        self.git2("rev-parse", "HEAD")
        commit.cloned_sha = self._stdout.split(b"\n")[0]

class SubtreeMerge(GitAction):
    __slots__ = ["commit_sha", "message", "parent_sha", "prefix"]

    def __call__(self):
        sha2commit = self._ctx._sha2commit
        commit = sha2commit[self.commit_sha]
        message = self.message
        prefix = self.prefix
        parent = sha2commit[self.parent_sha]

        # TODO --allow-unrelated-histories for Git >= 2.9
        self.git("merge", "-s", "ours", "--no-commit",
            parent.cloned_sha
        )

        if exists(".gic"):
            rmtree(".gic")
        makedirs(".gic")

        self.git("read-tree",
            "--prefix", ".gic/",
            "-u",
            parent.cloned_sha
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

        self.git2("rev-parse", "HEAD")
        commit.cloned_sha = self._stdout.split(b"\n")[0]

class CherryPick(GitAction):
    __slots__ = ["commit_sha", "message"]

    def __call__(self):
        c = self._ctx._sha2commit[self.commit_sha]

        try:
            self.git2("cherry-pick", c.sha)
        except RuntimeError as e:
            if b"--allow-empty" not in self._stderr:
                raise e

            self.git("commit", "--allow-empty", "-m", self.message)

        self.git2("rev-parse", "HEAD")
        c.cloned_sha = self._stdout.split(b"\n")[0]

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
