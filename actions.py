__all__ = [
    "Action"
      , "Interrupt"
      , "FSAction"
          , "RemoveDirectory"
          , "ProvideDirectory"
          , "RemoveFile"
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
          , "ContinueCommitting"
          , "SubtreeMerge"
          , "CherryPick"
          , "CreateHead"
          , "DeleteHead"
          , "CreateTag"
          , "DeleteTag"
          , "CollectGarbage"
          , "PatchFileAction"
              , "ApplyPatchFile"
              , "HEAD2PatchFile"
          , "ApplyCache"
              , "ApplyCacheOrInterrupt"
  , "ActionContext"
      , "GitContext"
  , "LOG_STANDARD"
  , "switch_context"
  , "get_context"
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
from time import (
    time,
    timezone,
    mktime,
    strptime,
    gmtime,
    strftime
)
from traceback import print_exc
import sys
from common import (
    sloted,
    launch,
    LaunchFailed
)
from six import (
    b,
    u
)
from re import compile
from itertools import chain

current_context = None

def switch_context(ctx):
    global current_context

    if current_context is ctx:
        raise RuntimeError("Same action context")

    ret = current_context
    current_context = ctx
    return ret

def get_context():
    return current_context

def csv_excape(cell):
    if b";" in cell:
        # Note that quotes (") inside quoted cell seems to be supported
        return b'"' + cell + b'"'
    else:
        return cell

class CSVLogFormatter(sloted):
    __slots__ = ["writer", "kind"]

    def write(self, data):
        timestamp = b(dt(time(), timezone))

        # attribute lookup optimization
        kind = self.kind
        write = self.writer.write

        for ll in data.split(b"\r"):
            # Two different line separators one by one is one line separator.
            stripped = ll.strip(b"\n")

            liter = iter(stripped.split(b"\n"))

            # This forward scan logic omits last empty line. I.e. if last byte
            # of data is the line separator.
            prev_line = csv_excape(next(liter))
            for line in liter:
                write(timestamp + b";" + kind + b";" + prev_line + b";\n")
                prev_line = csv_excape(line)
            else:
                if prev_line:
                    write(timestamp + b";" + kind + b";" + prev_line + b";\n")

# Just not a `str`
LOG_STANDARD = object()

# Python 2 & 3 compatibility
raw_stdout = getattr(sys.stdout, 'buffer', sys.stdout)
raw_stderr = getattr(sys.stderr, 'buffer', sys.stderr)

class ActionContext(sloted):
    __slots__ = ["_actions", "current_action", "interrupted", "_doing",
                 "_extra_actions", "_out_log", "_err_log", "_log_io"]

    def __init__(self,
        current_action = -1,
        interrupted = False,
        log = LOG_STANDARD,
        ** kw
    ):
        super(ActionContext, self).__init__(
            current_action = current_action,
            interrupted = interrupted,
            **kw
        )

        self._actions = []
        self._extra_actions = []
        self._doing = False

        self._log_io = None
        # properties is not compatible with slots
        self.log = log

    @property
    def log(self):
        if self._out_log is raw_stdout:
            return LOG_STANDARD
        else:
            return self._log_io.name

    @log.setter
    def log(self, value):
        if self._log_io:
            self._log_io.close()
            self._log_io = None

        if value is LOG_STANDARD:
            self._out_log, self._err_log = raw_stdout, raw_stderr
        else:
            self._log_io = writer = open(value, "ab+")
            self._out_log = CSVLogFormatter(writer = writer, kind = b"stdout")
            self._err_log = CSVLogFormatter(writer = writer, kind = b"stderr")

    def interrupt(self):
        self.interrupted = True

    def do(self, limit = None):
        """ Perform actions until all actions finished or limit is exceeded or
        exception is raised.

        limit
            Set maximum number of actions to perform. None means unlimited.
        """
        actions = self._actions
        extra_actions = self._extra_actions

        ca = self.current_action
        if ca < 0: # start
            if limit is None:
                i = enumerate(actions)
            else:
                i = enumerate(actions[:limit])
        elif ca >= len(actions): # all actions were done
            print("Nothing to do")
            return True
        # continue the work
        elif limit is None:
            i = enumerate(actions[ca:], ca)
        else:
            i = enumerate(actions[ca:ca + limit], ca)

        self.interrupted = False
        self._doing = True
        ret = True

        while not self.interrupted:
            # This construction allows to switch i from within loop body. While
            # the same is wrong for constructions like `for idx, a in i:`.
            try:
                idx, a = next(i)
            except StopIteration:
                break

            try:
                a()
            except:
                print("Failed on %s" % a)
                print_exc(file = sys.stdout)
                ret = False
                break

            if extra_actions:
                next_idx = idx + 1

                while extra_actions:
                    a = extra_actions.pop()
                    actions.insert(next_idx, a)

                if limit is None:
                    i = enumerate(actions[next_idx:], next_idx)
                else:
                    rest = limit - (next_idx - ca)
                    i = enumerate(actions[next_idx:next_idx + rest], next_idx)

        self._doing = False
        self.current_action = idx + 1

        return ret

    @property
    def finished(self):
        return self.current_action >= len(self._actions)

    def __dfs_children__(self):
        return list(self._actions)

    def __gen_code__(self, g):
        self.gen_by_slots(g, log = self.log)

        g.line("switch_context(" + g.nameof(self) + ")")
        g.line()
        g.write("actions = ")
        g.pprint(self._actions)
        g.line()
        g.line()
        g.line("for a in actions:")
        g.line("    a.q()")

cache_file_re = compile("[A-Fa-f0-9]{40}.*")

class GitContext(ActionContext):
    __slots__ = ["_sha2commit", "src_repo_path", "_origin2cloned",
                 "git_command", "_git_version", "cache_path", "_cache",
                 "from_cache"]

    def __init__(self,
        git_command = "git",
        cache_path = None,
        from_cache = False,
        **kw
    ):
        super(GitContext, self).__init__(
            git_command = git_command,
            cache_path = cache_path,
            from_cache = from_cache,
            **kw
        )

        self._sha2commit = {}
        self._origin2cloned = {}

        # get version of git
        _stdout, _stderr = launch([self.git_command, "--version"],
            epfx = "Cannot get version of git"
        )

        _, _, version = _stdout.split(b" ")[:3]
        self._git_version = tuple(int(v) for v in version.split(b".")[:3])

        # walk cache_path and fill _cahce
        self._cache = cache = {}

        # refer the cache by absolute path
        cwd = getcwd()
        cache_path = self.cache_path
        if not cache_path.startswith(cwd):
            cache_path = join(cwd, cache_path)
            self.cache_path = cache_path

        if cache_path:
            for root, _, files in walk(cache_path):
                for f in files:
                    if not cache_file_re.match(f):
                        continue

                    key = b(f[:40].lower())

                    if key in cache:
                        print("Multiple entries for %s found in the "
                            "cache" % u(key)
                        )
                        continue

                    cache[key] = join(cwd, root, f)

        print("cache = " + str(self._cache)
            .replace(",", ",\n   ")
            .replace("{", "{\n    ")
            .replace("}", "\n}")
        )

    def __backup_cloned(self):
        origin2cloned = {}

        for sha, c in self._sha2commit.items():
            cloned_sha = c.cloned_sha

            if cloned_sha is None:
                continue

            origin2cloned[sha] = cloned_sha

        self._origin2cloned = origin2cloned

    def plan_set_commiter_by_env(self):
        "Inserts SetCommitter action getting its parameters from environment."

        committed_date, committer_tz_offset = gds2so(
            environ["GIT_COMMITTER_DATE"]
        )
        SetCommitter(
            committer_name = environ["GIT_COMMITTER_NAME"],
            committer_email = environ["GIT_COMMITTER_EMAIL"],
            committed_date = committed_date,
            committer_tz_offset = committer_tz_offset
        )

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

def gds2so(gds):
    "Git Date String To Seconds since epoch and time zone Offset"
    offset_str = gds[-5:]
    hours = int(offset_str[1:3])
    minutes = int(offset_str[3:])
    # sign is reverted
    sign = -1 if offset_str[0] == "+"  else 1
    offset = sign * (hours * 3600 + minutes * 60)

    datetime_str = gds[:-5]
    dt_val = strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
    ts = mktime(dt_val)

    # assert gds == dt(ts, offset)

    return (ts, offset)

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

        if current_context._doing:
            current_context._extra_actions.append(self)
        else:
            current_context._actions.append(self)

        self._ctx = current_context

    q = queue

    def _out(self, data):
        self._ctx._out_log.write(data)

    def _err(self, data):
        self._ctx._err_log.write(data)

    def __call__(self):
        raise NotImplementedError()

    def __str__(self):
        return type(self).__name__

    def __dfs_children__(self):
        return []

    def __gen_code__(self, g):
        self.gen_by_slots(g, queue = False)

class Interrupt(Action):
    __slots__ = ["reason"]

    def __call__(self):
        print(self.reason)
        self._ctx.interrupt()

class FSAction(Action):
    __slots__ = ["path"]

class RemoveDirectory(FSAction):
    def __call__(self):
        if exists(self.path):
            rmtree(self.path)

class ProvideDirectory(FSAction):
    def __call__(self):
        makedirs(self.path)

class RemoveFile(FSAction):
    def __call__(self):
        if exists(self.path):
            unlink(self.path)

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

    def launch(self, *cmd_args):
        cwd = getcwd()

        if cwd != self.path:
            chdir(self.path)

        out, err = launch(cmd_args)
        if out:
            self._out(out)
        if err:
            self._err(err)

    def git(self, *cmd_args):
        self.launch(*((self._ctx.git_command,) + cmd_args))

    def git2(self, *cmd_args):
        cwd = getcwd()

        if cwd != self.path:
            chdir(self.path)

        self._stdout, self._stderr = launch(
            (self._ctx.git_command,) + cmd_args
        )

    def get_conflicts(self):
        self.git2("diff", "--name-only", "--diff-filter=U")
        # get conflicts skipping empty lines
        conflicts = [ n for n in self._stdout.strip().split(b"\n") if n ]
        return conflicts

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
    __slots__ = [
        "tags"
    ]

    def __call__(self):
        self.git("fetch", "--%stags" % ("" if self.tags else "no-"), self.name)

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

MSG_MNG_CNFLCT_BY_SFL = """\
Try to manage it by self. Non-resolved conflicts will be taken from the \
original repository automatically after continuing. \
"""

class MergeCloned(GitAction):
    __slots__ = ["commit_sha", "message", "extra_parents"]

    def __call__(self):
        ctx = self._ctx
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
        except LaunchFailed as e:
            # conflicts?
            conflicts = self.get_conflicts()

            if not conflicts:
                # there is something else...
                raise e

            confl_str = (
                ("is merge conflict with '%s'" % conflicts[0])
                    if len (conflicts) == 1
                else "are merge conflicts"
            )
            reason = ("There %s. Interrupting... %s" % (
                confl_str, MSG_MNG_CNFLCT_BY_SFL
            ))

            if ctx.from_cache:
                ApplyCacheOrInterrupt(
                    path = self.path,
                    commit_sha = commit.sha,
                    reason = reason
                )
            else:
                # try to resolve conflicts using the cache
                if ctx.cache_path:
                    ApplyCache(path = self.path, commit_sha = commit.sha)
                # let user to resolve conflict by self
                Interrupt(reason = reason)

            # preserve original committer information
            ctx.plan_set_commiter_by_env()
            ContinueCommitting(
                path = self.path,
                commit_sha = self.commit_sha
            )
            ResetCommitter()
            return

        self.git2("rev-parse", "HEAD")
        commit.cloned_sha = self._stdout.split(b"\n")[0]

class ContinueCommitting(GitAction):
    __slots__ = ["commit_sha"]

    def __call__(self):
        sha2commit = self._ctx._sha2commit
        commit = sha2commit[self.commit_sha]

        # The behavior differs for merge commit completion and existing commit
        # overwriting.
        # Determine kind of commit to continue by presence of MERGE_MSG file.
        # Note that cherry picked commits with conflicts do store original
        # message into this file too.
        merge_msg_path = join(self.path, ".git", "MERGE_MSG")
        merging = isfile(merge_msg_path)

        if merging:
            # handle conflicts
            conflicts = self.get_conflicts()

            # get changes for unresolved conflicts from original history
            for c in conflicts:
                self.git("checkout", commit.sha, c.decode("utf-8"))

            self.git("commit", "--allow-empty", "--no-edit")
        else:
            # All changes had been added to index and committed before. Only
            # ensure that committer name, e-mail and date are correct.
            self.git("commit", "--allow-empty", "--no-edit", "--amend")

        self.git2("rev-parse", "HEAD")
        commit.cloned_sha = self._stdout.split(b"\n")[0]

class SubtreeMerge(GitAction):
    __slots__ = ["commit_sha", "message", "parent_sha", "prefix"]

    def __call__(self):
        ctx = self._ctx
        sha2commit = ctx._sha2commit
        commit = sha2commit[self.commit_sha]
        message = self.message
        prefix = self.prefix
        parent = sha2commit[self.parent_sha]

        if ctx._git_version >= (2, 9, 0):
            self.git("merge", "-s", "ours", "--no-commit",
                "--allow-unrelated-histories", parent.cloned_sha
            )
        else:
            self.git("merge", "-s", "ours", "--no-commit", parent.cloned_sha)

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
        ctx = self._ctx
        c = ctx._sha2commit[self.commit_sha]

        try:
            self.git("cherry-pick", c.sha)
        except LaunchFailed as e:
            if b"--allow-empty" in e._stderr:
                self.git("commit", "--allow-empty", "-m", self.message)
            else:
                # conflicts?
                conflicts = self.get_conflicts()

                if not conflicts:
                    # there is something else...
                    raise e

                confl_str = (
                    ("is conflict with '%s'" % conflicts[0])
                        if len (conflicts) == 1
                    else "are conflicts"
                )
                reason = ("There %s in course of cherry picking. "
                    "Interrupting... %s" % (confl_str, MSG_MNG_CNFLCT_BY_SFL))

                if ctx.from_cache:
                    ApplyCacheOrInterrupt(
                        path = self.path,
                        commit_sha = c.sha,
                        reason = reason
                    )
                else:
                    # try to resolve conflicts using the cache
                    if ctx.cache_path:
                        ApplyCache(path = self.path, commit_sha = c.sha)
                    # let user to resolve conflict by self
                    Interrupt(reason = reason)

                # preserve original committer information
                ctx.plan_set_commiter_by_env()
                ContinueCommitting(
                    path = self.path,
                    commit_sha = self.commit_sha
                )
                ResetCommitter()
                return

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
    # TODO: tag message

    def __call__(self):
        self.git("tag", "-f", self.name)

class DeleteTag(GitAction):
    __slots__ = ["name"]

    def __call__(self):
        self.git("tag", "-d", self.name)

class CollectGarbage(GitAction):
    def __call__(self):
        self.git("gc", "--aggressive", "--prune=all")

class PatchFileAction(GitAction):
    __slots__ = ["patch_name"]

class ApplyPatchFile(PatchFileAction):
    def __call__(self):
        patch_name = self.patch_name

        try:
            self.git("am", "--committer-date-is-author-date", patch_name)
        except LaunchFailed:
            self.git("am", "--abort")

            Interrupt(
                reason = "Failed to apply the patch form file '%s'" % patch_name
            )

class HEAD2PatchFile(PatchFileAction):
    def __call__(self):
        patch_name = self.patch_name

        self.git2("format-patch", "--stdout", "HEAD~1")

        f = open(patch_name, "wb")
        f.write(self._stdout)
        f.close()

re_commit_message = compile(b"(Subject: *)(\[PATCH\] *)?(.*)")

class ApplyCache(GitAction):
    __slots__ = ["commit_sha", "_changed_files", "_deleted_files",
                 "_created_files"]

    def __call__(self):
        ctx = self._ctx
        cache = ctx._cache
        sha = self.commit_sha

        if sha not in cache:
            return

        patch_file_name = cache[sha]

        print("Applying changes from " + patch_file_name)

        # analyze the patch and prepare working directory to patching
        p = open(patch_file_name, "rb")
        liter = iter(list(p.readlines()))
        p.close()

        msg = b""
        for l in liter:
            minfo = re_commit_message.match(l)
            if minfo:
                msg += minfo.group(3)
                break
        else:
            raise ValueError("Incorrect patch file: no commit message.")

        msg_lines = []
        for l in liter:
            if l.startswith(b"diff --git ") or l.startswith(b"---"):
                msg += b"".join(msg_lines[:-1])
                break
            msg_lines.append(l)
        else:
            raise ValueError(
                "Incorrect patch file: commit message terminator is not found."
            )

        changed_files = set()
        created_files = set()
        deleted_files = set()

        for l in liter:
            if l.startswith(b"--- a/"):
                file_name = l[6:].strip(b"\n\r")
                l = next(liter)
                if l.startswith(b"--- /dev/null"):
                    deleted_files.add(file_name)
                else:
                    changed_files.add(file_name)
            elif l.startswith(b"--- /dev/null"):
                l = next(liter)
                created_files.add(l[6:].strip(b"\n\r"))

        # for  n in ["changed_files", "created_files", "deleted_files"]:
        #    print(n + " = " + str(locals()[n])
        #        .replace("set([", "set([\n    ")
        #        .replace("'])", "'\n])")
        #        .replace("', '", "',\n    '")
        #    )

        s2c = ctx._sha2commit

        c = s2c[sha]

        if changed_files or deleted_files:
            p = c.parents[0]
            p_cloned_sha = p.cloned_sha

            for cf in chain(changed_files, deleted_files):
                self.git("checkout", p_cloned_sha, cf)

        for f in created_files:
            if isfile(f):
                self.launch("rm", f)

        # actual patching
        try:
            out, err = launch(["patch", "-p", "1", "-i", patch_file_name],
                epfx = "Failed to apply changes from '%s'" % patch_file_name
            )
        except LaunchFailed as e:
            out, err = e._stdout, e._stderr
            Interrupt(reason = str(e))

        if out:
            self._out(out)
        if err:
            self._err(err)

        # apply commit message
        merge_msg_path = join(self.path, ".git", "MERGE_MSG")
        if isfile(merge_msg_path):
            # a merge is in progress
            msg_f = open(merge_msg_path, "wb")
            msg_f.write(msg)
            msg_f.close()
        else:
            self.git("commit", "--only", "--amend", "-m", msg)

        self._changed_files = changed_files
        self._deleted_files = deleted_files
        self._created_files = created_files

class ApplyCacheOrInterrupt(ApplyCache):
    __slots__ = [
        "reason" # for interrupt
    ]

    def __call__(self):
        if self.commit_sha in self._ctx._cache:
            ApplyCache.__call__(self)
            # stage all changes affected by the patch
            for f in chain(self._changed_files, self._created_files,
                           self._deleted_files
            ):
                self.git("add", f)
        else:
            Interrupt(reason = self.reason)
