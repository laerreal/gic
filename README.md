# GIC - Git Interactive Cloner

The tool allows to clone an existing Git repository making changes in history.
The changes will took effect for the clone only.

## Are there analogs?

Yes, they are:

* [git-filter-branch](https://git-scm.com/docs/git-filter-branch): Uses hooks
to apply changes to Git history. A hook is a shell script. You have to
construct hooks so that the changes you want is made by those hooks in **all**
relevant commit.

* [The BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/): It is at
least 10-50x faster than git-filter-branch but providing less functionality.

**TODO**: about BFG


| Tool             | Approach                                                                                                                                                        |
|:----------------:|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| This tool        | Change commits by hand during copying. Then resolve produced conflicts.<br><br>Too hard for simple changes.                                                          |
| filter-branch    | Write a script that makes the changes for you in all relevant commits.<br><br>Writing a script to make complicated changes is equivalent to development of this tool. |
| BFG Repo-Cleaner | **TODO**                                                                                                                                                        |


## How to use it?

Clone original repository into a directory. Assume it is called
`origin_directory`.

**TODO**: referencing original repository by SSH or HHTP(S) link is not
implemented yet.

Call `gic.py` providing next information as CLI arguments.

* `-d` is destination folder. It will contain the cloned repository.
* `-b` list of SHA1 identifiers of commits to interrupt on (_break points_).
One `-b` per commit. You could change those commits using `git --amend`,
for instance.
* `origin_directory` as is after last CLI argument.

```bash
python ./gic.py \
    -d ~/destination/repo/directory \
    ~/source/repo/directory \
    -b f01fe3a921ec075374b461203b4ff24f5ec062c1 \
    -b 8a59687fe2bd1d577d95b77a5b5b66ddd99c7451
```
Note that the tool saves state into a file inside _current work directory_.

**TODO**: save state into `.git` directory of destination repository.

During first launch the tool analyzing the origin repository and play **most**
actions those have to be done to clone the origin. Break points are taken into
account at this stage.

Then the tool will begin to perform those actions one by one until either a
break point or a conflict is met.

There are several cases:

* _interruption on a break point_: You asked the tool to stop right there. So,
make the changes you want.
* _interruption on a conflict caused by **your** changes_: Resolve them by hand
and add to index.
* _interruption on a conflict like in the **origin**_: Do not touch them. The
tool will take actual changes from the origin during the next launch.
* _interruption on conflicts of mixed types_: handle it the same way. But, if
there are conflicts of both types in one file then **you** have to manage them
by hand. Refer to origin repository for help.

Now, launch the tool again. You may pass no arguments this time. All runtime
information had been saved during previous launch.

```bash
python ./gic.py
```

You probably desire to use additional features.

* `-m` specifies main stream by SHA1 of one of its commits. This is only
actual when there are several roots (initial commits without a parent). Just
pass SAH1 of **main** root. Only main stream commits will be copied, including
merge commits with non-main stream commits. Other commits will be taken as is.
Break points on non-main stream commits are ignored.
* `-r` specifies a file to save internal state of the too after the process
is finished. It is a debug option. This only takes effect for last invocations.
But use it every time because you probably cannot predict which invocation is
actually last.

## How it works?

Given origin repository the tool analyzes it and plans the sequence of actions.
Together those actions create same repository as the origin.
An action corresponds to one or several commands that a user could entered
using a terminal.
E.g. `git cherry-pick 000000` or
`export GIT_COMMITTER_EMAIL=user@example.org`.
The tool allow to change actions in the sequence making them by hand.
Then it watches consequent actions for conflicts allowing the user to resolve
them by hand.

Most actions are implemented as invocations of `git` tool. But several
actions change environment variables. They are implemented using
`os.environ`. But environment variables changing can be made by hand
using `export` shell command. Hence, it is only simplification of
development.

Environment variables are used to preserve the original author and committer
information (name, e-mail and date of each commit). So, if you change a commit,
those date will be taken from the origin.
