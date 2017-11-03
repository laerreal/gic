#!/usr/bin/python3

from git import Repo
from argparse import (
    ArgumentTypeError,
    ArgumentParser
)
from actions import (
    GitContext,
    switch_context,
    RemoveDirectory
)
from os.path import (
    join,
    split,
    isdir,
    isfile
)
from common import (
    pythonize,
    callco
)
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
from shutil import rmtree
from itertools import count
from subprocess import (
    PIPE,
    Popen
)
from core import (
    GICCommitDesc,
    plan,
    load_context
)

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

def arg_type_git_repository(string):
    try:
        string = arg_type_directory(string)
    except ArgumentTypeError:
        # It is not a directory. It could be a remote.
        string = arg_type_git_remote(string)
    else:
        # It s a directory. Check if it is a Git repository.
        try:
            Repo(string)
        except:
            raise ArgumentTypeError("Cannot open directory '%s' as a Git "
                "repository, underlying error:\n %s" % (
                    string, format_exc()
            ))

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

def arg_type_git_ref_name_internal(ref, string):
    full_name = "refs/%ss/%s" % (ref, string)

    check_ref_format = Popen(
        ["git", "check-ref-format", full_name],
        stdout = PIPE,
        stderr = PIPE
    )

    _stdout, _stderr = check_ref_format.communicate()
    if check_ref_format.returncode:
        raise ArgumentTypeError("Incorrect %s name '%s' (%s), Git stdout:\n"
            "%s\nstderr:\n%s\n" % (
                ref, string, full_name, _stdout, _stderr
            )
        )

    return full_name

def arg_type_git_head_name(string):
    return arg_type_git_ref_name_internal("head", string)

STATE_FILE_NAME = ".gic-state.py"

def main():
    print("Git Interactive Cloner")

    init_cwd = getcwd()

    ap = ArgumentParser()
    ap.add_argument("source", type = arg_type_git_repository, nargs = "?")
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
        action = 'append',
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
        action = 'append',
        dest = "skips",
        metavar = "SHA1",
        help = """\
Specify a commit to skip. Use multiple options to skip several commits. If a \
commit at break point is skipped then interruption will be made after \
previous non-skipped commit in the branch except for no commits are copied yet \
since either trunk or root."""
    )
    ap.add_argument("-H", "--head",
        type = arg_type_git_head_name,
        action = 'append',
        dest = "heads",
        metavar = "name_of_head",
        help = """\
Copy commits those are ancestors of selected heads only (including the
heads)."""
    )

    args = ap.parse_args()

    ctx = None
    if isfile(STATE_FILE_NAME):
        try:
            ctx = load_context(STATE_FILE_NAME)
        except:
            print("Incorrect state file")
            print_exc(file = stdout)

    cloned_source = None

    if ctx is None:
        source = args.source

        if source is None:
            print("No source repository path was given.")
            ap.print_help(stdout)
            return

        try:
            remote = arg_type_git_remote(source)
        except ArgumentTypeError:
            # Source points to a local repository.
            srcRepoPath = source
        else:
            # Source points to a remote repository. It must be cloned first
            # because git.Repo cannot work with a remote repository.
            cloned_source = join(init_cwd, ".gic-cloned-source")
            try:
                cloned_source = arg_type_new_directory(cloned_source)
            except ArgumentTypeError:
                raise RuntimeError("Cannot clone source repository into local "
                    "temporal directory '%s', underlying error:\n%s" % (
                        cloned_source, format_exc()
                    )
                )

            print("Cloning source repository into local temporal directory "
                "'%s'" % cloned_source
            )

            # delete existing copy
            if isdir(cloned_source):
                rmtree(cloned_source)

            cloning = Popen(["git", "clone", remote, cloned_source])
            cloning.wait()

            if cloning.returncode:
                raise RuntimeError("Cloning has failed.")
                rmtree(cloned_source)

            # create all branches in temporal copy
            tmp_repo = Repo(cloned_source)

            chdir(cloned_source)

            for ref in list(tmp_repo.references):
                if not ref.path.startswith("refs/remotes/origin/"):
                    continue

                # cut out prefix "origin/"
                branch = ref.name[7:]

                if branch == "HEAD" or branch == "master":
                    continue

                add_branch = Popen(
                    ["git", "branch", branch, ref.name],
                    stdout = PIPE,
                    stderr = PIPE
                )
                _stdout, _stderr = add_branch.communicate()

                if add_branch.returncode:
                    chdir(init_cwd)
                    rmtree(cloned_source)

                    raise RuntimeError("Cannot create tracking branch '%s' "
                        "in temporal copy of origin repository, Git stdout:\n"
                        "%s\nstderr:\n%s\n" % (branch, _stdout, _stderr)
                    )

            chdir(init_cwd)

            srcRepoPath = cloned_source

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
            skip_stashes = True,
            refs = args.heads
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

        # remove temporal clone of the source repository
        if cloned_source:
            RemoveDirectory(path = cloned_source)
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
