#!/usr/bin/python3

from git import Repo
from argparse import (
    ArgumentTypeError,
    ArgumentParser
)
from actions import *
from os.path import (
    split,
    isdir,
    isfile
)
from common import (
    CommitDesc,
    pythonize,
    callco
)

from six import PY2
if not PY2:
    def execfile(filename, globals = None, locals = None):
        f = open(filename, "rb")
        content = f.read()
        f.close()
        obj = compile(content, filename, "exec")
        exec(content, globals, locals)

from traceback import (
    print_exc,
    format_exc
)
from sys import stdout
from os import (
    mkdir,
    rmdir,
    rename,
    unlink,
    getcwd,
    chdir
)
from itertools import count
from subprocess import (
    PIPE,
    Popen
)

class GICCommitDesc(CommitDesc):
    __slots__ = [
        "processed"
        "cloned_sha"
    ]

    def __init__(self, *args):
        super(GICCommitDesc, self).__init__(*args)

        self.cloned_sha = None
        self.processed = False

def arg_type_directory(string):
    if not isdir(string):
        raise ArgumentTypeError("'%s' is not a directory" % string)
    return string

def arg_type_git_remote(string):
    # See: https://stackoverflow.com/questions/9610131/how-to-check-the-validity-of-a-remote-git-repository-url
    test_command = Popen(["git", "ls-remote", string],
        stdout = PIPE,
        stderr = PIPE,
    )
    _stdout, _stderr = test_command.communicate()

    if test_command.returncode:
        raise ArgumentTypeError("Cannot handle '%s' as a Git repository, "
            "underlying error:\n%s" % (
                string,
                "stdout:\n%s\nstderr:\n%s" % (_stdout, _stderr)
            )
        )
    return string

def arg_type_new_directory(string):
    parent, _ = split(string)
    if not isdir(parent):
        raise ArgumentTypeError("Cannot create directory '%s' because %s is "
            "not a directory" % (string, parent)
        )

    if isdir(string):
        # The directory already exists but checking access rights by its
        # deletion is not a good way. Hence, try to create and delete other
        # directory.
        for i in count():
            name = string + str(i)
            if not isdir(name):
                break
            # else: Such directory exists too, try next.
    else:
        # no such directory, try to create one
        name = string

    try:
        mkdir(name)
    except:
        # There is no confusion between `name` and `string`, see above!
        raise ArgumentTypeError("Cannot create directory '%s', underlying "
            "error:\n%s" % (string, format_exc())
        )
    else:
        rmdir(name)

    return string

def arg_type_output_file(string):
    directory, _ = split(string)
    if not isdir(directory):
        raise ArgumentTypeError("Cannot create file '%s' because '%s' is not "
            "a directory" % (string, directory)
        )

    if isfile(string):
        # file already exists, try to open it for writing
        try:
            open(string, "ab+").close()
        except:
            raise ArgumentTypeError(
                "Cannot write to existing file '%s', underlying error:\n%s" % (
                    string, format_exc()
                )
            )
    else:
        # file does not exist, try to create it
        try:
            open(string, "wb").close()
        except:
            raise ArgumentTypeError("Cannot create file '%s', underlying "
                "error:\n%s" % (string, format_exc())
            )
        else:
            unlink(string)

    return string

SHA1_digits = "0123456789abcdef"

def arg_type_SHA1_lower(string):
    if len(string) != 40:
        raise ArgumentTypeError(
            "'%s' is not SHA1, length must be 40 digits" % string
        )

    # lower characters
    string = string.lower()

    for d in string:
        if d not in SHA1_digits:
            raise ArgumentTypeError(
                "'%s' is not SHA1, it may contains only digits 0-9 and "
                "characters a-f" % string
            )

    return string

def is_subtree(c, acceptable = 4):
    """ Heuristically detect a subtree merge.

    @acceptable:
    if the parent of @c have N files with same content but different names,
    the Git can be confused about name correspondence:

    E.g., let sys/time.h == time.h, then

    sys/time.h -> prefix/time.h
    time.h     -> prefix/sys/time.h

    is a correct Diff record (for version control system). While the assumption
    of the heuristic is violated.

    @acceptable is a threshold to handle such cases.
    """

    p1 = c.parents[1]
    d = p1.diff(c)

    # suggest a prefix
    for probe in d:
        if probe.renamed:
            break
    else:
        return None

    if probe.b_path.endswith(probe.a_path):
        prefix = probe.b_path[:-len(probe.a_path)]
    else:
        return None

    # Were all parent files renamed using same prefix?
    for po in p1.tree.traverse():
        if po.type != "blob":
            continue

        new_path = prefix + po.path

        for check in d:
            if check.renamed:
                if check.rename_from == po.path \
                and check.rename_to == new_path:
                    break
            elif check.new_file:
                if check.b_path == new_path:
                    break
        else:
            # no such difference
            if not acceptable:
                return None
            else:
                acceptable -= 1
                # print(po.path + " ACC")
                continue

        # print(po.path + " OK")

    return prefix

CLONED_REPO_NAME = "__cloned__"
STATE_FILE_NAME = ".gic-state.py"

def orphan(n):
    return "__orphan__%d" % n

def plan(repo, sha2commit, dstRepoPath,
    main_stream_bits = 0,
    breaks = None,
    skips = None
):
    breaks = set() if breaks is None else set(breaks)
    skips = set() if skips is None else set(skips)

    srcRepoPath = repo.working_dir

    queue = sorted(sha2commit.values(), key = lambda c : c.num)

    RemoveDirectory(path = dstRepoPath)
    ProvideDirectory(path = dstRepoPath)
    InitRepo(path = dstRepoPath)
    AddRemote(
        path = dstRepoPath,
        name = CLONED_REPO_NAME,
        address = srcRepoPath
    )
    FetchRemote(path = dstRepoPath, name = CLONED_REPO_NAME)

    iqueue = iter(queue)

    orphan_counter = 0

    prev_c = None

    for c in iqueue:
        c.processed = True

        if main_stream_bits and not (c.roots & main_stream_bits):
            # this commit will be used as is
            c.cloned_sha = c.sha
            continue

        m = repo.commit(c.sha)

        if prev_c is not None:
            if not c.parents:
                CheckoutOrphan(
                    name = orphan(orphan_counter),
                    path = dstRepoPath
                )
                orphan_counter += 1
                at_least_one_in_trunk = False
            else:
                # get real parents order
                main_stream_sha = m.parents[0].hexsha
                if main_stream_sha != prev_c.sha:
                    # jump to main stream commit
                    CheckoutCloned(
                        path = dstRepoPath,
                        commit_sha = main_stream_sha
                    )
                    at_least_one_in_trunk = False

        skipping = c.sha in skips

        if skipping:
            for h in c.heads:
                if h.path.startswith("refs/heads/"):
                    if at_least_one_in_trunk:
                        # Skipping a commits moves its head on first
                        # non-skipped ancestor.
                        CreateHead(
                            path = dstRepoPath,
                            name = h.name
                        )
                    else:
                        print("Head '%s' will be skipped because no commits "
                            "of this trunk are copied." % h.name
                        )
                elif h.path.startswith("refs/tags/"):
                    print("Tag '%s' will be skipped with its commit!" % h.name)
        else:
            at_least_one_in_trunk = True

            if len(c.parents) > 1:
                subtree_prefix = None if len(c.parents) != 2 else is_subtree(m)

                SetAuthor(
                    author_name = m.author.name.encode("utf-8"),
                    author_email = m.author.email,
                    authored_date = m.authored_date,
                    author_tz_offset = m.author_tz_offset
                )
                SetCommitter(
                    committer_name = m.committer.name.encode("utf-8"),
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )

                if subtree_prefix is None:
                    MergeCloned(
                        path = dstRepoPath,
                        commit_sha = c.sha,
                        message = m.message,
                        # original parents order is significant
                        extra_parents = [
                            p.hexsha for p in m.parents[1:]
                        ]
                    )
                else:
                    SubtreeMerge(
                        path = dstRepoPath,
                        commit_sha = c.sha,
                        message = m.message,
                        parent_sha = m.parents[1].hexsha,
                        prefix = subtree_prefix
                    )

                ResetAuthor()
                ResetCommitter()

            else:
                # Note that author is set by cherry-pick
                SetCommitter(
                    committer_name = m.committer.name.encode("utf-8"),
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )
                CherryPick(
                    path = dstRepoPath,
                    commit_sha = c.sha,
                    message = m.message
                )
                ResetCommitter()

            for h in c.heads:
                if h.path.startswith("refs/heads/"):
                    CreateHead(
                        path = dstRepoPath,
                        name = h.name
                    )
                elif h.path.startswith("refs/tags/"):
                    CreateTag(
                        path = dstRepoPath,
                        name = h.name
                    )

        if c.sha in breaks:
            if at_least_one_in_trunk:
                Interrupt(reason = "Interrupting as requested...")

                # Update committer name, e-mail and date after user actions.
                SetCommitter(
                    committer_name = m.committer.name.encode("utf-8"),
                    committer_email = m.committer.email,
                    committed_date = m.committed_date,
                    committer_tz_offset = m.committer_tz_offset
                )
                ContinueCommitting(
                    path = dstRepoPath,
                    commit_sha = c.sha
                )
                ResetCommitter()
            else:
                print("Cannot interrupt on '%s' because no commits "
                    "of this trunk are copied." % c.sha
                )

        prev_c = c

    # delete temporary branch names
    for o in range(0, orphan_counter):
        DeleteHead(path = dstRepoPath, name = orphan(o))

    CheckoutCloned(
        path = dstRepoPath,
        commit_sha = repo.head.commit.hexsha
    )
    RemoveRemote(path = dstRepoPath, name = CLONED_REPO_NAME)
    CollectGarbage(path = dstRepoPath)

    for c in sha2commit.values():
        if not c.processed:
            print("Commit %s was not cloned!" % str(c.sha))

def main():
    print("Git Interactive Cloner")

    init_cwd = getcwd()

    ap = ArgumentParser()
    ap.add_argument("source", type = arg_type_directory, nargs = "?")
    ap.add_argument("-d", "--destination", type = arg_type_new_directory)
    ap.add_argument("-r", "--result-state", type = arg_type_output_file)
    ap.add_argument("-m", "--main-stream",
        type = arg_type_SHA1_lower,
        metavar = "SHA1",
        help = """\
Set main stream by SHA1 of one of main stream commits. Only main stream commits
will be cloned. Other commits will be taken as is. A commit belongs to main
stream if it is a descendant of the given commit or both have at least one
common ancestor. Commonly, SHA1 corresponds to main stream initial commit."""
    )
    ap.add_argument("-b", "--break",
        type = arg_type_SHA1_lower,
        nargs = 1,
        dest = "breaks",
        metavar = "SHA1",
        help = """\
Specify break points. A break point is set on the commit identified by SHA1. \
The process will be interrupted after the commit allowing a user to change it. \
The tool will recover original committer name, e-mail and date during the next \
launch."""
    )
    ap.add_argument("-s", "--skip",
        type = arg_type_SHA1_lower,
        nargs = 1,
        dest = "skips",
        metavar = "SHA1",
        help = """\
Specify a commit to skip. Use multiple options to skip several commits. If a \
commit at break point is skipped then interruption will be made after \
previous non-skipped commit in the branch except for no commits are copied yet \
since either trunk or root."""
    )

    args = ap.parse_args()

    ctx = None
    if isfile(STATE_FILE_NAME):
        loaded = {}
        try:
            execfile(STATE_FILE_NAME, globals(), loaded)
        except:
            print("Incorrect state file")
            print_exc(file = stdout)
        else:
            for ctx in loaded.values():
                if isinstance(ctx, GitContext):
                    break
            else: # no saved context found among loaded objects
                ctx = None

    if ctx is None:
        srcRepoPath = args.source

        if srcRepoPath is None:
            print("No source repository path was given.")
            ap.print_help(stdout)
            return

        ctx = GitContext(src_repo_path = srcRepoPath)
        switch_context(ctx)
    else:
        srcRepoPath = ctx.src_repo_path

    print("Building graph of repository: " + srcRepoPath)

    repo = Repo(srcRepoPath)
    sha2commit = ctx._sha2commit
    callco(
        GICCommitDesc.co_build_git_graph(repo, sha2commit,
            skip_remotes = True,
            skip_stashes = True
        )
    )

    print("Total commits: %d" % len(sha2commit))

    if ctx.current_action < 0:
        destination = args.destination
        if destination is None:
            print("No destination specified. Dry run.")
            return

        dstRepoPath = destination

        ms = args.main_stream
        if ms:
            ms_bits = sha2commit[ms].roots
        else:
            ms_bits = 0

        print("The repository will be cloned to: " + dstRepoPath)

        # Planing
        plan(repo, sha2commit, dstRepoPath,
            breaks = args.breaks,
            skips = args.skips,
            main_stream_bits = ms_bits
        )
    else:
        print("The context was loaded. Continuing...")

        ctx.restore_cloned()

    ctx.do()

    # save results
    if getcwd() != init_cwd:
        chdir(init_cwd)

    if ctx.finished:
        if isfile(STATE_FILE_NAME):
            unlink(STATE_FILE_NAME)
    else:
        pythonize(ctx, STATE_FILE_NAME + ".tmp")

        if isfile(STATE_FILE_NAME):
            unlink(STATE_FILE_NAME)
        rename(STATE_FILE_NAME + ".tmp", STATE_FILE_NAME)

    rs = args.result_state
    if rs:
        pythonize(ctx, rs)

if __name__ == "__main__":
    ret = main()
    exit(0 if ret is None else ret)
