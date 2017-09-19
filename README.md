# GIC - Git Interactive Cloner

The tool allows to clone an existing Git repository making changes in history.
The changes will took effect for the clone only.

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
